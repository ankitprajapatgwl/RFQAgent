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
from src.modules.email_delivery.exceptions import ConversationNotFoundError, EmailProviderError
from src.modules.email_delivery.providers import EmailMaster
from src.modules.email_delivery.schemas import (
    ConversationDetail,
    ConversationRead,
    FollowupSendRequest,
    InboundResult,
    NegotiationSendRequest,
    RfqSendRequest,
)

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


@router.post(
    "/conversations/{conversation_id}/follow-up",
    response_model=ConversationRead,
    summary="Send a template-rendered follow-up reminder on an existing conversation",
)
def send_followup(
    conversation_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
    submission_deadline: Annotated[str, Form()],
    rfq_reference: Annotated[str, Form()] = "",
    portal_link: Annotated[str, Form()] = "",
    include_qa_note: Annotated[bool, Form()] = False,
    attachments: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI form default
) -> ConversationRead:
    """Send a follow-up reminder on an existing tracked conversation.

    Unlike ``/conversations/rfq`` (which always opens a new conversation),
    this appends to one that already exists, so it threads into the same
    supplier relationship. Accepts ``multipart/form-data`` so files can ride
    along, matching the other send endpoints.

    Args:
        conversation_id: The conversation to send the follow-up on.
        current_user: The authenticated user (sender/owner).
        email_delivery_service: Performs the send and persistence.
        submission_deadline: The (possibly new) deadline to highlight.
        rfq_reference: Optional label naming the original RFQ.
        portal_link: Optional URL to a submission portal.
        include_qa_note: Whether to include the "questions welcome" reminder.
        attachments: Optional uploaded files to attach to the follow-up.

    Returns:
        The conversation summary.

    Raises:
        HTTPException: ``422`` if the fields are invalid; ``404`` if no such
            conversation exists for this user; ``502`` if the provider send fails.
    """
    try:
        payload = FollowupSendRequest(
            submission_deadline=submission_deadline,
            rfq_reference=rfq_reference,
            portal_link=portal_link,
            include_qa_note=include_qa_note,
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
        conversation = email_delivery_service.send_followup(
            user_id=current_user.id,
            conversation_id=conversation_id,
            user_name=current_user.full_name,
            sender_email=current_user.sending_email,
            contact_email=current_user.email,
            submission_deadline=payload.submission_deadline,
            rfq_reference=payload.rfq_reference,
            portal_link=payload.portal_link,
            include_qa_note=payload.include_qa_note,
            attachments=_read_uploads(attachments),
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmailProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ConversationRead.model_validate(conversation)


@router.post(
    "/conversations/{conversation_id}/negotiation",
    response_model=ConversationRead,
    summary="Send a template-rendered negotiation/counter-offer on an existing conversation",
)
def send_negotiation(
    conversation_id: uuid.UUID,
    current_user: RequiredCookieUserDep,
    email_delivery_service: EmailDeliveryServiceDep,
    response_deadline: Annotated[str, Form()],
    rfq_reference: Annotated[str, Form()] = "",
    original_quoted_price: Annotated[str, Form()] = "",
    target_price: Annotated[str, Form()] = "",
    new_quantity: Annotated[str, Form()] = "",
    quoted_terms: Annotated[str, Form()] = "",
    requested_terms: Annotated[str, Form()] = "",
    quoted_lead_time: Annotated[str, Form()] = "",
    target_date: Annotated[str, Form()] = "",
    clarifications: Annotated[str, Form()] = "",
    portal_link: Annotated[str, Form()] = "",
    include_meeting_request: Annotated[bool, Form()] = False,
    attachments: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI form default
) -> ConversationRead:
    """Send a negotiation/counter-offer on an existing tracked conversation.

    Unlike ``/conversations/rfq`` (which always opens a new conversation),
    this appends to one that already exists, so it threads into the same
    supplier relationship. Every adjustment field is optional and
    independently gated in the rendered email.

    Args:
        conversation_id: The conversation to send the negotiation on.
        current_user: The authenticated user (sender/owner).
        email_delivery_service: Performs the send and persistence.
        response_deadline: Deadline for the supplier to respond.
        rfq_reference: Optional label naming the original RFQ.
        original_quoted_price: The supplier's quoted price, if negotiating price.
        target_price: The buyer's target price, if negotiating price.
        new_quantity: A proposed new order quantity, if negotiating volume.
        quoted_terms: The supplier's quoted payment terms, if negotiating terms.
        requested_terms: The buyer's requested payment terms.
        quoted_lead_time: The supplier's quoted lead time, if negotiating schedule.
        target_date: The buyer's requested delivery date.
        clarifications: A free-text technical/scope note, if any.
        portal_link: Optional URL to a revised-quote submission portal.
        include_meeting_request: Whether to include the "let's hop on a call" note.
        attachments: Optional uploaded files to attach to the negotiation.

    Returns:
        The conversation summary.

    Raises:
        HTTPException: ``422`` if the fields are invalid; ``404`` if no such
            conversation exists for this user; ``502`` if the provider send fails.
    """
    try:
        payload = NegotiationSendRequest(
            response_deadline=response_deadline,
            rfq_reference=rfq_reference,
            original_quoted_price=original_quoted_price,
            target_price=target_price,
            new_quantity=new_quantity,
            quoted_terms=quoted_terms,
            requested_terms=requested_terms,
            quoted_lead_time=quoted_lead_time,
            target_date=target_date,
            clarifications=clarifications,
            portal_link=portal_link,
            include_meeting_request=include_meeting_request,
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
        conversation = email_delivery_service.send_negotiation(
            user_id=current_user.id,
            conversation_id=conversation_id,
            user_name=current_user.full_name,
            sender_email=current_user.sending_email,
            response_deadline=payload.response_deadline,
            rfq_reference=payload.rfq_reference,
            original_quoted_price=payload.original_quoted_price,
            target_price=payload.target_price,
            new_quantity=payload.new_quantity,
            quoted_terms=payload.quoted_terms,
            requested_terms=payload.requested_terms,
            quoted_lead_time=payload.quoted_lead_time,
            target_date=payload.target_date,
            clarifications=payload.clarifications,
            portal_link=payload.portal_link,
            include_meeting_request=payload.include_meeting_request,
            attachments=_read_uploads(attachments),
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
