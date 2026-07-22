"""SQLAlchemy ORM models for the auth module.

These are the persistence-layer representations of domain entities. Pydantic
schemas (see :mod:`src.modules.auth.schemas`) are the API contracts; this
module is strictly about how entities are stored.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.integrations.database import Base
from src.modules.auth.enums import UserRole


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class User(Base):
    """A registered application user.

    Attributes:
        id: Surrogate primary key, a randomly generated UUID.
        email: Unique, case-insensitive login identifier.
        full_name: Display name of the user.
        hashed_password: Bcrypt hash of the user's password. The plaintext
            password is never stored.
        role: Authorisation role for the account.
        is_active: Whether the account may authenticate.
        sending_email: The user's permanent, unique outbound address
            (``{CamelCaseName}@{outbound_domain}``), assigned once at
            registration when an email-sending domain is configured. It is
            independent of the login ``email`` and is what the email-delivery
            module matches a brand-new (headerless) supplier email against to
            recover its owning user. ``None`` when no sending domain is
            configured, in which case new-thread matching is simply skipped.
        created_at: UTC timestamp when the account was created.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(20), default=UserRole.BUYER, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sending_email: Mapped[str | None] = mapped_column(
        String(320), unique=True, index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for debugging/logs."""
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
