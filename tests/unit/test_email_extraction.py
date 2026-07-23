"""Unit tests for the email-extraction module.

Covers the editable constants catalog, the prompt builder, the LLM-response
parser, and the :class:`EmailExtractorAgent` end-to-end against a real in-memory
SQLite database with a fake LLM client (Testing rule: never call a real LLM in a
unit test). The agent's own failure handling — a failed call still stores a
``failed`` record and never raises — is asserted directly.
"""

from __future__ import annotations

import base64
import io
import uuid
import zipfile
from typing import Any

import pytest
from src.config.settings import Settings
from src.integrations.database import Database
from src.integrations.llm import LLMGenerationError
from src.modules.auth.repository import UserRepository
from src.modules.email_delivery.enums import EmailDirection
from src.modules.email_delivery.models import Email
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.email_extraction.agent import EmailExtractorAgent, _parse_result
from src.modules.email_extraction.attachments_reader import AttachmentRef, read_attachments
from src.modules.email_extraction.constants import EMAIL_TYPE_STRUCTURES, label_for
from src.modules.email_extraction.enums import ExtractedEmailType, ExtractionStatus
from src.modules.email_extraction.exceptions import EmailExtractionError
from src.modules.email_extraction.prompts import build_prompts
from src.modules.email_extraction.repository import ExtractionRepository

_DOMAIN = "mail.example.com"


class _FakeLLM:
    """Fake LLM client returning a canned response or raising, and counting calls.

    Records the content blocks it was last asked to send so tests can assert that
    native media (PDF/image) blocks reached the model.
    """

    def __init__(self, *, response: str | None = None, raises: bool = False) -> None:
        self._response = response or ""
        self._raises = raises
        self.calls = 0
        self.last_content: list[dict[str, Any]] | None = None

    def generate(self, *, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        return self.generate_multimodal(
            system_prompt=system_prompt,
            content=[{"type": "text", "text": user_prompt}],
            max_tokens=max_tokens,
        )

    def generate_multimodal(
        self, *, system_prompt: str, content: list[dict[str, Any]], max_tokens: int = 4096
    ) -> str:
        self.calls += 1
        self.last_content = content
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


# ── Attachment reader (all file types) ───────────────────────────────────────


class _ReaderSettings:
    """Minimal settings stand-in exposing only what the reader reads."""

    def __init__(self, attachments_dir: Any) -> None:
        self.attachments_dir = attachments_dir


def _write_attachment(directory: Any, name: str, data: bytes) -> AttachmentRef:
    """Write ``data`` to ``directory/name`` and return a matching ref."""
    (directory / name).write_bytes(data)
    return AttachmentRef(filename=name, url=f"/attachments/{name}")


def _xlsx_bytes() -> bytes:
    """Build a tiny two-row spreadsheet in memory."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Product", "Unit Price"])
    sheet.append(["Bluetooth Speaker", 12])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_read_attachments_returns_empty_when_none(tmp_path: Any) -> None:
    result = read_attachments(_ReaderSettings(tmp_path), [])  # type: ignore[arg-type]
    assert result.text == ""
    assert result.media_blocks == []


def test_read_attachments_reads_text_inline(tmp_path: Any) -> None:
    ref = _write_attachment(tmp_path, "quote.txt", b"USD 12 per unit, MOQ 500")
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    assert "USD 12 per unit, MOQ 500" in result.text
    assert result.media_blocks == []


def test_read_attachments_renders_spreadsheet(tmp_path: Any) -> None:
    ref = _write_attachment(tmp_path, "prices.xlsx", _xlsx_bytes())
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    assert "Bluetooth Speaker" in result.text
    assert "Unit Price" in result.text
    assert result.media_blocks == []


def test_read_attachments_emits_pdf_document_block(tmp_path: Any) -> None:
    ref = _write_attachment(tmp_path, "quote.pdf", b"%PDF-1.4 pretend pdf bytes")
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    assert len(result.media_blocks) == 1
    block = result.media_blocks[0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(block["source"]["data"]) == b"%PDF-1.4 pretend pdf bytes"
    assert "separate content block" in result.text


def test_read_attachments_emits_image_block(tmp_path: Any) -> None:
    ref = _write_attachment(tmp_path, "scan.png", b"\x89PNG pretend image bytes")
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    assert len(result.media_blocks) == 1
    block = result.media_blocks[0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"


def test_read_attachments_expands_zip(tmp_path: Any) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("terms.txt", "Net 30 payment terms")
        archive.writestr("quote.pdf", b"%PDF-1.4 inner pdf")
    ref = _write_attachment(tmp_path, "pack.zip", buffer.getvalue())
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    # Text member is read inline; PDF member becomes a native document block.
    assert "Net 30 payment terms" in result.text
    assert len(result.media_blocks) == 1
    assert result.media_blocks[0]["type"] == "document"


def test_read_attachments_notes_missing_file(tmp_path: Any) -> None:
    ref = AttachmentRef(filename="gone.txt", url="/attachments/gone.txt")
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    assert "not found on disk" in result.text
    assert result.media_blocks == []


def test_read_attachments_notes_unknown_binary(tmp_path: Any) -> None:
    ref = _write_attachment(tmp_path, "mystery.bin", b"\x00\x01\x02\x03")
    result = read_attachments(_ReaderSettings(tmp_path), [ref])  # type: ignore[arg-type]
    assert "not a readable type" in result.text
    assert result.media_blocks == []


def test_extract_and_store_forwards_media_blocks_to_llm(
    database: Database, settings: Settings, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF attachment reaches the model as a native document block."""
    # Point the attachments dir at a throwaway tmp dir (never the repo's data/).
    monkeypatch.setattr(Settings, "attachments_dir", property(lambda self: tmp_path))
    ids = _seed_received_email(database)
    pdf_name = "supplier-quote.pdf"
    (tmp_path / pdf_name).write_bytes(b"%PDF-1.4 quote")

    llm = _FakeLLM(response='{"email_type": "quote", "summary": "x", "details": {}}')
    agent = EmailExtractorAgent(llm, settings)  # type: ignore[arg-type]

    with database.session() as session:
        repository = EmailDeliveryRepository(session)
        email = session.get(Email, ids["email"])
        assert email is not None
        repository.add_attachments(
            email_id=email.id,
            metas=[
                {
                    "filename": pdf_name,
                    "url": f"/attachments/{pdf_name}",
                    "content_type": "application/pdf",
                    "size": 14,
                }
            ],
        )
        session.refresh(email, attribute_names=["attachments"])
        assert agent.extract_and_store(session=session, email=email) is True

    assert llm.last_content is not None
    block_types = [block["type"] for block in llm.last_content]
    assert "text" in block_types
    assert "document" in block_types
