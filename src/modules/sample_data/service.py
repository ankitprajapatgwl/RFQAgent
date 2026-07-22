"""Sample email-drafting query generation.

:class:`SampleQueryService` orchestrates prompt-building, the LLM client, and
persistence to invent a fictional, schema-valid sample scenario for one of
the ``skills/emails-patterns`` email types, and save it so it can be reused
later from the dashboard's "saved sample data" dropdown.
"""

from __future__ import annotations

import json
import uuid

from pydantic import ValidationError

from src.modules.sample_data.enums import EmailType
from src.modules.sample_data.exceptions import SampleQueryGenerationError
from src.modules.sample_data.llm_client import LLMClient, LLMGenerationError
from src.modules.sample_data.models import SavedSampleQuery
from src.modules.sample_data.prompts import build_prompts
from src.modules.sample_data.repository import SampleQueryRepository
from src.modules.sample_data.schemas import GeneratedSample
from src.observability import get_logger

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
    """Generates and persists fictional sample queries for the email-drafting skills.

    Args:
        llm_client: Client used to call the underlying language model.
        repository: Data access for saved sample queries.
    """

    def __init__(self, llm_client: LLMClient, repository: SampleQueryRepository) -> None:
        """Store the injected collaborators."""
        self._llm_client = llm_client
        self._repository = repository

    def generate_and_save(self, *, user_id: uuid.UUID, email_type: EmailType) -> SavedSampleQuery:
        """Generate one sample query and persist it for the given user.

        Args:
            user_id: The requesting user's id — the saved record's owner.
            email_type: Which email pattern to generate a sample for.

        Returns:
            The saved :class:`SavedSampleQuery`.

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
            generated = GeneratedSample.model_validate(payload)
        except ValidationError as exc:
            raise SampleQueryGenerationError(
                "The model's response did not match the expected schema."
            ) from exc

        return self._repository.save(
            user_id=user_id,
            email_type=email_type,
            fields=generated.fields,
            query_text=generated.query_text,
        )

    def list_saved(
        self, *, user_id: uuid.UUID, email_type: EmailType | None = None
    ) -> list[SavedSampleQuery]:
        """Return a user's previously saved samples, newest first.

        Args:
            user_id: The requesting user's id.
            email_type: Optional email pattern to filter by. When ``None``
                (the default), the user's complete saved history is returned.

        Returns:
            Matching :class:`SavedSampleQuery` rows, most recent first.
        """
        return self._repository.list_for_user(user_id=user_id, email_type=email_type)
