"""Email-processing logic for the background worker.

:class:`EmailProcessingWorker` owns one *tick* of work: pull the oldest received
email still awaiting processing, hand it downstream, and mark it processed so it
is never picked up twice. It deliberately knows nothing about *scheduling* — the
polling loop and its thread live in :mod:`src.modules.worker.runner`, keeping the
"what to do" (this file) separate from the "when to do it" (the runner), which
makes this class trivially unit-testable with a plain in-memory database.

The actual processing of a reply (quote extraction, negotiation, ...) is future
work; for now :meth:`_process` only logs the record.
"""

from __future__ import annotations

from src.integrations.database import Database
from src.modules.email_delivery.models import Email
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.observability import get_logger

logger = get_logger(__name__)


class EmailProcessingWorker:
    """Processes one pending received email per invocation.

    Args:
        database: The shared database facade used to open a short-lived,
            transactional session for each tick.
    """

    def __init__(self, database: Database) -> None:
        """Bind the worker to the database it draws work from."""
        self._database = database

    def process_next(self) -> bool:
        """Process the single oldest unprocessed received email, if any.

        Opens its own transactional session so a tick either fully succeeds
        (email handled *and* marked processed, committed together) or rolls
        back untouched — the same email is then retried on the next tick.

        Returns:
            ``True`` if an email was found and processed, ``False`` if the
            queue was empty (nothing to do this tick).
        """
        with self._database.session() as session:
            repository = EmailDeliveryRepository(session)
            email = repository.get_oldest_unprocessed_received_email()
            if email is None:
                return False

            self._process(email)
            repository.mark_email_processed(email)
            return True

    def _process(self, email: Email) -> None:
        """Handle one received email.

        Placeholder for the real processing pipeline (added later). Logs the
        record and prints it so you can see what's happening.

        Args:
            email: The received email to process.
        """
        message = (
            f"✓ WORKER PROCESSING EMAIL\n"
            f"  ID: {email.id}\n"
            f"  Conversation: {email.conversation_id}\n"
            f"  From: {email.from_email}\n"
            f"  Subject: {email.subject}\n"
            f"  Saved at: {email.created_at.isoformat()}"
        )
        print(message)
        logger.info(
            "Processing email id=%s conversation=%s from=%s subject=%r saved_at=%s",
            email.id,
            email.conversation_id,
            email.from_email,
            email.subject,
            email.created_at.isoformat(),
        )
