"""Pydantic schemas for authentication requests and JWT tokens."""

from pydantic import BaseModel, EmailStr, Field


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
