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
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from src.modules.auth.deps import RequiredCookieUserDep
from src.modules.email_delivery.attachments import RawAttachment
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


def _read_uploads(uploads: list[UploadFile]) -> list[RawAttachment]:
    """Read uploaded files into in-memory attachments, skipping empty parts.

    The bytes are read synchronously off each upload's underlying file object
    so this stays usable from the module's sync route handlers (which keep the
    blocking provider HTTP call off the event loop).

    Args:
        uploads: The ``UploadFile`` parts parsed from the multipart form.

    Returns:
        One :class:`RawAttachment` per non-empty upload.
    """
    attachments: list[RawAttachment] = []
    for upload in uploads:
        if upload is None or not upload.filename:
            continue
        content = upload.file.read()
        if not content:
            continue
        attachments.append(
            RawAttachment(
                filename=upload.filename,
                content_type=upload.content_type or "application/octet-stream",
                content=content,
            )
        )
    return attachments

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
    attachments: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI form default
) -> ConversationRead:
    """Send an already-verified draft and start tracking its conversation.

    The draft must be verified and carry a recipient — sending is never a side
    effect of drafting or editing, honouring the human-approval gate. Any files
    attached on the draft page are transmitted with the email and persisted.

    Args:
        draft_id: The draft to send.
        current_user: The authenticated user (sender/owner).
        email_draft_service: Used to fetch the verified draft.
        email_delivery_service: Performs the send and persistence.
        attachments: Optional uploaded files to attach to the email.

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
            attachments=_read_uploads(attachments),
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
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
    supplier_email: Annotated[str, Form()],
    supplier_name: Annotated[str, Form()],
    product_name: Annotated[str, Form()],
    quantity: Annotated[int, Form()],
    target_price: Annotated[str, Form()],
    attachments: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI form default
) -> ConversationRead:
    """Send a template-rendered RFQ and start tracking its conversation.

    Accepts ``multipart/form-data`` so files (e.g. a quotation form) can ride
    along with the RFQ fields. The fields are validated through
    :class:`RfqSendRequest` so the contract is unchanged from the old JSON body.

    Args:
        current_user: The authenticated user (sender/owner).
        email_delivery_service: Performs the send and persistence.
        supplier_email: Destination supplier address.
        supplier_name: Supplier display name.
        product_name: Product being quoted.
        quantity: Number of units requested.
        target_price: Buyer's target unit price.
        attachments: Optional uploaded files to attach to the RFQ.

    Returns:
        The created conversation summary.

    Raises:
        HTTPException: ``422`` if the RFQ fields are invalid; ``502`` if the
            provider is misconfigured or the send fails.
    """
    try:
        payload = RfqSendRequest(
            supplier_email=supplier_email,
            supplier_name=supplier_name,
            product_name=product_name,
            quantity=quantity,
            target_price=target_price,
        )
    except ValidationError as exc:
        detail = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", "invalid value")}
            for err in exc.errors()
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        ) from exc

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
            sender_phone=current_user.phone_number or "",
            attachments=_read_uploads(attachments),
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


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation from the dispatch history",
)
def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
) -> Response:
    """Delete one of the current user's tracked conversations.

    Removes the conversation, its full sent/received thread and the backing
    attachment files. Idempotent from the client's view — deleting an unknown
    or already-deleted conversation returns ``404``.

    Args:
        conversation_id: The conversation to delete.
        current_user: The authenticated user (owner).
        email_delivery_service: Performs the delete.

    Returns:
        An empty ``204`` response on success.

    Raises:
        HTTPException: ``404`` if no such conversation exists for this user.
    """
    deleted = email_delivery_service.delete_conversation(
        user_id=current_user.id, conversation_id=conversation_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
