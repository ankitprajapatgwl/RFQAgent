"""Data-access layer for :class:`~src.domain.models.User`.

Implements the *Repository pattern*: all SQL/ORM queries for users live behind
this class, so the service layer never touches SQLAlchemy directly. Swapping the
storage backend later means changing only this file.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.enums import UserRole
from src.domain.models import User


class UserRepository:
    """Read/write access to :class:`User` records for a single session.

    Args:
        session: The active SQLAlchemy session this repository operates on.
    """

    def __init__(self, session: Session) -> None:
        """Bind the repository to a database session."""
        self._session = session

    def get_by_email(self, email: str) -> User | None:
        """Return the user with the given email, or ``None`` if not found.

        The lookup is case-insensitive so ``User@x.com`` and ``user@x.com``
        resolve to the same account.

        Args:
            email: The email address to look up.

        Returns:
            The matching :class:`User`, or ``None``.
        """
        normalized = self._normalize_email(email)
        stmt = select(User).where(User.email == normalized)
        return self._session.scalars(stmt).first()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the user with the given id, or ``None`` if not found.

        Args:
            user_id: The primary key to look up.

        Returns:
            The matching :class:`User`, or ``None``.
        """
        return self._session.get(User, user_id)

    def create(
        self,
        *,
        email: str,
        full_name: str,
        hashed_password: str,
        role: UserRole = UserRole.BUYER,
    ) -> User:
        """Persist a new user and return the managed instance.

        The caller is responsible for having verified the email is unique; this
        method only performs the insert (the surrounding session controls the
        transaction boundary).

        Args:
            email: Unique login email (stored normalised to lowercase).
            full_name: Display name.
            hashed_password: Pre-hashed password digest.
            role: Authorisation role, defaulting to ``BUYER``.

        Returns:
            The newly created, flushed :class:`User` with its ``id`` populated.
        """
        user = User(
            email=self._normalize_email(email),
            full_name=full_name,
            hashed_password=hashed_password,
            role=role,
        )
        self._session.add(user)
        self._session.flush()  # assigns the primary key without ending the transaction
        return user

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Normalise an email for storage and comparison."""
        return email.strip().lower()
