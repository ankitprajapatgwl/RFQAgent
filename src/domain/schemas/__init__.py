"""Pydantic contracts (schemas) for the authentication feature.

These models are the typed input/output contracts of the API layer. Following
the "contract-first" rule (file ``04``, §3.1), every value crossing the HTTP
boundary is validated against one of these models rather than a loose ``dict``.
"""

from src.domain.schemas.auth_schema import LoginRequest, TokenPayload, TokenResponse
from src.domain.schemas.user_schema import UserCreate, UserRead

__all__ = [
    "LoginRequest",
    "TokenPayload",
    "TokenResponse",
    "UserCreate",
    "UserRead",
]
