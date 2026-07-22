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
