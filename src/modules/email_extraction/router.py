"""JSON API routes for reading stored email extractions.

Backs two dashboard features:

* ``GET /api/v1/email-extraction/extractions`` — every extraction for the
  signed-in user, newest first (the "RFQ Monitoring" list, Requirement 3).
* ``GET /api/v1/email-extraction/conversations/{conversation_id}/extractions`` —
  one conversation's extractions (the "view extracted JSON" popup on the Email
  Dispatch History page, Requirement 4).

Both endpoints are authenticated and scoped to the current user — an extraction
is only ever returned to the user who owns the underlying conversation.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from src.modules.auth.deps import RequiredCookieUserDep
from src.modules.email_extraction.deps import EmailExtractionServiceDep
from src.modules.email_extraction.schemas import ExtractedEmailRead

router = APIRouter(prefix="/api/v1/email-extraction", tags=["email-extraction"])


@router.get(
    "/extractions",
    response_model=list[ExtractedEmailRead],
    summary="List every extracted email for the current user (RFQ monitoring)",
)
def list_extractions(
    current_user: RequiredCookieUserDep,
    extraction_service: EmailExtractionServiceDep,
) -> list[ExtractedEmailRead]:
    """Return the current user's extractions, newest first.

    Args:
        current_user: The authenticated user.
        extraction_service: Injected read-side extraction service.

    Returns:
        Every stored extraction owned by the user, most recent first, each
        pairing the original email content with its extracted details.
    """
    rows = extraction_service.list_for_user(user_id=current_user.id)
    return [ExtractedEmailRead.model_validate(row) for row in rows]


@router.get(
    "/conversations/{conversation_id}/extractions",
    response_model=list[ExtractedEmailRead],
    summary="List the extractions recorded for one conversation",
)
def list_conversation_extractions(
    conversation_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    extraction_service: EmailExtractionServiceDep,
) -> list[ExtractedEmailRead]:
    """Return one conversation's extractions for the owning user, oldest first.

    Returns an empty list — never a 404 — when the conversation has no
    extractions yet or is not owned by the user, so the dispatch-history popup
    can uniformly show "nothing extracted yet".

    Args:
        conversation_id: The conversation whose extractions to return.
        current_user: The authenticated user (ownership guard).
        extraction_service: Injected read-side extraction service.

    Returns:
        The conversation's extractions, oldest first.
    """
    rows = extraction_service.list_for_conversation(
        user_id=current_user.id, conversation_id=conversation_id
    )
    return [ExtractedEmailRead.model_validate(row) for row in rows]
