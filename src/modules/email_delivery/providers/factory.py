"""Factory that builds outbound email provider instances.

:class:`EmailProviderFactory` maps a provider key to the matching
:class:`~src.modules.email_delivery.providers.base.EmailMaster` subclass and
returns a ready-to-use instance (its ``__init__`` validates that provider's
credentials, failing fast). Callers never import a concrete provider directly,
so adding one is a new subclass plus one line in :data:`_PROVIDERS` — nothing
else changes.

EngageLab and SendGrid are registered today; the registry and the
Master/Factory abstraction exist so a further provider (SendCloud, ...) can be
dropped in later without touching the service, repository or routes.
"""

from __future__ import annotations

from src.config import Settings
from src.modules.email_delivery.exceptions import ProviderConfigError
from src.modules.email_delivery.providers.base import EmailMaster, logger
from src.modules.email_delivery.providers.engagelab import EngageLabEmailProvider
from src.modules.email_delivery.providers.sendgrid import SendGridEmailProvider

# Registry mapping the lowercase provider key to its implementation class.
_PROVIDERS: dict[str, type[EmailMaster]] = {
    "engagelab": EngageLabEmailProvider,
    "sendgrid": SendGridEmailProvider,
}


class EmailProviderFactory:
    """Construct the configured email provider instance.

    Stateless; exposes a single classmethod that performs the
    lookup-and-instantiate step.
    """

    @classmethod
    def create(cls, provider_name: str, settings: Settings) -> EmailMaster:
        """Instantiate the provider identified by ``provider_name``.

        Args:
            provider_name: Provider key, e.g. ``"engagelab"`` (matched
                case-insensitively after trimming whitespace).
            settings: Shared application configuration passed to the provider.

        Returns:
            A fully constructed provider instance.

        Raises:
            ProviderConfigError: If ``provider_name`` is unknown, or that
                provider is missing required configuration.
        """
        key = (provider_name or "").strip().lower()
        provider_cls = _PROVIDERS.get(key)
        if provider_cls is None:
            supported = ", ".join(_PROVIDERS) or "(none registered)"
            raise ProviderConfigError(
                f"Unknown email provider '{provider_name}'. Supported providers: {supported}."
            )
        logger.info("Selected email provider: %s", key)
        return provider_cls(settings)

    @classmethod
    def supported(cls) -> list[str]:
        """Return the registered provider keys, in registration order."""
        return list(_PROVIDERS)
