"""JSON API routes for sample email-drafting query generation.

Backs the dashboard's "Generate Email" panel: list the available email
patterns, generate (and persist) a fictional sample scenario, and list a
user's previously saved samples for reuse.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.modules.auth.deps import RequiredCookieUserDep
from src.modules.email_patterns import EMAIL_TYPE_LABELS, EmailType, EmailTypeOption
from src.modules.sample_data.deps import SampleQueryServiceDep
from src.modules.sample_data.exceptions import SampleQueryGenerationError
from src.modules.sample_data.schemas import SavedSampleQueryRead

router = APIRouter(prefix="/api/v1", tags=["sample-data"])


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
    response_model=SavedSampleQueryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and save a fictional sample query for the given email type",
)
def generate_sample_query(
    email_type: EmailType,
    current_user: RequiredCookieUserDep,
    sample_query_service: SampleQueryServiceDep,
) -> SavedSampleQueryRead:
    """Generate one random, schema-valid sample query and save it.

    Args:
        email_type: Which email pattern to generate a sample for.
        current_user: The authenticated user — the saved record's owner.
        sample_query_service: Injected sample-query service.

    Returns:
        The saved :class:`SavedSampleQueryRead`.

    Raises:
        HTTPException: ``502`` if the LLM call fails or returns an
            unparsable/invalid response.
    """
    try:
        saved = sample_query_service.generate_and_save(
            user_id=current_user.id, email_type=email_type
        )
    except SampleQueryGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return SavedSampleQueryRead.model_validate(saved)


@router.get(
    "/sample-queries",
    response_model=list[SavedSampleQueryRead],
    summary="List the current user's saved sample queries (optionally by email type)",
)
def list_saved_sample_queries(
    current_user: RequiredCookieUserDep,
    sample_query_service: SampleQueryServiceDep,
    email_type: EmailType | None = None,
) -> list[SavedSampleQueryRead]:
    """Return the current user's saved samples, newest first.

    Args:
        current_user: The authenticated user.
        sample_query_service: Injected sample-query service.
        email_type: Optional email pattern to filter by (query parameter).
            Omit it to get the user's complete saved history across every type.

    Returns:
        Matching saved samples, most recent first.
    """
    saved = sample_query_service.list_saved(user_id=current_user.id, email_type=email_type)
    return [SavedSampleQueryRead.model_validate(row) for row in saved]
