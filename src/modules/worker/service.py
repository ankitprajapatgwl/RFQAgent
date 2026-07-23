"""Email-processing logic for the background worker.

:class:`EmailProcessingWorker` owns one *tick* of work: pull the oldest received
email still awaiting processing, hand it to the extractor, and record the
outcome so it is never picked up twice. It deliberately knows nothing about
*scheduling* — the polling loop and its thread live in
:mod:`src.modules.worker.runner`, keeping the "what to do" (this file) separate
from the "when to do it" (the runner), which makes this class trivially
unit-testable with a plain in-memory database and a fake extractor.

The worker is the orchestrator here (AgenticAI Rule 4): it selects the work and
owns the source email's status transition, while the injected
:class:`EmailExtractor` owns the extraction itself. The two are commit together
in one transaction so a tick either fully succeeds or rolls back untouched.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from src.integrations.database import Database
from src.modules.email_delivery.models import Email
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.observability import get_logger

logger = get_logger(__name__)


class EmailExtractor(Protocol):
    """The extraction capability the worker depends on.

    Declared as a :class:`~typing.Protocol` so the worker depends on a behaviour,
    not a concrete class — the real
    :class:`~src.modules.email_extraction.agent.EmailExtractorAgent` satisfies it
    in production, and a trivial fake satisfies it in unit tests (Testing rule:
    unit tests mock the LLM).
    """

    def extract_and_store(self, *, session: Session, email: Email) -> bool:
        """Extract details from ``email`` within ``session`` and store them.

        Returns:
            ``True`` if extraction succeeded, ``False`` if it failed (a failed
            record is still stored either way).
        """
        ...


class EmailProcessingWorker:
    """Processes one pending received email per invocation.

    Args:
        database: The shared database facade used to open a short-lived,
            transactional session for each tick.
        extractor: The extractor each pending email is handed to.
    """

    def __init__(self, database: Database, extractor: EmailExtractor) -> None:
        """Bind the worker to the database it draws work from and its extractor."""
        self._database = database
        self._extractor = extractor

    def process_next(self) -> bool:
        """Process the single oldest unprocessed received email, if any.

        Opens its own transactional session so a tick either fully succeeds
        (email extracted *and* its status updated, committed together) or rolls
        back untouched — the same email is then retried on the next tick. A
        deterministic extraction failure marks the email ``failed`` rather than
        leaving it ``pending``, so one bad record never blocks the queue.

        Returns:
            ``True`` if an email was found and handled, ``False`` if the queue
            was empty (nothing to do this tick).
        """
        with self._database.session() as session:
            repository = EmailDeliveryRepository(session)
            email = repository.get_oldest_unprocessed_received_email()
            if email is None:
                return False

            succeeded = self._extractor.extract_and_store(session=session, email=email)
            if succeeded:
                repository.mark_email_processed(email)
            else:
                repository.mark_email_failed(email)
            return True
