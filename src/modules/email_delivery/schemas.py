"""Pydantic request/response contracts for the email-delivery module.

Every value crossing the HTTP boundary is validated against one of these
models rather than a loose ``dict`` (the contract-first rule). The persisted
ORM rows are mapped to the ``*Read`` shapes via ``from_attributes``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.modules.email_delivery.enums import (
    ConversationStatus,
    EmailDirection,
    InboundEmailType,
    MatchedVia,
    ReplyAction,
    SendKind,
)


class RfqSendRequest(BaseModel):
    """Input contract for a standalone (template-rendered) RFQ send.

    Attributes:
        supplier_email: Destination supplier address.
        supplier_name: Supplier display name for the salutation.
        product_name: Product being quoted.
        quantity: Number of units requested.
        target_price: Buyer's target unit price, e.g. ``"$12.00"``.
    """

    supplier_email: EmailStr
    supplier_name: str = Field(min_length=1, max_length=255)
    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(gt=0)
    target_price: str = Field(min_length=1, max_length=64)


class FollowupSendRequest(BaseModel):
    """Input contract for sending a follow-up reminder on an existing conversation.

    Attributes:
        submission_deadline: The (possibly new) deadline to highlight.
        rfq_reference: Optional label naming the original RFQ; defaults to the
            conversation's subject when left blank.
        portal_link: Optional URL to a submission portal.
        include_qa_note: Whether to include the "questions welcome" reminder.
    """

    submission_deadline: str = Field(min_length=1, max_length=255)
    rfq_reference: str = Field(default="", max_length=255)
    portal_link: str = Field(default="", max_length=2048)
    include_qa_note: bool = False


class NegotiationSendRequest(BaseModel):
    """Input contract for sending a negotiation/counter-offer on an existing conversation.

    Every adjustment is optional and independently gated in the rendered
    email — a pricing/volume/terms/lead-time/clarification block only
    appears once its value(s) are supplied.

    Attributes:
        response_deadline: Deadline for the supplier to respond.
        rfq_reference: Optional label naming the original RFQ; defaults to
            the conversation's subject when left blank.
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
    """

    response_deadline: str = Field(min_length=1, max_length=255)
    rfq_reference: str = Field(default="", max_length=255)
    original_quoted_price: str = Field(default="", max_length=64)
    target_price: str = Field(default="", max_length=64)
    new_quantity: str = Field(default="", max_length=64)
    quoted_terms: str = Field(default="", max_length=255)
    requested_terms: str = Field(default="", max_length=255)
    quoted_lead_time: str = Field(default="", max_length=255)
    target_date: str = Field(default="", max_length=64)
    clarifications: str = Field(default="", max_length=2000)
    portal_link: str = Field(default="", max_length=2048)
    include_meeting_request: bool = False


class AttachmentRead(BaseModel):
    """Output contract for a stored attachment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    url: str
    content_type: str | None
    size_bytes: int | None


class EmailMessageRead(BaseModel):
    """Output contract for one message in a conversation thread."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: EmailDirection
    from_email: str
    to_email: str
    subject: str
    body_text: str | None
    body_html: str | None
    provider: str | None
    inbound_type: InboundEmailType | None
    matched_via: MatchedVia | None
    reply_action: ReplyAction | None
    spam_score: float | None
    status_code: int | None
    created_at: datetime
    attachments: list[AttachmentRead] = Field(default_factory=list)


class ConversationRead(BaseModel):
    """Output contract for a conversation summary (no thread)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    token: str
    reply_to_address: str
    provider: str
    send_kind: SendKind | None
    supplier_email: str
    supplier_name: str
    subject: str
    product_name: str | None
    quantity: str | None
    target_price: str | None
    status: ConversationStatus
    reply_count: int
    last_reply_at: datetime | None
    created_at: datetime


class ConversationDetail(ConversationRead):
    """Output contract for a conversation plus its full email thread."""

    emails: list[EmailMessageRead] = Field(default_factory=list)


class InboundResult(BaseModel):
    """Output contract for the inbound-webhook handler's outcome.

    Attributes:
        status: One of ``matched`` / ``unmatched`` / ``skipped`` /
            ``rejected`` / ``error``.
        conv_id: The matched conversation token, when ``status == "matched"``.
        action: The reply classification, when matched.
        reason: A short machine-readable reason for non-matched outcomes.
    """

    status: str
    conv_id: str | None = None
    action: ReplyAction | None = None
    reason: str | None = None
