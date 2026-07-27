"""The protected dashboard shell.

Composes the auth module (who's signed in) into the app's single-page
dashboard — sidebar navigation, top-right profile menu, and a "Generate
Email" panel. This lives at the app level, not inside any one module,
because it depends on more than one.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from src.api.templating import templates
from src.modules.auth.deps import OptionalCookieUserDep

router = APIRouter(tags=["dashboard"], include_in_schema=False)


@router.get("/", include_in_schema=False)
def index(current_user: OptionalCookieUserDep) -> RedirectResponse:
    """Send signed-in users to the dashboard and everyone else to login."""
    target = "/dashboard" if current_user is not None else "/login"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse, response_model=None)
def dashboard_page(
    request: Request, current_user: OptionalCookieUserDep
) -> HTMLResponse | RedirectResponse:
    """Render the protected dashboard, redirecting anonymous visitors to login."""
    if current_user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "dashboard.html", {"user": current_user})
