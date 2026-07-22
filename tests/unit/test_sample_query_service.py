"""Unit tests for sample email-drafting query generation.

Per the coding standards (file ``04``, §5.1), the LLM is never called for
real in a unit test — a fake client returns canned responses instead.
"""

import json

import pytest
from src.domain.enums import EmailType
from src.integrations.llm_client import LLMGenerationError
from src.services.exceptions import SampleQueryGenerationError
from src.services.sample_query_prompts import EMAIL_TYPE_LABELS, build_prompts
from src.services.sample_query_service import SampleQueryService

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

    def generate(self, *, system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self._raises is not None:
            raise self._raises
        return self._response


def test_generate_returns_valid_response() -> None:
    client = _FakeLLMClient(json.dumps(_VALID_PAYLOAD))
    service = SampleQueryService(client)  # type: ignore[arg-type]

    result = service.generate(EmailType.NEGOTIATION)

    assert result.email_type is EmailType.NEGOTIATION
    assert result.fields == _VALID_PAYLOAD["fields"]
    assert result.query_text == _VALID_PAYLOAD["query_text"]
    assert len(client.calls) == 1


def test_generate_strips_markdown_code_fences() -> None:
    fenced = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
    client = _FakeLLMClient(fenced)
    service = SampleQueryService(client)  # type: ignore[arg-type]

    result = service.generate(EmailType.APOLOGY)

    assert result.fields == _VALID_PAYLOAD["fields"]


def test_generate_raises_on_invalid_json() -> None:
    client = _FakeLLMClient("not json at all")
    service = SampleQueryService(client)  # type: ignore[arg-type]

    with pytest.raises(SampleQueryGenerationError):
        service.generate(EmailType.RFQ)


def test_generate_raises_on_schema_mismatch() -> None:
    client = _FakeLLMClient(json.dumps({"fields": {}, "query_text": ""}))
    service = SampleQueryService(client)  # type: ignore[arg-type]

    with pytest.raises(SampleQueryGenerationError):
        service.generate(EmailType.FOLLOW_UP)


def test_generate_raises_when_llm_call_fails() -> None:
    client = _FakeLLMClient(raises=LLMGenerationError("boom"))
    service = SampleQueryService(client)  # type: ignore[arg-type]

    with pytest.raises(SampleQueryGenerationError):
        service.generate(EmailType.SAMPLE_REQUEST)


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
