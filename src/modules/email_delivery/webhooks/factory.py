"""Factory that builds inbound webhook parser instances.

:class:`WebhookParserFactory` maps a provider key to the matching
:class:`~src.modules.email_delivery.webhooks.base.WebhookParserMaster`
subclass so the single ``POST /webhooks/inbound`` route can decode that
provider's payload. It mirrors
:class:`~src.modules.email_delivery.providers.factory.EmailProviderFactory` on
the inbound side. EngageLab and SendGrid are registered today.
"""

from __future__ import annotations

from src.config import Settings
from src.modules.email_delivery.exceptions import ProviderConfigError
from src.modules.email_delivery.webhooks.base import WebhookParserMaster, logger
from src.modules.email_delivery.webhooks.engagelab import EngageLabWebhookParser
from src.modules.email_delivery.webhooks.sendgrid import SendGridWebhookParser

# Keep keys identical to the email-provider factory so one provider key can
# build either a send-side or receive-side instance.
_PARSERS: dict[str, type[WebhookParserMaster]] = {
    "engagelab": EngageLabWebhookParser,
    "sendgrid": SendGridWebhookParser,
}


class WebhookParserFactory:
    """Construct the configured inbound webhook parser instance.

    Stateless; exposes a single classmethod that performs the
    lookup-and-instantiate step.
    """

    @classmethod
    def create(cls, provider_name: str, settings: Settings) -> WebhookParserMaster:
        """Instantiate the parser identified by ``provider_name``.

        Args:
            provider_name: Provider key, e.g. ``"engagelab"`` (matched
                case-insensitively after trimming whitespace).
            settings: Shared application configuration passed to the parser.

        Returns:
            A fully constructed parser instance.

        Raises:
            ProviderConfigError: If ``provider_name`` is not registered (same
                error type as the email-provider factory, so callers can
                handle both uniformly).
        """
        key = (provider_name or "").strip().lower()
        parser_cls = _PARSERS.get(key)
        if parser_cls is None:
            supported = ", ".join(_PARSERS) or "(none registered)"
            raise ProviderConfigError(
                f"Unknown email provider '{provider_name}' for webhook parsing. "
                f"Supported providers: {supported}."
            )
        logger.info("Selected inbound webhook parser: %s", key)
        return parser_cls(settings)

    @classmethod
    def supported(cls) -> list[str]:
        """Return the registered parser keys, in registration order."""
        return list(_PARSERS)
