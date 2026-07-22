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
        phone_number: Optional contact phone number (never verified); shown in
            the "Best regards" sign-off of outbound emails.
        sending_email: The outbound address the user confirmed at registration.
            Only its local part is honoured — the service always re-anchors it
            to the configured outbound domain. ``None`` lets the service derive
            one from the email's local part.
    """

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    phone_number: str | None = Field(default=None, max_length=32)
    sending_email: str | None = Field(default=None, max_length=320)


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
    phone_number: str | None = None
    sending_email: str | None = None
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


class SendingEmailAvailability(BaseModel):
    """Output contract for the sending-email availability check.

    Backs the registration form's live "is this address free?" hint and the
    suggestion it prefills. ``available`` is ``False`` when the address is
    already taken by another user.

    Attributes:
        sending_email: The fully qualified address that was checked (local part
            re-anchored to the configured outbound domain).
        available: Whether the address is free to claim.
        configured: Whether an outbound domain is configured at all; when
            ``False`` the app runs without per-user sending addresses.
    """

    sending_email: str | None
    available: bool
    configured: bool
