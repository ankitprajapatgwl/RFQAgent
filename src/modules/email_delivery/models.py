"""SQLAlchemy ORM models for the email-delivery module.

A tracked RFQ conversation and its thread of sent/received emails, adapted
from the reference EmailPOC schema to this project's sync SQLite + shared
:class:`~src.integrations.database.Base` conventions:

* Postgres-specific types are replaced with portable ones — ``UUID`` →
  :class:`~sqlalchemy.Uuid`, ``JSONB`` → :class:`~sqlalchemy.JSON`, ``ARRAY``
  → a JSON list, ``Numeric`` → :class:`~sqlalchemy.Float`.
* ``conversations.user_id`` references the auth module's ``users`` table **by
  name only** (no import of the ``User`` class), so this module stays
  independent of auth's Python code while still enforcing referential
  integrity — the same pattern ``modules/email_draft`` uses.

Persisting inbound replies here (``emails`` rows with ``direction="received"``
under the owning user's conversation) is what fulfils "save each supplier
response against its user for future use".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.integrations.database import Base
from src.modules.email_delivery.enums import (
    ConversationStatus,
    EmailProcessingStatus,
    UnmatchedStatus,
)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Conversation(Base):
    """A tracked RFQ conversation between one user and one supplier.

    Attributes:
        id: Surrogate primary key.
        user_id: Owning user's id (FK to ``users``, cascade-deleted).
        token: The 8-char hex conversation id encoded into the Reply-To
            address; unique — the real backstop against id collisions.
        reply_to_address: The dynamic per-conversation address suppliers reply
            to, which routes back to the inbound webhook.
        provider: Provider key that sent the first message (e.g. ``engagelab``).
        send_kind: Which outbound flow opened the conversation (draft/rfq).
        supplier_email: Destination supplier address.
        supplier_name: Supplier display name for salutations.
        subject: Subject line of the conversation's first email.
        product_name / quantity / target_price: RFQ metadata, when the
            conversation was opened by a standalone RFQ send (else ``None``).
        status: Lifecycle state (open / replied / declined).
        reply_count: Number of received replies recorded.
        last_reply_at: Timestamp of the most recent received reply.
        created_at: When the conversation was created.
    """

    __tablename__ = "email_conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    reply_to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    send_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    supplier_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    subject: Mapped[str] = mapped_column(Text, default="", nullable=False)
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_price: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=ConversationStatus.OPEN.value, nullable=False, index=True
    )
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    emails: Mapped[list[Email]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Email.created_at",
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<Conversation id={self.id} token={self.token!r} status={self.status!r}>"


class Email(Base):
    """One sent or received message within a conversation.

    Attributes:
        id: Surrogate primary key.
        conversation_id: Owning conversation (FK, cascade-deleted).
        direction: ``sent`` or ``received``.
        from_email / to_email: Envelope addresses.
        subject: Subject line.
        body_text / body_html: Message bodies.
        provider: Provider key that transmitted/received it.
        provider_message_id: The provider's message id, when known.
        inbound_type: For received emails, reply/forwarded/new_thread.
        matched_via: For received emails, how it was matched to the conversation.
        reply_action: For received emails, the coarse classification.
        dkim / spf: Auth check results for received emails.
        spam_score: SpamAssassin-style score for received emails.
        status_code: HTTP status the provider returned for a sent email.
        processing_status: Background-processing state driven by the ``worker``
            module (``pending`` on creation, ``processed`` once handled). Only
            received emails are picked up for processing today.
        created_at: When the row was recorded.
    """

    __tablename__ = "email_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("email_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    from_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    to_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    subject: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inbound_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    matched_via: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reply_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dkim: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spf: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(
        String(16),
        default=EmailProcessingStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="emails")
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<Email id={self.id} direction={self.direction!r} subject={self.subject!r}>"


class Attachment(Base):
    """A file attached to a received email, persisted to the attachments dir.

    Attributes:
        id: Surrogate primary key.
        email_id: Owning email (FK, cascade-deleted).
        filename: Original filename.
        url: Served URL under the attachments mount.
        content_type: MIME type.
        size_bytes: Size of the stored file.
    """

    __tablename__ = "email_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    email: Mapped[Email] = relationship(back_populates="attachments")

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<Attachment id={self.id} filename={self.filename!r}>"


class UnmatchedEmail(Base):
    """An inbound email that could not be matched to any conversation.

    Stored for manual review rather than dropped, so a misrouted supplier
    reply is never silently lost.

    Attributes:
        id: Surrogate primary key.
        raw_payload: The normalised inbound fields, kept for triage.
        from_email / to_email: Envelope addresses, when known.
        subject: Subject line, when known.
        reason: Why it couldn't be matched (address_not_recognized, ...).
        provider: Provider key that produced the payload.
        status: Triage state (needs_review / resolved / ignored).
        created_at: When it was recorded.
    """

    __tablename__ = "email_unmatched"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    to_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=UnmatchedStatus.NEEDS_REVIEW.value, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<UnmatchedEmail id={self.id} reason={self.reason!r} status={self.status!r}>"
