"""JSON API + inbound webhook routes for the email-delivery module.

Two routers are exported:

* :data:`router` — authenticated JSON API (``/api/v1/email-delivery/...``):
  send a verified draft, send a standalone RFQ, and read conversation
  tracking (list + full thread).
* :data:`webhook_router` — the single **unauthenticated** inbound webhook
  (``POST /webhooks/inbound``), which email providers call anonymously, plus a
  ``GET`` probe some providers issue before saving a webhook URL.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.modules.auth.deps import RequiredCookieUserDep
from src.modules.email_delivery.deps import EmailDeliveryServiceDep
from src.modules.email_delivery.exceptions import EmailProviderError
from src.modules.email_delivery.schemas import (
    ConversationDetail,
    ConversationRead,
    InboundResult,
    RfqSendRequest,
)
from src.modules.email_draft.deps import EmailDraftServiceDep
from src.modules.email_draft.enums import DraftStatus
from src.modules.email_draft.exceptions import EmailDraftNotFoundError

router = APIRouter(prefix="/api/v1/email-delivery", tags=["email-delivery"])

# Greetings the drafter opens a body with; the captured group is the recipient's
# display name the model pulled from the query (e.g. "Dear Jane Smith,").
_GREETING_RE = re.compile(
    r"^\s*(?:dear|hi|hello|hey|greetings)\s+([^\n,.:;!?]+)", re.IGNORECASE
)


def extract_recipient_name(body: str) -> str:
    """Recover the recipient's display name from a drafted email's greeting.

    Task: "extract recipient_name from the query and pass it to the send API".
    The drafter already resolves the name from the user's query into the body's
    salutation, so the greeting is the canonical, no-extra-call source. An
    unresolved bracketed placeholder (``[recipient name]``) is treated as no
    name rather than sent literally.

    Args:
        body: The drafted email body.

    Returns:
        The recipient's display name, or ``""`` if none could be recovered.
    """
    match = _GREETING_RE.match(body or "")
    if not match:
        return ""
    name = match.group(1).strip()
    if "[" in name or "]" in name:
        return ""
    return name

# HTTP status per inbound outcome. matched/unmatched/skipped return 200 so
# providers don't retry a non-delivery-failure; only auth/parse failures are
# surfaced as 4xx/5xx.
_INBOUND_STATUS_CODES = {
    "matched": status.HTTP_200_OK,
    "unmatched": status.HTTP_200_OK,
    "skipped": status.HTTP_200_OK,
    "rejected": status.HTTP_400_BAD_REQUEST,
    "error": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


@router.post(
    "/conversations/from-draft/{draft_id}",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a human-verified draft, opening a tracked conversation",
)
def send_verified_draft(
    draft_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_draft_service: EmailDraftServiceDep,
    email_delivery_service: EmailDeliveryServiceDep,
) -> ConversationRead:
    """Send an already-verified draft and start tracking its conversation.

    The draft must be verified and carry a recipient — sending is never a side
    effect of drafting or editing, honouring the human-approval gate.

    Args:
        draft_id: The draft to send.
        current_user: The authenticated user (sender/owner).
        email_draft_service: Used to fetch the verified draft.
        email_delivery_service: Performs the send and persistence.

    Returns:
        The created conversation summary.

    Raises:
        HTTPException: ``404`` if the draft doesn't exist; ``409`` if it isn't
            verified or has no recipient; ``502`` if the provider send fails.
    """
    try:
        draft = email_draft_service.get_saved(user_id=current_user.id, draft_id=draft_id)
    except EmailDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if draft.status != DraftStatus.VERIFIED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft must be verified before it can be sent.",
        )
    if not draft.recipient:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft has no recipient address to send to.",
        )

    try:
        conversation = email_delivery_service.send_draft(
            user_id=current_user.id,
            user_name=current_user.full_name,
            sender_email=current_user.sending_email,
            recipient=draft.recipient,
            recipient_name=extract_recipient_name(draft.body),
            subject=draft.subject,
            body_text=draft.body,
        )
    except EmailProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ConversationRead.model_validate(conversation)


@router.post(
    "/conversations/rfq",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a standalone, template-rendered RFQ email",
)
def send_rfq(
    payload: RfqSendRequest,
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
) -> ConversationRead:
    """Send a template-rendered RFQ and start tracking its conversation.

    Args:
        payload: The RFQ fields (supplier, product, quantity, target price).
        current_user: The authenticated user (sender/owner).
        email_delivery_service: Performs the send and persistence.

    Returns:
        The created conversation summary.

    Raises:
        HTTPException: ``502`` if the provider is misconfigured or the send fails.
    """
    try:
        conversation = email_delivery_service.send_rfq(
            user_id=current_user.id,
            user_name=current_user.full_name,
            sender_email=current_user.sending_email,
            supplier_email=payload.supplier_email,
            supplier_name=payload.supplier_name,
            product_name=payload.product_name,
            quantity=payload.quantity,
            target_price=payload.target_price,
        )
    except EmailProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ConversationRead.model_validate(conversation)


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    summary="List the current user's tracked conversations (newest first)",
)
def list_conversations(
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
) -> list[ConversationRead]:
    """Return the current user's conversations, newest first."""
    conversations = email_delivery_service.list_conversations(user_id=current_user.id)
    return [ConversationRead.model_validate(row) for row in conversations]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="Fetch one conversation with its full sent+received email thread",
)
def get_conversation(
    conversation_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
) -> ConversationDetail:
    """Return one owned conversation with its full email thread.

    Raises:
        HTTPException: ``404`` if no such conversation exists for this user.
    """
    conversation = email_delivery_service.get_conversation_detail(
        user_id=current_user.id, conversation_id=conversation_id
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return ConversationDetail.model_validate(conversation)


# ── Inbound webhook (unauthenticated — providers call it anonymously) ────────

webhook_router = APIRouter(tags=["email-webhook"])


@webhook_router.post("/webhooks/inbound", summary="Provider inbound-mail webhook")
async def inbound_webhook(
    request: Request,
    email_delivery_service: EmailDeliveryServiceDep,
) -> JSONResponse:
    """Receive, match and persist one inbound supplier reply.

    Delegates to :meth:`EmailDeliveryService.handle_inbound` and maps its
    ``status`` to an HTTP code (see :data:`_INBOUND_STATUS_CODES`).

    Args:
        request: The raw inbound POST from the email provider.
        email_delivery_service: Parses, matches and persists the reply.

    Returns:
        A JSON body describing the outcome, with a status-mapped HTTP code.
    """
    result = await email_delivery_service.handle_inbound(request)
    body = InboundResult(
        status=result.get("status", "error"),
        conv_id=result.get("conv_id"),
        action=result.get("action"),
        reason=result.get("reason"),
    )
    http_status = _INBOUND_STATUS_CODES.get(body.status, status.HTTP_200_OK)
    return JSONResponse(status_code=http_status, content=body.model_dump(mode="json"))


@webhook_router.get("/webhooks/inbound", summary="Inbound webhook health probe")
def inbound_webhook_probe() -> dict[str, str]:
    """Return ``{"status": "ok"}`` for providers that GET-probe the URL first."""
    return {"status": "ok"}
