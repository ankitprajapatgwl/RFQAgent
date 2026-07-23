"""Unit tests for the email-extraction module.

Covers the editable constants catalog, the prompt builder, the LLM-response
parser, and the :class:`EmailExtractorAgent` end-to-end against a real in-memory
SQLite database with a fake LLM client (Testing rule: never call a real LLM in a
unit test). The agent's own failure handling — a failed call still stores a
``failed`` record and never raises — is asserted directly.
"""

from __future__ import annotations

import uuid

import pytest
from src.config.settings import Settings
from src.integrations.database import Database
from src.integrations.llm import LLMGenerationError
from src.modules.auth.repository import UserRepository
from src.modules.email_delivery.enums import EmailDirection
from src.modules.email_delivery.models import Email
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.email_extraction.agent import EmailExtractorAgent, _parse_result
from src.modules.email_extraction.constants import EMAIL_TYPE_STRUCTURES, label_for
from src.modules.email_extraction.enums import ExtractedEmailType, ExtractionStatus
from src.modules.email_extraction.exceptions import EmailExtractionError
from src.modules.email_extraction.prompts import build_prompts
from src.modules.email_extraction.repository import ExtractionRepository

_DOMAIN = "mail.example.com"


class _FakeLLM:
    """Fake LLM client returning a canned response or raising, and counting calls."""

    def __init__(self, *, response: str | None = None, raises: bool = False) -> None:
        self._response = response or ""
        self._raises = raises
        self.calls = 0

    def generate(self, *, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        self.calls += 1
        if self._raises:
            raise LLMGenerationError("boom")
        return self._response


@pytest.fixture
def settings() -> Settings:
    """Testing settings backed by in-memory SQLite."""
    return Settings(database_url="sqlite:///:memory:", environment="testing", debug=False)


@pytest.fixture
def database(settings: Settings) -> Database:
    """A Database facade backed by a fresh in-memory SQLite schema."""
    db = Database(settings)
    db.create_all()
    return db


def _seed_received_email(database: Database) -> dict[str, uuid.UUID]:
    """Create a user + conversation + one received supplier reply.

    Returns:
        Mapping with ``user``, ``conversation`` and ``email`` ids.
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
        email = repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.RECEIVED,
            from_email="supplier@acme.com",
            to_email=f"jane@{_DOMAIN}",
            subject="Re: RFQ — Bluetooth Speaker",
            body_text="We can offer USD 12 per unit, MOQ 500, lead time 3 weeks.",
        )
        return {"user": user.id, "conversation": conversation.id, "email": email.id}


# ── Constants catalog ────────────────────────────────────────────────────────


def test_every_email_type_has_a_structure() -> None:
    for member in ExtractedEmailType:
        assert member in EMAIL_TYPE_STRUCTURES
        assert EMAIL_TYPE_STRUCTURES[member].label


def test_label_for_returns_configured_label() -> None:
    assert label_for(ExtractedEmailType.QUOTE) == "Quote / Pricing"


# ── Prompt builder ───────────────────────────────────────────────────────────


def test_build_prompts_includes_types_fields_and_fences_content() -> None:
    system_prompt, user_prompt = build_prompts(
        subject="Re: RFQ", body="price 12 usd", attachments_text=""
    )
    # The classification vocabulary and at least one type-specific field render
    # into the system prompt straight from the constants file.
    assert "quote" in system_prompt
    assert "unit_price" in system_prompt
    # Untrusted content is fenced with explicit data markers.
    assert "BEGIN EMAIL DATA" in user_prompt
    assert "END EMAIL DATA" in user_prompt
    assert "price 12 usd" in user_prompt


# ── Response parsing ─────────────────────────────────────────────────────────


def test_parse_result_accepts_plain_json() -> None:
    result = _parse_result('{"email_type": "quote", "summary": "hi", "details": {"a": "b"}}')
    assert result.email_type is ExtractedEmailType.QUOTE
    assert result.details == {"a": "b"}


def test_parse_result_tolerates_code_fences() -> None:
    result = _parse_result('```json\n{"email_type": "follow_up", "summary": "x"}\n```')
    assert result.email_type is ExtractedEmailType.FOLLOW_UP


def test_parse_result_coerces_unknown_type_to_general() -> None:
    result = _parse_result('{"email_type": "nonsense", "summary": "x"}')
    assert result.email_type is ExtractedEmailType.GENERAL


def test_parse_result_rejects_non_json() -> None:
    with pytest.raises(EmailExtractionError):
        _parse_result("not json at all")


def test_parse_result_rejects_non_object() -> None:
    with pytest.raises(EmailExtractionError):
        _parse_result("[1, 2, 3]")


# ── Agent end-to-end ─────────────────────────────────────────────────────────


def test_extract_and_store_persists_completed_record(
    database: Database, settings: Settings
) -> None:
    ids = _seed_received_email(database)
    llm = _FakeLLM(
        response=(
            '{"email_type": "quote", "summary": "Supplier quoted USD 12/unit.", '
            '"details": {"unit_price": "USD 12", "minimum_order_quantity": "500"}, '
            '"confidence": 0.9}'
        )
    )
    agent = EmailExtractorAgent(llm, settings)  # type: ignore[arg-type]

    with database.session() as session:
        email = session.get(Email, ids["email"])
        assert email is not None
        assert agent.extract_and_store(session=session, email=email) is True

    with database.session() as session:
        rows = ExtractionRepository(session).list_for_user(user_id=ids["user"])
    assert len(rows) == 1
    row = rows[0]
    assert row.status == ExtractionStatus.COMPLETED.value
    assert row.email_type == ExtractedEmailType.QUOTE.value
    assert row.details["unit_price"] == "USD 12"
    assert row.supplier_email == "supplier@acme.com"
    assert row.original_subject == "Re: RFQ — Bluetooth Speaker"
    assert "USD 12" in row.original_body
    assert row.email_id == ids["email"]
    assert row.conversation_id == ids["conversation"]
    assert row.model == settings.llm_model


def test_extract_and_store_records_failure_without_raising(
    database: Database, settings: Settings
) -> None:
    ids = _seed_received_email(database)
    agent = EmailExtractorAgent(_FakeLLM(raises=True), settings)  # type: ignore[arg-type]

    with database.session() as session:
        email = session.get(Email, ids["email"])
        assert email is not None
        # A failed LLM call is caught, not propagated.
        assert agent.extract_and_store(session=session, email=email) is False

    with database.session() as session:
        rows = ExtractionRepository(session).list_for_user(user_id=ids["user"])
    assert len(rows) == 1
    assert rows[0].status == ExtractionStatus.FAILED.value
    assert rows[0].error


def test_extract_and_store_is_idempotent(database: Database, settings: Settings) -> None:
    ids = _seed_received_email(database)
    llm = _FakeLLM(response='{"email_type": "general", "summary": "x", "details": {}}')
    agent = EmailExtractorAgent(llm, settings)  # type: ignore[arg-type]

    with database.session() as session:
        email = session.get(Email, ids["email"])
        assert email is not None
        assert agent.extract_and_store(session=session, email=email) is True
        # Second run short-circuits before any LLM call.
        assert agent.extract_and_store(session=session, email=email) is True

    assert llm.calls == 1
    with database.session() as session:
        rows = ExtractionRepository(session).list_for_user(user_id=ids["user"])
    assert len(rows) == 1


def test_list_for_conversation_scopes_to_owner(database: Database, settings: Settings) -> None:
    ids = _seed_received_email(database)
    llm = _FakeLLM(response='{"email_type": "general", "summary": "x", "details": {}}')
    agent = EmailExtractorAgent(llm, settings)  # type: ignore[arg-type]
    with database.session() as session:
        email = session.get(Email, ids["email"])
        assert email is not None
        agent.extract_and_store(session=session, email=email)

    other_user = uuid.uuid4()
    with database.session() as session:
        repository = ExtractionRepository(session)
        owner_rows = repository.list_for_conversation(
            user_id=ids["user"], conversation_id=ids["conversation"]
        )
        stranger_rows = repository.list_for_conversation(
            user_id=other_user, conversation_id=ids["conversation"]
        )
    assert len(owner_rows) == 1
    assert stranger_rows == []
