"""Inbound webhook parsers — normalise each provider's payload for the service.

base.py       -- WebhookParserMaster abstract base + InboundEmail / RawAttachment
engagelab.py  -- EngageLabWebhookParser (verified nested payload shape)
factory.py    -- WebhookParserFactory: provider key -> parser subclass
"""

from src.modules.email_delivery.webhooks.base import (
    InboundEmail,
    RawAttachment,
    WebhookParserMaster,
)
from src.modules.email_delivery.webhooks.factory import WebhookParserFactory

__all__ = [
    "InboundEmail",
    "RawAttachment",
    "WebhookParserFactory",
    "WebhookParserMaster",
]
