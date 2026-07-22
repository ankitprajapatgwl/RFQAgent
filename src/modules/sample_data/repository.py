"""Data-access layer for :class:`~src.modules.sample_data.models.SavedSampleQuery`.

Implements the *Repository pattern*: all SQL/ORM queries for saved sample
queries live behind this class, so the service layer never touches
SQLAlchemy directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.modules.sample_data.enums import EmailType
from src.modules.sample_data.models import SavedSampleQuery


class SampleQueryRepository:
    """Read/write access to :class:`SavedSampleQuery` records for a single session.

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
        fields: dict[str, str],
        query_text: str,
    ) -> SavedSampleQuery:
        """Persist a generated sample query and return the managed instance.

        Args:
            user_id: Owning user's id.
            email_type: Which email pattern the sample is for.
            fields: The generated field values.
            query_text: The generated natural-language request.

        Returns:
            The newly created, flushed :class:`SavedSampleQuery`.
        """
        record = SavedSampleQuery(
            user_id=user_id,
            email_type=email_type.value,
            fields=fields,
            query_text=query_text,
        )
        self._session.add(record)
        self._session.flush()  # assigns the primary key without ending the transaction
        return record

    def list_for_user(
        self, *, user_id: uuid.UUID, email_type: EmailType | None = None
    ) -> list[SavedSampleQuery]:
        """Return a user's saved samples, newest first.

        Args:
            user_id: Owning user's id.
            email_type: Optional email pattern to filter by. When ``None``
                (the default), every saved sample for the user is returned
                regardless of type.

        Returns:
            Matching :class:`SavedSampleQuery` rows, most recent first.
        """
        stmt = select(SavedSampleQuery).where(SavedSampleQuery.user_id == user_id)
        if email_type is not None:
            stmt = stmt.where(SavedSampleQuery.email_type == email_type.value)
        stmt = stmt.order_by(SavedSampleQuery.created_at.desc())
        return list(self._session.scalars(stmt).all())
