"""Application settings sourced from environment variables.

All configuration (database URL, JWT secret, token lifetimes, server host/port)
is centralised here via ``pydantic-settings``. No other module reads
``os.environ`` directly — this keeps configuration typed, validated, and
discoverable in exactly one place, as required by the coding standards
(file ``04``, rule 2.5 "No hardcoded secrets").
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: ``src/config/settings.py`` -> up two parents (config -> src -> root).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed, validated application configuration.

    Attributes are populated from environment variables (case-insensitive) or a
    local ``.env`` file. Every field carries a sensible, non-secret default so
    the app boots in development without extra setup, while production overrides
    them through the environment.

    Attributes:
        app_name: Human-readable application name used in the API metadata.
        environment: Deployment environment, e.g. ``development`` or ``production``.
        debug: When ``True`` enables verbose behaviour (auto-reload, debug logs).
        host: Interface the ASGI server binds to.
        port: TCP port the ASGI server listens on.
        database_url: SQLAlchemy connection URL. Defaults to a local SQLite file.
        jwt_secret_key: Secret used to sign JWT access tokens. MUST be overridden
            in production via the environment.
        jwt_algorithm: Signing algorithm for JWTs.
        access_token_expire_minutes: Access-token lifetime in minutes.
        session_cookie_name: Name of the cookie storing the access token for the
            HTML page flow.
        log_level: Root logging level (e.g. ``INFO``, ``DEBUG``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "RFQ Agent — Auth Service"
    environment: str = "development"
    debug: bool = True

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'data' / 'rfq_agent.db'}",
        description="SQLAlchemy database URL.",
    )

    jwt_secret_key: str = Field(
        default="change-me-in-production-please-use-a-long-random-value",
        description="Secret key used to sign JWT access tokens.",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    session_cookie_name: str = "rfq_access_token"

    log_level: str = "INFO"

    @property
    def is_sqlite(self) -> bool:
        """Return ``True`` when the configured database is SQLite."""
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide singleton ``Settings`` instance.

    The ``lru_cache`` decorator implements the singleton pattern: settings are
    read from the environment exactly once and reused for the process lifetime,
    which is both efficient and consistent across the application.

    Returns:
        The cached :class:`Settings` instance.
    """
    return Settings()
