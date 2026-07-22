"""Sample email-drafting query generation.

:class:`SampleQueryService` orchestrates prompt-building and the LLM client to
invent a fictional, schema-valid sample scenario for one of the
``skills/emails-patterns`` email types — used to populate the dashboard's
"generate a random sample query" button.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from src.domain.enums import EmailType
from src.domain.schemas.sample_query_schema import SampleQueryResponse
from src.integrations.llm_client import LLMClient, LLMGenerationError
from src.observability import get_logger
from src.services.exceptions import SampleQueryGenerationError
from src.services.sample_query_prompts import build_prompts

logger = get_logger(__name__)


def _parse_json_object(raw: str) -> dict[str, object]:
    """Parse the model's response into a JSON object, tolerating code fences.

    Args:
        raw: The raw text returned by the LLM.

    Returns:
        The decoded JSON object.

    Raises:
        SampleQueryGenerationError: If the text is not a valid JSON object.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SampleQueryGenerationError("The model did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise SampleQueryGenerationError("The model's JSON response was not an object.")
    return parsed


class SampleQueryService:
    """Generates fictional sample queries for the email-drafting skills.

    Args:
        llm_client: Client used to call the underlying language model.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Store the injected LLM client."""
        self._llm_client = llm_client

    def generate(self, email_type: EmailType) -> SampleQueryResponse:
        """Generate one sample query for the given email type.

        Args:
            email_type: Which email pattern to generate a sample for.

        Returns:
            The validated :class:`SampleQueryResponse`.

        Raises:
            SampleQueryGenerationError: If the LLM call fails or its response
                does not match the expected shape.
        """
        system_prompt, user_prompt = build_prompts(email_type)
        try:
            raw = self._llm_client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        except LLMGenerationError as exc:
            logger.warning("Sample query generation failed for %s: %s", email_type, exc)
            raise SampleQueryGenerationError("Could not generate a sample query.") from exc

        payload = _parse_json_object(raw)
        try:
            return SampleQueryResponse.model_validate({"email_type": email_type, **payload})
        except ValidationError as exc:
            raise SampleQueryGenerationError(
                "The model's response did not match the expected schema."
            ) from exc
