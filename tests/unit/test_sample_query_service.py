"""Unit tests for sample email-drafting query generation and persistence.

Per the coding standards (file ``04``, §5.1), the LLM is never called for
real in a unit test — a fake client returns canned responses instead.
Persistence is exercised against the real repository/in-memory database, the
same pattern used by the auth service's tests.
"""

import json
import uuid

import pytest
from src.modules.sample_data.enums import EmailType
from src.modules.sample_data.exceptions import SampleQueryGenerationError
from src.modules.sample_data.llm_client import LLMGenerationError
from src.modules.sample_data.prompts import EMAIL_TYPE_LABELS, build_prompts
from src.modules.sample_data.repository import SampleQueryRepository
from src.modules.sample_data.service import SampleQueryService

_VALID_PAYLOAD = {
    "fields": {"supplier_name": "Acme Supplies", "product": "Steel Bolts"},
    "query_text": "Please draft an email to Acme Supplies about steel bolts.",
}


class _FakeLLMClient:
    """Stand-in for :class:`LLMClient` returning a canned response."""

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
    repository: SampleQueryRepository,
    response: str = "",
    *,
    raises: Exception | None = None,
) -> SampleQueryService:
    return SampleQueryService(_FakeLLMClient(response, raises=raises), repository)  # type: ignore[arg-type]


def test_generate_and_save_persists_valid_response(
    sample_query_repository: SampleQueryRepository,
) -> None:
    service = _service(sample_query_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()

    saved = service.generate_and_save(user_id=user_id, email_type=EmailType.NEGOTIATION)

    assert saved.id is not None
    assert saved.user_id == user_id
    assert saved.email_type == EmailType.NEGOTIATION.value
    assert saved.fields == _VALID_PAYLOAD["fields"]
    assert saved.query_text == _VALID_PAYLOAD["query_text"]


def test_generate_and_save_strips_markdown_code_fences(
    sample_query_repository: SampleQueryRepository,
) -> None:
    fenced = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
    service = _service(sample_query_repository, fenced)

    saved = service.generate_and_save(user_id=uuid.uuid4(), email_type=EmailType.APOLOGY)

    assert saved.fields == _VALID_PAYLOAD["fields"]


def test_generate_and_save_raises_on_invalid_json(
    sample_query_repository: SampleQueryRepository,
) -> None:
    service = _service(sample_query_repository, "not json at all")

    with pytest.raises(SampleQueryGenerationError):
        service.generate_and_save(user_id=uuid.uuid4(), email_type=EmailType.RFQ)


def test_generate_and_save_raises_on_schema_mismatch(
    sample_query_repository: SampleQueryRepository,
) -> None:
    service = _service(sample_query_repository, json.dumps({"fields": {}, "query_text": ""}))

    with pytest.raises(SampleQueryGenerationError):
        service.generate_and_save(user_id=uuid.uuid4(), email_type=EmailType.FOLLOW_UP)


def test_generate_and_save_raises_when_llm_call_fails(
    sample_query_repository: SampleQueryRepository,
) -> None:
    service = _service(sample_query_repository, raises=LLMGenerationError("boom"))

    with pytest.raises(SampleQueryGenerationError):
        service.generate_and_save(user_id=uuid.uuid4(), email_type=EmailType.SAMPLE_REQUEST)


def test_list_saved_returns_only_matching_user_and_type(
    sample_query_repository: SampleQueryRepository,
) -> None:
    service = _service(sample_query_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ)
    service.generate_and_save(user_id=user_id, email_type=EmailType.APOLOGY)
    service.generate_and_save(user_id=other_user_id, email_type=EmailType.RFQ)

    saved = service.list_saved(user_id=user_id, email_type=EmailType.RFQ)

    assert len(saved) == 1
    assert saved[0].user_id == user_id
    assert saved[0].email_type == EmailType.RFQ.value


def test_list_saved_orders_most_recent_first(
    sample_query_repository: SampleQueryRepository,
) -> None:
    service = _service(sample_query_repository, json.dumps(_VALID_PAYLOAD))
    user_id = uuid.uuid4()

    first = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ)
    second = service.generate_and_save(user_id=user_id, email_type=EmailType.RFQ)

    saved = service.list_saved(user_id=user_id, email_type=EmailType.RFQ)

    assert [row.id for row in saved] == [second.id, first.id]


def test_email_type_labels_cover_every_email_type() -> None:
    assert set(EMAIL_TYPE_LABELS) == set(EmailType)


@pytest.mark.parametrize("email_type", list(EmailType))
def test_build_prompts_includes_skill_spec(email_type: EmailType) -> None:
    system_prompt, user_prompt = build_prompts(email_type)

    assert EMAIL_TYPE_LABELS[email_type] in system_prompt
    assert user_prompt


def test_build_prompts_includes_rfq_field_checklist_only_for_rfq() -> None:
    rfq_system_prompt, _ = build_prompts(EmailType.RFQ)
    other_system_prompt, _ = build_prompts(EmailType.APOLOGY)

    assert "RFQ field checklist" in rfq_system_prompt
    assert "Cover Letter / Invitation" in rfq_system_prompt
    assert "RFQ field checklist" not in other_system_prompt
