"""Unit tests for email drafting, review, and verification.

Per the coding standards (file ``04``, §5.1), the LLM is never called for
real in a unit test — a fake client returns canned responses instead.
Persistence is exercised against the real repository/in-memory database, the
same pattern used by the sample-data module's tests.

A dedicated set of tests enforces the module's hard rule (Rule 6 in
``AgenticAI_Rules_Diagram.md``): generation and modification can never mark a
draft "verified" — only :meth:`EmailDraftService.verify` can.
"""

import json
import uuid

import pytest
from src.modules.email_draft.enums import DraftStatus
from src.modules.email_draft.exceptions import EmailDraftGenerationError, EmailDraftNotFoundError
from src.modules.email_draft.repository import EmailDraftRepository
from src.modules.email_draft.service import EmailDraftService
from src.modules.email_patterns import EmailType

_VALID_PAYLOAD = {
    "subject": "Request for Quotation — Steel Bolts",
    "body": "Dear Acme Supplies,\n\nPlease provide a quote for steel bolts.",
}


class _FakeLLMClient:
    """Stand-in for :class:`~src.integrations.llm.LLMClient` returning a canned response."""

    def __init__(self, response: str = "", *, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self._raises is not None:
            raise self._raises
        return self._response


def _service(
    repository: EmailDraftRepository,
    response: str = "",
    *,
    raises: Exception | None = None,
) -> EmailDraftService:
    return EmailDraftService(_FakeLLMClient(response, raises=raises), repository)  # type: ignore[arg-type]


def test_generate_and_save_persists_valid_response(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()

    saved = service.generate_and_save(
        user_id=user_id, email_type=EmailType.RFQ, query_text="Please draft an RFQ for steel bolts."
    )

    assert saved.id is not None
    assert saved.user_id == user_id
    assert saved.email_type == EmailType.RFQ.value
    assert saved.subject == _VALID_PAYLOAD["subject"]
    assert saved.body == _VALID_PAYLOAD["body"]
    assert saved.query_text == "Please draft an RFQ for steel bolts."
    assert saved.recipient is None


def test_generate_and_save_passes_query_text_as_user_prompt(
    email_draft_repository: EmailDraftRepository,
) -> None:
    fake_client = _FakeLLMClient(json.dumps(_VALID_PAYLOAD))
    service = EmailDraftService(fake_client, email_draft_repository)  # type: ignore[arg-type]

    service.generate_and_save(
        user_id=uuid.uuid4(), email_type=EmailType.APOLOGY, query_text="Apologize for the delay."
    )

    assert fake_client.calls[0][1] == "Apologize for the delay."


def test_generate_and_save_strips_markdown_code_fences(
    email_draft_repository: EmailDraftRepository,
) -> None:
    fenced = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
    service = _service(email_draft_repository, fenced)

    saved = service.generate_and_save(
        user_id=uuid.uuid4(), email_type=EmailType.FOLLOW_UP, query_text="Follow up on the invoice."
    )

    assert saved.subject == _VALID_PAYLOAD["subject"]


def test_generate_and_save_raises_on_invalid_json(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, "not json at all")

    with pytest.raises(EmailDraftGenerationError):
        service.generate_and_save(user_id=uuid.uuid4(), email_type=EmailType.RFQ, query_text="q")


def test_generate_and_save_raises_on_schema_mismatch(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps({"subject": "", "body": ""}))

    with pytest.raises(EmailDraftGenerationError):
        service.generate_and_save(
            user_id=uuid.uuid4(), email_type=EmailType.NEGOTIATION, query_text="q"
        )


def test_generate_and_save_raises_when_llm_call_fails(
    email_draft_repository: EmailDraftRepository,
) -> None:
    from src.integrations.llm import LLMGenerationError

    service = _service(email_draft_repository, raises=LLMGenerationError("boom"))

    with pytest.raises(EmailDraftGenerationError):
        service.generate_and_save(
            user_id=uuid.uuid4(), email_type=EmailType.SAMPLE_REQUEST, query_text="q"
        )


def test_generate_and_save_always_creates_draft_status(
    email_draft_repository: EmailDraftRepository,
) -> None:
    """Hard rule: generation can never produce anything but 'draft'."""
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))

    saved = service.generate_and_save(
        user_id=uuid.uuid4(), email_type=EmailType.RFQ, query_text="q"
    )

    assert saved.status == DraftStatus.DRAFT.value


def test_list_saved_returns_only_matching_user_and_type(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q1")
    service.generate_and_save(user_id=user_id, email_type=EmailType.APOLOGY, query_text="q2")
    service.generate_and_save(user_id=other_user_id, email_type=EmailType.RFQ, query_text="q3")

    saved = service.list_saved(user_id=user_id, email_type=EmailType.RFQ)

    assert len(saved) == 1
    assert saved[0].user_id == user_id
    assert saved[0].email_type == EmailType.RFQ.value


def test_list_saved_without_email_type_returns_complete_history(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q1")
    service.generate_and_save(user_id=user_id, email_type=EmailType.APOLOGY, query_text="q2")
    service.generate_and_save(user_id=user_id, email_type=EmailType.FOLLOW_UP, query_text="q3")
    service.generate_and_save(user_id=other_user_id, email_type=EmailType.RFQ, query_text="q4")

    saved = service.list_saved(user_id=user_id)

    assert len(saved) == 3
    assert {row.email_type for row in saved} == {
        EmailType.RFQ.value,
        EmailType.APOLOGY.value,
        EmailType.FOLLOW_UP.value,
    }
    assert all(row.user_id == user_id for row in saved)


def test_list_saved_orders_most_recent_first(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()

    first = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q1")
    second = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q2")

    saved = service.list_saved(user_id=user_id, email_type=EmailType.RFQ)

    assert [row.id for row in saved] == [second.id, first.id]


def test_get_saved_returns_owned_draft(email_draft_repository: EmailDraftRepository) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    saved = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q")

    fetched = service.get_saved(user_id=user_id, draft_id=saved.id)

    assert fetched.id == saved.id


def test_get_saved_raises_for_other_users_draft(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    saved = service.generate_and_save(
        user_id=uuid.uuid4(), email_type=EmailType.RFQ, query_text="q"
    )

    with pytest.raises(EmailDraftNotFoundError):
        service.get_saved(user_id=uuid.uuid4(), draft_id=saved.id)


def test_get_saved_raises_for_unknown_id(email_draft_repository: EmailDraftRepository) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))

    with pytest.raises(EmailDraftNotFoundError):
        service.get_saved(user_id=uuid.uuid4(), draft_id=uuid.uuid4())


def test_modify_updates_only_supplied_fields(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    saved = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q")

    updated = service.modify(
        user_id=user_id, draft_id=saved.id, subject="A new subject", recipient="buyer@example.com"
    )

    assert updated.subject == "A new subject"
    assert updated.recipient == "buyer@example.com"
    assert updated.body == _VALID_PAYLOAD["body"]  # unchanged — not supplied


def test_modify_never_changes_status(email_draft_repository: EmailDraftRepository) -> None:
    """Hard rule: editing a draft can never verify it."""
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    saved = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q")

    updated = service.modify(user_id=user_id, draft_id=saved.id, subject="Edited subject")

    assert updated.status == DraftStatus.DRAFT.value


def test_modify_raises_for_other_users_draft(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    saved = service.generate_and_save(
        user_id=uuid.uuid4(), email_type=EmailType.RFQ, query_text="q"
    )

    with pytest.raises(EmailDraftNotFoundError):
        service.modify(user_id=uuid.uuid4(), draft_id=saved.id, subject="hijacked")


def test_verify_marks_draft_verified(email_draft_repository: EmailDraftRepository) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    saved = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ, query_text="q")
    assert saved.status == DraftStatus.DRAFT.value

    verified = service.verify(user_id=user_id, draft_id=saved.id)

    assert verified.status == DraftStatus.VERIFIED.value


def test_verify_raises_for_other_users_draft(
    email_draft_repository: EmailDraftRepository,
) -> None:
    service = _service(email_draft_repository, json.dumps(_VALID_PAYLOAD))
    saved = service.generate_and_save(
        user_id=uuid.uuid4(), email_type=EmailType.RFQ, query_text="q"
    )

    with pytest.raises(EmailDraftNotFoundError):
        service.verify(user_id=uuid.uuid4(), draft_id=saved.id)


@pytest.mark.parametrize("email_type", list(EmailType))
def test_build_prompts_includes_skill_spec_and_query(email_type: EmailType) -> None:
    from src.modules.email_draft.prompts import build_prompts
    from src.modules.email_patterns import EMAIL_TYPE_LABELS

    system_prompt, user_prompt = build_prompts(email_type, "Draft this for me please.")

    assert EMAIL_TYPE_LABELS[email_type] in system_prompt
    assert user_prompt == "Draft this for me please."


def test_build_prompts_includes_rfq_field_checklist_only_for_rfq() -> None:
    from src.modules.email_draft.prompts import build_prompts

    rfq_system_prompt, _ = build_prompts(EmailType.RFQ, "q")
    other_system_prompt, _ = build_prompts(EmailType.APOLOGY, "q")

    assert "RFQ field checklist" in rfq_system_prompt
    assert "Cover Letter / Invitation" in rfq_system_prompt
    assert "RFQ field checklist" not in other_system_prompt
