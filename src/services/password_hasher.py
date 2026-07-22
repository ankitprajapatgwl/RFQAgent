"""Password hashing strategy.

An abstract :class:`PasswordHasher` defines the contract; :class:`BcryptPasswordHasher`
is the concrete bcrypt implementation. This *Strategy pattern* means the hashing
algorithm can be swapped (e.g. to Argon2) without touching the rest of the app —
callers depend only on the abstract interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import bcrypt

# Bcrypt operates on at most 72 bytes of input; inputs are encoded and truncated
# defensively so an over-long password can never raise at hash time.
_BCRYPT_MAX_BYTES = 72


class PasswordHasher(ABC):
    """Abstract hashing strategy for user passwords."""

    @abstractmethod
    def hash(self, plain_password: str) -> str:
        """Return a secure, salted hash of ``plain_password``.

        Args:
            plain_password: The user's plaintext password.

        Returns:
            The hash, encoded as a UTF-8 string safe to persist.
        """

    @abstractmethod
    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Check whether ``plain_password`` matches ``hashed_password``.

        Args:
            plain_password: The candidate plaintext password.
            hashed_password: A previously stored hash.

        Returns:
            ``True`` if the password matches, ``False`` otherwise.
        """


class BcryptPasswordHasher(PasswordHasher):
    """Bcrypt-based implementation of :class:`PasswordHasher`.

    Args:
        rounds: The bcrypt cost factor (work factor). Higher is slower and more
            secure. The default of 12 is a sensible production baseline.
    """

    def __init__(self, rounds: int = 12) -> None:
        """Store the configured bcrypt cost factor."""
        self._rounds = rounds

    @staticmethod
    def _encode(plain_password: str) -> bytes:
        """Encode and safely truncate a password to bcrypt's 72-byte limit."""
        return plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]

    def hash(self, plain_password: str) -> str:
        """Hash ``plain_password`` with a freshly generated salt."""
        salt = bcrypt.gensalt(rounds=self._rounds)
        digest = bcrypt.hashpw(self._encode(plain_password), salt)
        return digest.decode("utf-8")

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a stored bcrypt hash.

        A malformed stored hash yields ``False`` rather than raising, so a
        corrupt record can never crash the login flow.
        """
        try:
            return bcrypt.checkpw(
                self._encode(plain_password), hashed_password.encode("utf-8")
            )
        except (ValueError, TypeError):
            return False
