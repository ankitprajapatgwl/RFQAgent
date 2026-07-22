"""SQLAlchemy ORM models for the email-draft module.

Persists every drafted email immediately (status ``"draft"``) so a user can
reload the dashboard, revisit, edit, and verify it later instead of losing it
— the same "generate now, save immediately" pattern used by
``modules/sample_data``.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.integrations.database import Base
from src.modules.email_draft.enums import DraftStatus


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class DraftedEmail(Base):
    """A drafted email, owned by a user, awaiting human review.

    Attributes:
        id: Surrogate primary key, a randomly generated UUID.
        user_id: Owning user's id. Referenced by table name only (``users``)
            rather than importing the auth module's ``User`` class, so this
            module stays independent of the auth module's Python code while
            still enforcing referential integrity at the database level.
        email_type: Which email pattern this draft was generated for.
        query_text: The natural-language request the draft was generated
            from — kept for context if the user wants to regenerate or
            compare later.
        recipient: The intended recipient's email address, if the user has
            filled it in yet. Nullable — the agent never invents a real
            address; only a human sets this via a modify.
        subject: The email subject line.
        body: The email body.
        status: Lifecycle state — ``"draft"`` until a human explicitly
            verifies it. See :class:`~src.modules.email_draft.enums.DraftStatus`.
        created_at: UTC timestamp when the draft was generated.
        updated_at: UTC timestamp of the most recent human edit or
            verification.
    """

    __tablename__ = "drafted_emails"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DraftStatus.DRAFT.value, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<DraftedEmail id={self.id} email_type={self.email_type!r} status={self.status!r}>"
