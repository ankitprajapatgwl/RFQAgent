"""SQLAlchemy ORM model for the email-extraction module.

:class:`ExtractedEmail` is the new table required by Requirement 1: one row per
received supplier email (a reply, a forward, or a new thread), holding both the
message's **original content** and the **AI-extracted details**. Every row is
bound to the received email it came from (``email_id``), the conversation/thread
that email belongs to (``conversation_id``), and the owning user (``user_id``).
A conversation can accrue many replies over time, so it can own many
``ExtractedEmail`` rows — one per received message.

Foreign keys reference the auth and email-delivery tables **by name only**
(``users`` / ``email_conversations`` / ``email_messages``) rather than importing
those modules' ORM classes, so this module stays independent of their Python
code while still enforcing referential integrity — the same convention
``sample_data`` and ``email_draft`` use. ``ondelete="CASCADE"`` means deleting a
conversation from the dispatch history also removes its extractions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.integrations.database import Base
from src.modules.email_extraction.constants import label_for
from src.modules.email_extraction.enums import ExtractedEmailType, ExtractionStatus


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class ExtractedEmail(Base):
    """One received email's original content plus its AI-extracted details.

    Attributes:
        id: Surrogate primary key.
        user_id: Owning user's id (FK ``users``, cascade-deleted).
        conversation_id: The conversation/thread this email belongs to (FK
            ``email_conversations``, cascade-deleted).
        email_id: The specific received email this extraction was produced from
            (FK ``email_messages``, cascade-deleted). Unique — at most one
            extraction per received email, which also makes reprocessing
            idempotent.
        email_type: The classified inbound email type (RFQ quote, follow-up,
            negotiation, ...). Stored as the enum's value.
        status: Whether the extraction completed or failed.
        summary: Short AI summary of the message.
        supplier_email: Snapshot of the conversation's supplier address, so the
            monitoring list is a single-table read.
        original_subject: The original message's subject line.
        original_body: The original message's plain-text body.
        original_attachments: Snapshot of the message's attachments
            (``[{filename, url, content_type, size_bytes}, ...]``).
        details: The extracted field values, keyed by field name.
        confidence: The model's self-reported confidence, if provided.
        error: Failure reason when ``status`` is ``failed``.
        model: The LLM model id that produced the extraction (traceability).
        created_at: When the extraction was recorded.
    """

    __tablename__ = "extracted_emails"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("email_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("email_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    email_type: Mapped[str] = mapped_column(
        String(32), default=ExtractedEmailType.GENERAL.value, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ExtractionStatus.COMPLETED.value, nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    supplier_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    original_subject: Mapped[str] = mapped_column(Text, default="", nullable=False)
    original_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    original_attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    @property
    def email_type_label(self) -> str:
        """Human-readable label for :attr:`email_type` (read by the API schema)."""
        try:
            return label_for(ExtractedEmailType(self.email_type))
        except ValueError:  # pragma: no cover - defensive against unknown stored values
            return self.email_type

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return (
            f"<ExtractedEmail id={self.id} email_id={self.email_id} "
            f"type={self.email_type!r} status={self.status!r}>"
        )
