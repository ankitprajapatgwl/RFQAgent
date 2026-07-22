"""Server-rendered HTML page routes for the auth module.

These routes back the browser experience: login and registration forms, and
logout. On success the login form stores the JWT in an HttpOnly cookie so
subsequent page requests are authenticated without exposing the token to
JavaScript. The protected dashboard shell lives in
:mod:`src.api.routes.dashboard` — it composes this module with others, so it
isn't owned by the auth module itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from src.api.templating import templates
from src.modules.auth.deps import AuthServiceDep, OptionalCookieUserDep, SettingsDep
from src.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
)
from src.modules.auth.schemas import UserCreate

router = APIRouter(tags=["auth-pages"], include_in_schema=False)


def _first_validation_message(error: ValidationError) -> str:
    """Return a human-friendly message from a Pydantic validation error."""
    first = error.errors()[0]
    field = str(first.get("loc", ["field"])[-1])
    return f"{field.replace('_', ' ').capitalize()}: {first.get('msg', 'invalid value')}"


def _set_session_cookie(
    response: RedirectResponse, token: str, *, cookie_name: str, max_age: int, secure: bool
) -> None:
    """Attach the access-token session cookie to a redirect response."""
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(
    request: Request, current_user: OptionalCookieUserDep
) -> HTMLResponse | RedirectResponse:
    """Render the login form, or redirect to the dashboard if already signed in."""
    if current_user is not None:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"error": None, "email": ""})


@router.post("/login", response_model=None)
def login_submit(
    request: Request,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    """Handle a login form submission.

    On success, set the session cookie and redirect to the dashboard. On
    failure, re-render the form with an error message and a ``401`` status.
    """
    try:
        _, token = auth_service.login(email, password)
    except (InvalidCredentialsError, InactiveUserError) as exc:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": str(exc), "email": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(
        response,
        token.access_token,
        cookie_name=settings.session_cookie_name,
        max_age=token.expires_in,
        secure=settings.environment == "production",
    )
    return response


@router.get("/register", response_class=HTMLResponse, response_model=None)
def register_page(
    request: Request, current_user: OptionalCookieUserDep
) -> HTMLResponse | RedirectResponse:
    """Render the registration form, or redirect if already signed in."""
    if current_user is not None:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "register.html", {"error": None, "email": "", "full_name": ""}
    )


@router.post("/register", response_model=None)
def register_submit(
    request: Request,
    auth_service: AuthServiceDep,
    full_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    """Handle a registration form submission.

    Validates the form via :class:`UserCreate`, creates the account, and
    redirects to the login page with a success flag. Validation or duplicate
    errors re-render the form with a message.
    """
    context: dict[str, object] = {"error": None, "email": email, "full_name": full_name}
    try:
        payload = UserCreate(full_name=full_name, email=email, password=password)
    except ValidationError as exc:
        context["error"] = _first_validation_message(exc)
        return templates.TemplateResponse(
            request, "register.html", context, status_code=status.HTTP_400_BAD_REQUEST
        )

    try:
        auth_service.register(payload)
    except EmailAlreadyRegisteredError as exc:
        context["error"] = str(exc)
        return templates.TemplateResponse(
            request, "register.html", context, status_code=status.HTTP_409_CONFLICT
        )

    return RedirectResponse(url="/login?registered=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(settings: SettingsDep) -> RedirectResponse:
    """Clear the session cookie and return to the login page."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=settings.session_cookie_name)
    return response
