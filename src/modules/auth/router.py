"""JSON authentication API routes.

These endpoints implement the machine-facing contract: register, login (returns
a JWT), and a protected "current user" endpoint. HTML page rendering lives in
:mod:`src.modules.auth.pages`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.modules.auth.deps import AuthServiceDep, CurrentUserDep
from src.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    SendingEmailAlreadyInUseError,
)
from src.modules.auth.schemas import (
    LoginRequest,
    SendingEmailAvailability,
    TokenResponse,
    UserCreate,
    UserRead,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(payload: UserCreate, auth_service: AuthServiceDep) -> UserRead:
    """Create a new user account.

    Args:
        payload: Registration data (email, full name, password).
        auth_service: Injected authentication service.

    Returns:
        The created user's public profile.

    Raises:
        HTTPException: ``409`` if the email is already registered.
    """
    try:
        user = auth_service.register(payload)
    except (EmailAlreadyRegisteredError, SendingEmailAlreadyInUseError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserRead.model_validate(user)


@router.get(
    "/sending-email/availability",
    response_model=SendingEmailAvailability,
    summary="Check whether an outbound sending address is free (registration helper)",
)
def check_sending_email_availability(
    auth_service: AuthServiceDep,
    email: str | None = None,
    sending_email: str | None = None,
) -> SendingEmailAvailability:
    """Resolve and check a candidate ``sending_email`` for the register form.

    Unauthenticated — the registration page calls it before an account exists.
    Pass ``email`` (the login email) to get the default suggestion, and/or
    ``sending_email`` when the user has edited the address; the ``sending_email``
    value wins as the source of the local part. Either way the address is
    re-anchored to the configured outbound domain before the uniqueness check.

    Args:
        auth_service: Injected authentication service.
        email: The user's login email (source of the default local part).
        sending_email: The user's edited address, if any.

    Returns:
        The resolved address, whether it is available, and whether an outbound
        domain is configured at all.
    """
    source = sending_email or email or ""
    resolved = auth_service.suggest_sending_email(source) if source else None
    if resolved is None:
        # No outbound domain configured (or nothing to resolve) — the feature
        # is simply off; report "available" so the form never blocks.
        return SendingEmailAvailability(sending_email=None, available=True, configured=False)
    return SendingEmailAvailability(
        sending_email=resolved,
        available=auth_service.is_sending_email_available(resolved),
        configured=True,
    )


@router.post("/login", response_model=TokenResponse, summary="Authenticate and get a JWT")
def login(payload: LoginRequest, auth_service: AuthServiceDep) -> TokenResponse:
    """Authenticate a user and return a signed access token.

    Args:
        payload: Login credentials (email, password).
        auth_service: Injected authentication service.

    Returns:
        A bearer token response.

    Raises:
        HTTPException: ``401`` for bad credentials, ``403`` for inactive users.
    """
    try:
        _, token = auth_service.login(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return token


@router.get("/me", response_model=UserRead, summary="Get the current authenticated user")
def read_current_user(current_user: CurrentUserDep) -> UserRead:
    """Return the profile of the user identified by the bearer token.

    Args:
        current_user: The user resolved from the ``Authorization`` header.

    Returns:
        The authenticated user's public profile.
    """
    return UserRead.model_validate(current_user)
