"""Pydantic contracts (schemas) for the auth module.

Every value crossing the HTTP boundary is validated against one of these
models rather than a loose ``dict`` — the "contract-first" rule from the
coding standards (file ``04``, §3.1).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.modules.auth.enums import UserRole

# Bcrypt only considers the first 72 bytes of a password; capping the length
# here keeps validation honest and avoids silent truncation surprises.
_PASSWORD_MIN = 8
_PASSWORD_MAX = 72


class UserCreate(BaseModel):
    """Input contract for registering a new user.

    Attributes:
        email: Unique email address used as the login identifier.
        full_name: Display name of the user.
        password: Plaintext password (validated for length, never stored).
    """

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class UserRead(BaseModel):
    """Output contract exposing safe, non-sensitive user fields.

    The hashed password is deliberately excluded so it can never leak through
    an API response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    """Input contract for a JSON login request.

    Attributes:
        email: The account's email address.
        password: The account's plaintext password.
    """

    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """Output contract returned after a successful authentication.

    Attributes:
        access_token: Signed JWT access token.
        token_type: OAuth2 token type; always ``bearer``.
        expires_in: Token lifetime in seconds.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """Decoded JWT claims relevant to the application.

    Attributes:
        sub: Subject — the user's id as a string (JWT ``sub`` is a string claim).
        email: The authenticated user's email address.
        exp: Expiry as a POSIX timestamp.
    """

    sub: str
    email: EmailStr
    exp: int
