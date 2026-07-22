"""Pydantic schemas describing user input and output contracts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.domain.enums import UserRole

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
