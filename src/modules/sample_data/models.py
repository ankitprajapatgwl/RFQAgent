"""SQLAlchemy ORM models for the sample-data module.

Persists every generated sample query so a user can revisit and reuse one
later instead of generating a fresh one each time (the "saved sample data"
dropdown on the dashboard).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.integrations.database import Base


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class SavedSampleQuery(Base):
    """A previously generated sample email-drafting query, owned by a user.

    Attributes:
        id: Surrogate primary key, a randomly generated UUID.
        user_id: Owning user's id. Referenced by table name only (``users``)
            rather than importing the auth module's ``User`` class, so this
            module stays independent of the auth module's Python code while
            still enforcing referential integrity at the database level.
        email_type: Which email pattern this sample was generated for.
        fields: The mandatory (and any volunteered optional) field values,
            keyed by field name.
        query_text: The ready-to-use natural-language request generated
            alongside ``fields``.
        created_at: UTC timestamp when the sample was generated.
    """

    __tablename__ = "saved_sample_queries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fields: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<SavedSampleQuery id={self.id} email_type={self.email_type!r}>"
