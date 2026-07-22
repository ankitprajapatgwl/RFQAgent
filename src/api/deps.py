"""Shared FastAPI dependencies.

Dependency-injection wiring lives here so routes stay declarative. Each request
gets a fresh database session and an :class:`~src.services.auth_service.AuthService`
composed from cached, stateless collaborators.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.config import Settings, get_settings
from src.domain.models import User
from src.integrations import get_database
from src.services import (
    AuthService,
    BcryptPasswordHasher,
    InvalidTokenError,
    PasswordHasher,
    TokenService,
    UserRepository,
)

# ``auto_error=False`` lets us raise our own, consistent 401 responses.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_db_session() -> Iterator[Session]:
    """Yield a request-scoped session, committing on success.

    The surrounding :meth:`Database.session` context manager commits when the
    request handler returns normally and rolls back if it raises.

    Yields:
        An active SQLAlchemy :class:`~sqlalchemy.orm.Session`.
    """
    with get_database().session() as session:
        yield session


@lru_cache(maxsize=1)
def get_password_hasher() -> PasswordHasher:
    """Return the shared password-hashing strategy (bcrypt)."""
    return BcryptPasswordHasher()


@lru_cache(maxsize=1)
def get_token_service() -> TokenService:
    """Return the shared JWT token service."""
    return TokenService(get_settings())


def get_auth_service(
    session: Annotated[Session, Depends(get_db_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AuthService:
    """Compose an :class:`AuthService` for the current request.

    Args:
        session: Request-scoped database session.
        hasher: Shared password hasher.
        tokens: Shared token service.

    Returns:
        A fully wired :class:`AuthService`.
    """
    return AuthService(UserRepository(session), hasher, tokens)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_current_user(
    auth_service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> User:
    """Resolve the authenticated user from a ``Bearer`` token (JSON API).

    Args:
        auth_service: The request's auth service.
        credentials: Parsed ``Authorization`` header credentials, if present.

    Returns:
        The authenticated :class:`User`.

    Raises:
        HTTPException: ``401`` if the token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return auth_service.resolve_user_from_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_optional_user_from_cookie(
    request: Request,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
) -> User | None:
    """Resolve the current user from the session cookie for HTML pages.

    Unlike :func:`get_current_user`, a missing or invalid cookie returns
    ``None`` instead of raising, so page routes can redirect to the login page.

    Args:
        request: The incoming request (source of cookies).
        auth_service: The request's auth service.
        settings: Application settings (cookie name).

    Returns:
        The authenticated :class:`User`, or ``None`` if not signed in.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        return auth_service.resolve_user_from_token(token)
    except InvalidTokenError:
        return None


CurrentUserDep = Annotated[User, Depends(get_current_user)]
OptionalCookieUserDep = Annotated["User | None", Depends(get_optional_user_from_cookie)]
