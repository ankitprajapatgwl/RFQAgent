"""Auth module — user registration, login, and session management.

Self-contained: everything needed to understand or change authentication
behavior lives in this one folder.

    enums.py           -- UserRole, TokenType
    models.py           -- User ORM model
    schemas.py          -- Pydantic request/response contracts
    exceptions.py        -- typed domain errors
    password_hasher.py    -- bcrypt hashing strategy
    token_service.py      -- JWT issue/verify
    repository.py          -- User data access
    service.py              -- AuthService (registration/login orchestration)
    deps.py                  -- FastAPI dependency wiring
    router.py                 -- JSON API (/api/v1/auth/*)
    pages.py                   -- HTML pages (/login, /register, /logout)

``api_router`` and ``pages_router`` are the two pieces the app factory mounts.
"""

from src.modules.auth.pages import router as pages_router
from src.modules.auth.router import router as api_router

__all__ = ["api_router", "pages_router"]
