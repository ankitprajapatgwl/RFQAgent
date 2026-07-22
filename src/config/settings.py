"""Application settings sourced from environment variables.

All configuration (database URL, JWT secret, token lifetimes, server host/port)
is centralised here via ``pydantic-settings``. No other module reads
``os.environ`` directly — this keeps configuration typed, validated, and
discoverable in exactly one place, as required by the coding standards
(file ``04``, rule 2.5 "No hardcoded secrets").
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
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
        anthropic_api_key: API key for the Anthropic SDK, used to generate
            sample email-drafting queries. MUST be overridden via the
            environment; never hardcode a real key.
        llm_model: Anthropic model id used for sample-query generation.
            Defaults to Haiku — cheap and fast, appropriate for short-form
            structured sample data rather than final customer-facing content.
        llm_timeout_seconds: Timeout applied to every LLM call.
        llm_max_retries: Maximum retry attempts for a failed LLM call, with
            exponential backoff between attempts.
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

    anthropic_api_key: str = Field(
        default="",
        description="API key for the Anthropic SDK (sample-query generation).",
    )
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3

    # ── Email delivery (outbound send + inbound webhook) ────────────────
    # The single active email provider: which provider transmits outbound
    # sends AND whose inbound-webhook payload ``/webhooks/inbound`` parses.
    # Switch providers by setting ``EMAIL_PROVIDER`` in the environment — e.g.
    # ``EMAIL_PROVIDER=sendgrid`` — with no code change; each provider is one
    # ``EmailMaster``/``WebhookParserMaster`` subclass plus a registry line (see
    # ``src.modules.email_delivery.providers.factory`` /
    # ``...webhooks.factory``). ``INBOUND_EMAIL_PROVIDER`` is accepted as a
    # legacy alias so existing ``.env`` files keep working.
    email_provider: str = Field(
        default="engagelab",
        validation_alias=AliasChoices("email_provider", "inbound_email_provider"),
        description="Active email provider key, e.g. 'engagelab' or 'sendgrid'.",
    )
    # Inbound emails scoring above this SpamAssassin-style threshold are
    # discarded before being matched to a conversation.
    email_spam_threshold: float = 5.0
    # (connect, read) timeout in seconds applied to every provider HTTP call.
    email_connect_timeout_seconds: float = 10.0
    email_read_timeout_seconds: float = 30.0

    # Per-provider credentials follow the ``{provider}_outbound_domain`` /
    # ``{provider}_company_name`` naming convention read generically by
    # :meth:`provider_outbound_domain` / :meth:`provider_company_name`, so a
    # new provider needs only its own fields here plus a factory registration.
    # Every field is optional so the app boots without email configured; the
    # provider's own construction raises a clear error the first time a send is
    # actually attempted with a required value missing (see EmailMaster._require).

    # ── EngageLab credentials (provider key ``engagelab``) ──────────────
    engagelab_api_user: str = Field(
        default="", description="EngageLab dashboard API_USER (Trigger Email type)."
    )
    engagelab_api_key: str = Field(
        default="", description="EngageLab API_KEY for the configured API_USER."
    )
    engagelab_api_base: str = Field(
        default="https://email.api.engagelab.cc",
        description="EngageLab REST base URL (Singapore default; Turkey: "
        "https://emailapi-tr.engagelab.com).",
    )
    engagelab_outbound_domain: str = Field(
        default="",
        description="Verified EngageLab sending subdomain; also the inbound MX target.",
    )
    engagelab_company_name: str = Field(
        default="Your Company",
        description="From-header display name and email signature for EngageLab sends.",
    )

    # ── SendGrid credentials (provider key ``sendgrid``) ────────────────
    sendgrid_api_key: str = Field(
        default="", description="SendGrid API key (Settings → API Keys, 'Mail Send' scope)."
    )
    sendgrid_api_base: str = Field(
        default="https://api.sendgrid.com",
        description="SendGrid REST base URL (the v3 Mail Send API lives under it).",
    )
    sendgrid_outbound_domain: str = Field(
        default="",
        description="Authenticated SendGrid sending domain; also the Inbound Parse host.",
    )
    sendgrid_company_name: str = Field(
        default="Your Company",
        description="From-header display name and email signature for SendGrid sends.",
    )

    @property
    def is_sqlite(self) -> bool:
        """Return ``True`` when the configured database is SQLite."""
        return self.database_url.startswith("sqlite")

    @property
    def attachments_dir(self) -> Path:
        """Directory where inbound email attachments are persisted.

        Anchored at the project root so the location is independent of the
        shell working directory the server was launched from. Served to the
        browser under :attr:`attachments_url_path`.
        """
        return PROJECT_ROOT / "data" / "attachments"

    # URL path the attachments directory is mounted under (see
    # ``src.api.main.create_app``). Kept as a single constant so persisted
    # attachment URLs and the static mount can never drift apart.
    attachments_url_path: str = "/attachments"

    def provider_outbound_domain(self, provider_name: str) -> str:
        """Return the sending domain configured for ``provider_name``.

        Read generically off the ``{provider}_outbound_domain`` field so a
        new provider needs no change here — just its own settings field and a
        factory registration. Used to build both the per-conversation dynamic
        Reply-To address and the From address.

        Args:
            provider_name: Provider key, e.g. ``"engagelab"``.

        Returns:
            The configured domain, or ``""`` if unset/unknown.
        """
        return str(getattr(self, f"{provider_name.strip().lower()}_outbound_domain", "") or "")

    def provider_company_name(self, provider_name: str) -> str:
        """Return the From-header display name configured for ``provider_name``.

        Args:
            provider_name: Provider key, e.g. ``"engagelab"``.

        Returns:
            The configured display name, or ``"Your Company"`` if unset/unknown.
        """
        value = getattr(self, f"{provider_name.strip().lower()}_company_name", "") or ""
        return str(value) or "Your Company"

    @property
    def default_outbound_domain(self) -> str:
        """Best-effort sending domain for contexts with no provider chosen yet.

        Registration assigns each user a permanent ``sending_email`` on this
        domain before any provider is picked on a send form. Resolves the
        active provider's outbound domain.

        Returns:
            The configured domain, or ``""`` if none is set.
        """
        return self.provider_outbound_domain(self.email_provider)


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
