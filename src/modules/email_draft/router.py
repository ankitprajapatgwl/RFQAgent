"""JSON API routes for email drafting.

Backs the dashboard's "Verify & Modify Email" panel: draft (and persist) an
email from a query, list a user's drafted-email history, fetch one, apply a
human edit, and mark one verified. Generation and edits never set a draft
"verified" — only ``POST /email-drafts/{id}/verify`` can, by design (see
:mod:`src.modules.email_draft.service`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from src.config import get_settings
from src.modules.auth.deps import RequiredCookieUserDep
from src.modules.email_draft.deps import EmailDraftServiceDep
from src.modules.email_draft.exceptions import EmailDraftGenerationError, EmailDraftNotFoundError
from src.modules.email_draft.schemas import (
    EmailDraftGenerateRequest,
    EmailDraftRead,
    EmailDraftUpdate,
    RfqGraftRequest,
    RfqPreviewResponse,
)
from src.modules.email_patterns import EmailType

router = APIRouter(prefix="/api/v1", tags=["email-draft"])


@router.post(
    "/email-drafts/{email_type}",
    response_model=EmailDraftRead,
    status_code=status.HTTP_201_CREATED,
    summary="Draft and save an email for the given email type from a query",
)
def generate_email_draft(
    email_type: EmailType,
    payload: EmailDraftGenerateRequest,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
) -> EmailDraftRead:
    """Draft one email from the given query and save it.

    Args:
        email_type: Which email pattern to draft (selects the skill).
        payload: The query to draft from.
        current_user: The authenticated user — the saved draft's owner.
        email_draft_service: Injected email-draft service.

    Returns:
        The saved :class:`EmailDraftRead`, with ``status = "draft"``.

    Raises:
        HTTPException: ``502`` if the LLM call fails or returns an
            unparsable/invalid response.
    """
    try:
        saved = email_draft_service.generate_and_save(
            user_id=current_user.id,
            email_type=email_type,
            query_text=payload.query_text,
            sender_name=current_user.full_name,
            sender_email=current_user.email,
            sender_phone=current_user.phone_number or "",
        )
    except EmailDraftGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return EmailDraftRead.model_validate(saved)


@router.post(
    "/email-drafts/rfq-email/graft",
    response_model=EmailDraftRead,
    status_code=status.HTTP_201_CREATED,
    summary="Fill the RFQ HTML template directly from generated fields (no drafting agent)",
)
def graft_rfq_email_draft(
    payload: RfqGraftRequest,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
) -> EmailDraftRead:
    """Graft an RFQ email straight from generated field data and save it.

    This is the RFQ-only counterpart to :func:`generate_email_draft`: instead
    of asking the drafting LLM to write a subject/body from a natural-
    language query, it fills ``payload.fields`` (picked from a hard-coded
    sample, or subsequently hand-edited) directly into the RFQ HTML
    template. No drafting agent call is made.

    Args:
        payload: The RFQ field values to graft into the template.
        current_user: The authenticated user — the saved draft's owner.
        email_draft_service: Injected email-draft service.

    Returns:
        The saved :class:`EmailDraftRead`, with ``status = "draft"`` and
        ``is_html = True``.
    """
    settings = get_settings()
    saved = email_draft_service.graft_rfq_and_save(
        user_id=current_user.id,
        fields=payload.fields,
        contact_name=current_user.full_name,
        contact_email=current_user.email,
        company_name=settings.provider_company_name(settings.email_provider),
    )
    return EmailDraftRead.model_validate(saved)


@router.post(
    "/email-drafts/rfq-email/preview",
    response_model=RfqPreviewResponse,
    summary="Render the RFQ email subject/body from fields, without saving",
)
def preview_rfq_email_draft(
    payload: RfqGraftRequest,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
) -> RfqPreviewResponse:
    """Render an RFQ subject/body straight from field data — no persistence.

    Backs the dashboard's live preview: called as the user edits the
    generated fields for an already-grafted draft, so the on-screen email
    updates immediately without creating a new draft record for every edit.

    Args:
        payload: The RFQ field values to render.
        current_user: The authenticated user — supplies the buyer contact details.
        email_draft_service: Injected email-draft service.

    Returns:
        The rendered :class:`RfqPreviewResponse`.
    """
    settings = get_settings()
    subject, body = email_draft_service.render_rfq_preview(
        fields=payload.fields,
        contact_name=current_user.full_name,
        contact_email=current_user.email,
        company_name=settings.provider_company_name(settings.email_provider),
    )
    return RfqPreviewResponse(subject=subject, body=body)


@router.get(
    "/email-drafts",
    response_model=list[EmailDraftRead],
    summary="List the current user's drafted emails (optionally by email type)",
)
def list_email_drafts(
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
    email_type: EmailType | None = None,
) -> list[EmailDraftRead]:
    """Return the current user's drafted emails, newest first.

    Args:
        current_user: The authenticated user.
        email_draft_service: Injected email-draft service.
        email_type: Optional email pattern to filter by (query parameter).
            Omit it to get the user's complete draft history across every type.

    Returns:
        Matching drafts, most recent first.
    """
    saved = email_draft_service.list_saved(user_id=current_user.id, email_type=email_type)
    return [EmailDraftRead.model_validate(row) for row in saved]


@router.get(
    "/email-drafts/{draft_id}",
    response_model=EmailDraftRead,
    summary="Fetch one drafted email by id",
)
def get_email_draft(
    draft_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
) -> EmailDraftRead:
    """Return one drafted email owned by the current user.

    Args:
        draft_id: The draft's id.
        current_user: The authenticated user.
        email_draft_service: Injected email-draft service.

    Returns:
        The matching :class:`EmailDraftRead`.

    Raises:
        HTTPException: ``404`` if no such draft exists for this user.
    """
    try:
        draft = email_draft_service.get_saved(user_id=current_user.id, draft_id=draft_id)
    except EmailDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return EmailDraftRead.model_validate(draft)


@router.patch(
    "/email-drafts/{draft_id}",
    response_model=EmailDraftRead,
    summary="Apply a human edit (recipient/subject/body) to a drafted email",
)
def update_email_draft(
    draft_id: uuid.UUID,
    payload: EmailDraftUpdate,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
) -> EmailDraftRead:
    """Apply a human edit to a drafted email. Never changes ``status``.

    Args:
        draft_id: The draft's id.
        payload: The fields to change; omitted fields keep their current value.
        current_user: The authenticated user.
        email_draft_service: Injected email-draft service.

    Returns:
        The updated :class:`EmailDraftRead`.

    Raises:
        HTTPException: ``404`` if no such draft exists for this user.
    """
    try:
        draft = email_draft_service.modify(
            user_id=current_user.id,
            draft_id=draft_id,
            recipient=payload.recipient,
            subject=payload.subject,
            body=payload.body,
        )
    except EmailDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return EmailDraftRead.model_validate(draft)


@router.post(
    "/email-drafts/{draft_id}/verify",
    response_model=EmailDraftRead,
    summary="Mark a drafted email as verified — a human approval action",
)
def verify_email_draft(
    draft_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
) -> EmailDraftRead:
    """Mark a drafted email as verified.

    This is the only endpoint that can move a draft to ``status =
    "verified"`` — generation and edits never do. A future outreach/send
    feature would read this flag and only ever act on verified drafts.

    Args:
        draft_id: The draft's id.
        current_user: The authenticated user.
        email_draft_service: Injected email-draft service.

    Returns:
        The updated :class:`EmailDraftRead`.

    Raises:
        HTTPException: ``404`` if no such draft exists for this user.
    """
    try:
        draft = email_draft_service.verify(user_id=current_user.id, draft_id=draft_id)
    except EmailDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return EmailDraftRead.model_validate(draft)
