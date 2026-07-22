"""Data-access layer for :class:`~src.modules.email_draft.models.DraftedEmail`.

Implements the *Repository pattern*: all SQL/ORM queries for drafted emails
live behind this class, so the service layer never touches SQLAlchemy
directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.modules.email_draft.models import DraftedEmail
from src.modules.email_patterns import EmailType


class EmailDraftRepository:
    """Read/write access to :class:`DraftedEmail` records for a single session.

    Args:
        session: The active SQLAlchemy session this repository operates on.
    """

    def __init__(self, session: Session) -> None:
        """Bind the repository to a database session."""
        self._session = session

    def save(
        self,
        *,
        user_id: uuid.UUID,
        email_type: EmailType,
        query_text: str,
        subject: str,
        body: str,
    ) -> DraftedEmail:
        """Persist a freshly drafted email and return the managed instance.

        Always creates the record with the default (``"draft"``) status —
        callers cannot pass a different one through this method.

        Args:
            user_id: Owning user's id.
            email_type: Which email pattern the draft is for.
            query_text: The natural-language request the draft was generated from.
            subject: The generated subject line.
            body: The generated body.

        Returns:
            The newly created, flushed :class:`DraftedEmail`.
        """
        record = DraftedEmail(
            user_id=user_id,
            email_type=email_type.value,
            query_text=query_text,
            subject=subject,
            body=body,
        )
        self._session.add(record)
        self._session.flush()  # assigns the primary key without ending the transaction
        return record

    def list_for_user(
        self, *, user_id: uuid.UUID, email_type: EmailType | None = None
    ) -> list[DraftedEmail]:
        """Return a user's drafted emails, newest first.

        Args:
            user_id: Owning user's id.
            email_type: Optional email pattern to filter by. When ``None``
                (the default), every draft for the user is returned
                regardless of type.

        Returns:
            Matching :class:`DraftedEmail` rows, most recent first.
        """
        stmt = select(DraftedEmail).where(DraftedEmail.user_id == user_id)
        if email_type is not None:
            stmt = stmt.where(DraftedEmail.email_type == email_type.value)
        stmt = stmt.order_by(DraftedEmail.created_at.desc())
        return list(self._session.scalars(stmt).all())

    def get_for_user(self, *, user_id: uuid.UUID, draft_id: uuid.UUID) -> DraftedEmail | None:
        """Return one drafted email owned by the given user, if it exists.

        Args:
            user_id: Owning user's id.
            draft_id: The draft's id.

        Returns:
            The matching :class:`DraftedEmail`, or ``None`` if it doesn't
            exist or isn't owned by this user.
        """
        stmt = select(DraftedEmail).where(
            DraftedEmail.id == draft_id, DraftedEmail.user_id == user_id
        )
        return self._session.scalars(stmt).first()

    def update(self, record: DraftedEmail, **changes: Any) -> DraftedEmail:
        """Apply field changes to an already-fetched draft and flush.

        Args:
            record: A :class:`DraftedEmail` previously returned by this
                repository (attached to this session).
            **changes: Column name/value pairs to set on the record.

        Returns:
            The updated, flushed :class:`DraftedEmail`.
        """
        for field_name, value in changes.items():
            setattr(record, field_name, value)
        self._session.flush()
        return record
