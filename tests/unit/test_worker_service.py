"""Unit tests for the background worker's processing logic.

Exercises :meth:`EmailProcessingWorker.process_next` against a real in-memory
SQLite database (no threads, no scheduling — those live in ``runner.py``):
oldest-received-first ordering, mark-as-processed, sent emails ignored, the
empty-queue case, and the failed-extraction path. The extractor is a trivial
fake (Testing rule: unit tests never call a real LLM), so these tests stay
about the worker's queue/status logic, not extraction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session
from src.config.settings import Settings
from src.integrations.database import Database
from src.modules.auth.repository import UserRepository
from src.modules.email_delivery.enums import EmailDirection, EmailProcessingStatus
from src.modules.email_delivery.models import Email
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.worker.service import EmailProcessingWorker

_DOMAIN = "mail.example.com"
_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeExtractor:
    """Stand-in extractor recording calls and returning a fixed outcome."""

    def __init__(self, *, succeed: bool = True) -> None:
        self._succeed = succeed
        self.calls: list[uuid.UUID] = []

    def extract_and_store(self, *, session: Session, email: Email) -> bool:
        """Record the email handled and report the configured outcome."""
        self.calls.append(email.id)
        return self._succeed


@pytest.fixture
def database() -> Database:
    """A Database facade backed by a fresh in-memory SQLite schema."""
    db = Database(Settings(database_url="sqlite:///:memory:", environment="testing", debug=False))
    db.create_all()
    return db


@pytest.fixture
def worker(database: Database) -> EmailProcessingWorker:
    """A worker drawing from the in-memory database, with a succeeding extractor."""
    return EmailProcessingWorker(database, _FakeExtractor())


def _seed_conversation_with_emails(database: Database) -> dict[str, uuid.UUID]:
    """Create one conversation with a sent email and two received replies.

    Timestamps are set explicitly so the first received reply is unambiguously
    the oldest, making the FIFO assertions deterministic.

    Returns:
        Mapping of ``sent`` / ``first`` / ``second`` to their email ids.
    """
    with database.session() as session:
        user = UserRepository(session).create(
            email="jane@buyer.com",
            full_name="Jane Doe",
            hashed_password="x",
            sending_email=f"jane@{_DOMAIN}",
        )
        session.flush()

        repository = EmailDeliveryRepository(session)
        conversation = repository.create_conversation(
            user_id=user.id,
            token="abcd1234",
            reply_to_address=f"jane.abcd1234@{_DOMAIN}",
            provider="engagelab",
            supplier_email="supplier@acme.com",
        )

        sent = repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.SENT,
            from_email=f"jane@{_DOMAIN}",
            to_email="supplier@acme.com",
            subject="RFQ",
        )
        first = repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.RECEIVED,
            from_email="supplier@acme.com",
            to_email=f"jane@{_DOMAIN}",
            subject="Re: RFQ (first)",
        )
        second = repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.RECEIVED,
            from_email="supplier@acme.com",
            to_email=f"jane@{_DOMAIN}",
            subject="Re: RFQ (second)",
        )

        sent.created_at = _BASE_TIME
        first.created_at = _BASE_TIME + timedelta(seconds=10)
        second.created_at = _BASE_TIME + timedelta(seconds=20)
        session.flush()

        return {"sent": sent.id, "first": first.id, "second": second.id}


def _status(database: Database, email_id: uuid.UUID) -> str:
    """Return the persisted ``processing_status`` of the given email."""
    with database.session() as session:
        email = session.get(Email, email_id)
        assert email is not None
        return email.processing_status


def test_process_next_handles_oldest_received_first(
    database: Database, worker: EmailProcessingWorker
) -> None:
    ids = _seed_conversation_with_emails(database)

    assert worker.process_next() is True

    # The earliest-saved received reply is the one that got processed.
    assert _status(database, ids["first"]) == EmailProcessingStatus.PROCESSED.value
    assert _status(database, ids["second"]) == EmailProcessingStatus.PENDING.value


def test_process_next_ignores_sent_emails(
    database: Database, worker: EmailProcessingWorker
) -> None:
    ids = _seed_conversation_with_emails(database)

    # Drain both received replies.
    assert worker.process_next() is True
    assert worker.process_next() is True

    # Both received are processed; the sent email is never picked up.
    assert _status(database, ids["first"]) == EmailProcessingStatus.PROCESSED.value
    assert _status(database, ids["second"]) == EmailProcessingStatus.PROCESSED.value
    assert _status(database, ids["sent"]) == EmailProcessingStatus.PENDING.value

    # Queue is now empty of pending received emails.
    assert worker.process_next() is False


def test_process_next_returns_false_when_queue_empty(
    worker: EmailProcessingWorker,
) -> None:
    assert worker.process_next() is False


def test_process_next_marks_failed_when_extraction_fails(database: Database) -> None:
    ids = _seed_conversation_with_emails(database)
    worker = EmailProcessingWorker(database, _FakeExtractor(succeed=False))

    # A tick still consumes the email (it is handled), but a failed extraction
    # moves it to FAILED rather than PROCESSED so it is not retried forever.
    assert worker.process_next() is True
    assert _status(database, ids["first"]) == EmailProcessingStatus.FAILED.value
    # The next-oldest pending reply is untouched and still awaits processing.
    assert _status(database, ids["second"]) == EmailProcessingStatus.PENDING.value


def test_process_next_passes_received_email_to_extractor(database: Database) -> None:
    ids = _seed_conversation_with_emails(database)
    extractor = _FakeExtractor()
    worker = EmailProcessingWorker(database, extractor)

    assert worker.process_next() is True
    # The oldest received reply — not the sent email — is the one extracted.
    assert extractor.calls == [ids["first"]]
