"""FastAPI application factory.

:func:`create_app` builds and configures the ASGI application. Using a factory
(rather than a module-level ``app``) keeps construction explicit and makes it
trivial to spin up isolated instances in tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.routes import auth, pages
from src.api.templating import STATIC_DIR
from src.config import Settings, get_settings
from src.integrations import get_database
from src.observability import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: ensure the database schema exists on startup.

    Args:
        app: The FastAPI application (unused but required by the protocol).

    Yields:
        Control back to the running application.
    """
    logger.info("Starting up — ensuring database schema.")
    get_database().create_all()
    yield
    logger.info("Shutting down.")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override, primarily for tests. Defaults to
            the process-wide cached settings.

    Returns:
        A fully configured :class:`~fastapi.FastAPI` instance.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Authentication service for the RFQ Agent platform.",
        lifespan=_lifespan,
    )

    # Static assets (CSS) for the HTML pages.
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # JSON API first, then the HTML page routes.
    app.include_router(auth.router)
    app.include_router(pages.router)

    @app.get("/health", tags=["system"], summary="Liveness/readiness probe")
    def health() -> dict[str, str]:
        """Return a simple health payload for container/orchestrator probes."""
        return {"status": "ok", "environment": settings.environment}

    logger.info("Application '%s' configured (env=%s).", settings.app_name, settings.environment)
    return app


# Module-level ASGI app for `uvicorn src.api.main:app`.
app = create_app()
