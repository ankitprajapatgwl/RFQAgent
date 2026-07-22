"""JWT access-token creation and verification.

:class:`TokenService` wraps PyJWT so token concerns (signing, expiry, decoding)
live in one place. It depends only on primitives from :mod:`src.config`,
keeping it pure and unit-testable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import ValidationError

from src.config import Settings
from src.modules.auth.exceptions import InvalidTokenError
from src.modules.auth.schemas import TokenPayload


class TokenService:
    """Creates and validates signed JWT access tokens.

    Args:
        settings: Application settings supplying the secret, algorithm, and
            token lifetime.
    """

    def __init__(self, settings: Settings) -> None:
        """Capture the signing configuration from settings."""
        self._secret = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._expire_minutes = settings.access_token_expire_minutes

    @property
    def expires_in_seconds(self) -> int:
        """Access-token lifetime expressed in seconds."""
        return self._expire_minutes * 60

    def create_access_token(self, user_id: uuid.UUID, email: str) -> str:
        """Create a signed access token for a user.

        Args:
            user_id: The authenticated user's database id.
            email: The authenticated user's email address.

        Returns:
            The encoded JWT as a string.
        """
        now = datetime.now(UTC)
        expire = now + timedelta(minutes=self._expire_minutes)
        claims = {
            "sub": str(user_id),
            "email": email,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    def decode_access_token(self, token: str) -> TokenPayload:
        """Decode and validate a JWT access token.

        Args:
            token: The encoded JWT string.

        Returns:
            The validated :class:`TokenPayload`.

        Raises:
            InvalidTokenError: If the token is expired, malformed, or fails
                signature/claims validation.
        """
        try:
            raw_claims = jwt.decode(token, self._secret, algorithms=[self._algorithm])
            return TokenPayload.model_validate(raw_claims)
        except (jwt.PyJWTError, ValidationError) as exc:
            raise InvalidTokenError("Could not validate access token.") from exc
