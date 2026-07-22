"""Outbound email providers — the Strategy + Factory layer for sending.

base.py       -- EmailMaster abstract base: address scheme + content templates
engagelab.py  -- EngageLabEmailProvider (provider key "engagelab")
sendgrid.py   -- SendGridEmailProvider (provider key "sendgrid")
factory.py    -- EmailProviderFactory: provider key -> EmailMaster subclass
"""

from src.modules.email_delivery.providers.base import EmailMaster
from src.modules.email_delivery.providers.factory import EmailProviderFactory

__all__ = ["EmailMaster", "EmailProviderFactory"]
