"""Worker module — background processing of unprocessed emails.

A plain-threading background worker (no Celery/broker) started on application
startup. Every ``worker_poll_interval_seconds`` it looks for the oldest received
email still awaiting processing, hands it off, and marks it processed so it is
picked up exactly once, draining the queue in arrival order (FIFO).

    service.py -- EmailProcessingWorker: one tick of "process the next email"
    runner.py  -- EmailWorkerRunner + start/stop helpers wired into the app lifespan

``start_email_worker`` / ``stop_email_worker`` are the entry points the FastAPI
app factory calls on startup/shutdown (see ``src.api.main``).
"""

from src.modules.worker.runner import (
    EmailWorkerRunner,
    start_email_worker,
    stop_email_worker,
)
from src.modules.worker.service import EmailProcessingWorker

__all__ = [
    "EmailProcessingWorker",
    "EmailWorkerRunner",
    "start_email_worker",
    "stop_email_worker",
]
