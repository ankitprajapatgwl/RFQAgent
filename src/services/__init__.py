"""Services layer — business logic and pure, framework-agnostic components.

Nothing here imports FastAPI. Each class does one job (single-responsibility)
and is unit-testable in isolation:

* :class:`~src.services.password_hasher.PasswordHasher` — hashing strategy.
* :class:`~src.services.token_service.TokenService` — JWT encode/decode.
* :class:`~src.services.user_repository.UserRepository` — data access.
* :class:`~src.services.auth_service.AuthService` — orchestration.
"""

from src.services.auth_service import AuthService
from src.services.exceptions import (
    AuthError,
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from src.services.password_hasher import BcryptPasswordHasher, PasswordHasher
from src.services.token_service import TokenService
from src.services.user_repository import UserRepository

__all__ = [
    "AuthError",
    "AuthService",
    "BcryptPasswordHasher",
    "EmailAlreadyRegisteredError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "InvalidTokenError",
    "PasswordHasher",
    "TokenService",
    "UserRepository",
]
