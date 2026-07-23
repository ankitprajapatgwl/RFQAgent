"""Data-access layer for :class:`~src.modules.email_extraction.models.ExtractedEmail`.

Implements the *Repository pattern*: every SQL/ORM query for stored extractions
lives behind this class, so the agent and service layers never touch SQLAlchemy
directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.modules.email_extraction.enums import ExtractedEmailType, ExtractionStatus
from src.modules.email_extraction.models import ExtractedEmail


class ExtractionRepository:
    """Read/write access to :class:`ExtractedEmail` records for a single session.

    Args:
        session: The active SQLAlchemy session this repository operates on.
    """

    def __init__(self, session: Session) -> None:
        """Bind the repository to a database session."""
        self._session = session

    def exists_for_email(self, email_id: uuid.UUID) -> bool:
        """Return whether an extraction has already been stored for an email.

        Used by the agent to stay idempotent — a re-processed email is never
        extracted twice (``email_id`` is unique, but checking first avoids a
        needless LLM call).

        Args:
            email_id: The received email's id.

        Returns:
            ``True`` if a row already exists for this email.
        """
        stmt = select(ExtractedEmail.id).where(ExtractedEmail.email_id == email_id).limit(1)
        return self._session.scalars(stmt).first() is not None

    def save(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        email_id: uuid.UUID,
        email_type: ExtractedEmailType,
        status: ExtractionStatus,
        summary: str,
        supplier_email: str,
        original_subject: str,
        original_body: str,
        original_attachments: list[dict[str, Any]],
        details: dict[str, Any],
        confidence: float | None,
        error: str | None,
        model: str | None,
    ) -> ExtractedEmail:
        """Persist one extraction record and return the managed instance.

        Args:
            user_id: Owning user's id.
            conversation_id: The conversation/thread the email belongs to.
            email_id: The received email this extraction was produced from.
            email_type: The classified inbound email type.
            status: Whether the extraction completed or failed.
            summary: Short summary of the email.
            supplier_email: Snapshot of the conversation's supplier address.
            original_subject: The original message's subject.
            original_body: The original message's plain-text body.
            original_attachments: Snapshot of the message's attachments.
            details: The extracted field values.
            confidence: Self-reported confidence, if any.
            error: Failure reason when ``status`` is ``failed``.
            model: The LLM model id used.

        Returns:
            The newly created, flushed :class:`ExtractedEmail`.
        """
        record = ExtractedEmail(
            user_id=user_id,
            conversation_id=conversation_id,
            email_id=email_id,
            email_type=email_type.value,
            status=status.value,
            summary=summary,
            supplier_email=supplier_email,
            original_subject=original_subject,
            original_body=original_body,
            original_attachments=original_attachments,
            details=details,
            confidence=confidence,
            error=error,
            model=model,
        )
        self._session.add(record)
        self._session.flush()  # assigns the primary key without ending the transaction
        return record

    def list_for_user(self, *, user_id: uuid.UUID) -> list[ExtractedEmail]:
        """Return a user's extractions, newest first (the RFQ Monitoring list)."""
        stmt = (
            select(ExtractedEmail)
            .where(ExtractedEmail.user_id == user_id)
            .order_by(ExtractedEmail.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def list_for_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[ExtractedEmail]:
        """Return one conversation's extractions for the owning user, oldest first.

        Ordered oldest-first so the dispatch-history JSON popup reads in the
        same chronological order as the conversation thread.

        Args:
            user_id: The requesting user's id (ownership guard).
            conversation_id: The conversation whose extractions to return.

        Returns:
            Matching :class:`ExtractedEmail` rows, oldest first.
        """
        stmt = (
            select(ExtractedEmail)
            .where(
                ExtractedEmail.user_id == user_id,
                ExtractedEmail.conversation_id == conversation_id,
            )
            .order_by(ExtractedEmail.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())
