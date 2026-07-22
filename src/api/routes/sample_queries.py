"""JSON API routes for sample email-drafting query generation.

Backs the dashboard's "generate a random sample query" button: list the
available email patterns, then generate a fictional, schema-valid sample
scenario for one of them via the LLM.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.api.deps import RequiredCookieUserDep, SampleQueryServiceDep
from src.domain.enums import EmailType
from src.domain.schemas.sample_query_schema import EmailTypeOption, SampleQueryResponse
from src.services.exceptions import SampleQueryGenerationError
from src.services.sample_query_prompts import EMAIL_TYPE_LABELS

router = APIRouter(prefix="/api/v1", tags=["sample-queries"])


@router.get(
    "/email-types",
    response_model=list[EmailTypeOption],
    summary="List the email patterns available for sample-query generation",
)
def list_email_types(_current_user: RequiredCookieUserDep) -> list[EmailTypeOption]:
    """Return every selectable email type with a display label."""
    return [EmailTypeOption(value=value, label=label) for value, label in EMAIL_TYPE_LABELS.items()]


@router.post(
    "/sample-queries/{email_type}",
    response_model=SampleQueryResponse,
    summary="Generate a fictional sample query for the given email type",
)
def generate_sample_query(
    email_type: EmailType,
    _current_user: RequiredCookieUserDep,
    sample_query_service: SampleQueryServiceDep,
) -> SampleQueryResponse:
    """Generate one random, schema-valid sample query.

    Args:
        email_type: Which email pattern to generate a sample for.
        _current_user: The authenticated user (authorization gate only).
        sample_query_service: Injected sample-query service.

    Returns:
        The generated :class:`SampleQueryResponse`.

    Raises:
        HTTPException: ``502`` if the LLM call fails or returns an
            unparsable/invalid response.
    """
    try:
        return sample_query_service.generate(email_type)
    except SampleQueryGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
