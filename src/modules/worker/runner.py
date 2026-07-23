"""Background scheduling for the email-processing worker.

A deliberately plain design — a single ``threading.Thread`` and a
``threading.Event``, no Celery, broker, or external scheduler. The thread wakes
every ``worker_poll_interval_seconds`` (see :mod:`src.config.settings`), asks the
:class:`~src.modules.worker.service.EmailProcessingWorker` to handle the next
pending email, and loops. The ``Event`` doubles as both the interval sleep and a
responsive stop signal, so shutdown is immediate rather than blocking for a full
interval.

:func:`start_email_worker` / :func:`stop_email_worker` are the two entry points
the FastAPI app lifespan uses (see :mod:`src.api.main`).
"""

from __future__ import annotations

import threading

from src.config import Settings
from src.integrations.database import Database, get_database
from src.modules.worker.service import EmailProcessingWorker
from src.observability import get_logger

logger = get_logger(__name__)

# How long shutdown waits for the worker thread to finish its current tick.
_JOIN_TIMEOUT_SECONDS = 5.0


class EmailWorkerRunner:
    """Runs an :class:`EmailProcessingWorker` on a fixed interval in a thread.

    Args:
        worker: The worker performing one tick of processing.
        interval_seconds: Seconds to wait between ticks.
    """

    def __init__(self, worker: EmailProcessingWorker, interval_seconds: float) -> None:
        """Configure the runner; the thread is not started until :meth:`start`."""
        self._worker = worker
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background thread; a no-op if it is already running."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Email worker already running; start() ignored.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="email-worker", daemon=True)
        self._thread.start()
        logger.info("Email worker started (poll interval=%.1fs).", self._interval_seconds)

    def stop(self) -> None:
        """Signal the loop to stop and wait briefly for the thread to exit."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
            if thread.is_alive():
                logger.warning("Email worker did not stop within the join timeout.")
        self._thread = None
        logger.info("Email worker stopped.")

    def _run(self) -> None:
        """Poll for and process one email every interval until stopped.

        ``Event.wait`` returns ``True`` the moment :meth:`stop` is called and
        ``False`` on timeout, so it serves as both the interval sleep and the
        loop's exit check. Any error in a tick is logged and swallowed — a
        background loop must never die on a single bad record.
        """
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._worker.process_next()
            except Exception:
                logger.exception("Email worker tick failed; continuing.")


def start_email_worker(
    settings: Settings, database: Database | None = None
) -> EmailWorkerRunner | None:
    """Build and start the email worker, honouring the ``worker_enabled`` flag.

    Args:
        settings: Application settings (enable flag + poll interval).
        database: Database facade to draw work from; defaults to the process
            singleton.

    Returns:
        The started :class:`EmailWorkerRunner`, or ``None`` when the worker is
        disabled via configuration.
    """
    if not settings.worker_enabled:
        logger.info("Email worker disabled (worker_enabled=False); not starting.")
        return None
    worker = EmailProcessingWorker(database or get_database())
    runner = EmailWorkerRunner(worker, settings.worker_poll_interval_seconds)
    runner.start()
    return runner


def stop_email_worker(runner: EmailWorkerRunner | None) -> None:
    """Stop a runner started by :func:`start_email_worker` (``None`` is a no-op)."""
    if runner is not None:
        runner.stop()
