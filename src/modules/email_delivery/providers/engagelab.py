"""Outbound email provider backed by the EngageLab Email API.

:class:`EngageLabEmailProvider` implements :meth:`EmailMaster.send_email` by
POSTing JSON to EngageLab's ``/v1/mail/send`` endpoint with :mod:`httpx`
(EngageLab ships no first-party Python SDK). Authentication is HTTP Basic Auth
using ``api_user``/``api_key`` (a dashboard-created API_USER of type *Trigger
Email* — **not** the EngageLab login email).

Because ``ENGAGELAB_OUTBOUND_DOMAIN`` is a fully authenticated subdomain, the
local-part of the ``from``/``reply_to`` addresses can be defined dynamically
at send time with no per-address pre-registration.

Configuration consumed (see :class:`src.config.Settings`):

- ``ENGAGELAB_API_USER`` *(required)* — API_USER bound to the sending subdomain.
- ``ENGAGELAB_API_KEY`` *(required)* — API_KEY for that API_USER.
- ``ENGAGELAB_API_BASE`` — region base URL (Singapore by default).
- ``ENGAGELAB_OUTBOUND_DOMAIN`` *(required)* — the verified sending subdomain.
- ``ENGAGELAB_COMPANY_NAME`` — From-header display name (default ``"Your Company"``).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from src.config import Settings
from src.modules.email_delivery.exceptions import EmailSendError
from src.modules.email_delivery.providers.base import EmailMaster, logger

# ``0`` selects individual transactional sending (vs. batch) per EngageLab's
# Trigger Email API.
_SEND_MODE_TRANSACTIONAL = 0


class EngageLabEmailProvider(EmailMaster):
    """Send RFQ/draft emails through the EngageLab Trigger Email API.

    Inherits all address and template helpers from :class:`EmailMaster` and
    adds EngageLab-specific transmission via :mod:`httpx`.

    Args:
        settings: Shared application configuration.

    Raises:
        ProviderConfigError: If ``ENGAGELAB_OUTBOUND_DOMAIN``,
            ``ENGAGELAB_API_USER`` or ``ENGAGELAB_API_KEY`` is not set.
    """

    def __init__(self, settings: Settings) -> None:
        """Validate credentials and pre-build the send endpoint URL."""
        super().__init__(settings)
        self.api_user = self._require(settings.engagelab_api_user, "ENGAGELAB_API_USER")
        self.api_key = self._require(settings.engagelab_api_key, "ENGAGELAB_API_KEY")
        self.send_url = f"{settings.engagelab_api_base.rstrip('/')}/v1/mail/send"
        self._timeout = httpx.Timeout(
            connect=settings.email_connect_timeout_seconds,
            read=settings.email_read_timeout_seconds,
            write=settings.email_read_timeout_seconds,
            pool=settings.email_connect_timeout_seconds,
        )
        logger.info("EngageLab provider initialised")

    @property
    def provider_name(self) -> str:
        """Return the provider key ``"engagelab"``."""
        return "engagelab"

    def send_email(
        self,
        *,
        from_email: str,
        from_name: str,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        reply_to: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send one email via ``POST {base}/v1/mail/send`` (JSON, Basic Auth).

        ``subject``/``content``/``reply_to``/``attachments``/``settings`` all
        nest inside ``body`` — EngageLab returns ``404`` if they are sent flat.

        Args:
            from_email: Dynamic sender address (suffix must match the verified
                ``ENGAGELAB_OUTBOUND_DOMAIN``).
            from_name: Display name for the ``from`` header.
            to_email: Recipient address.
            to_name: Recipient display name (accepted for interface parity).
            subject: Subject line.
            html_body: HTML body.
            reply_to: Dynamic conversation address sent as ``reply_to``.
            attachments: Optional attachments, each base64-encoded into the
                ``body.attachments`` array.

        Returns:
            ``{"status_code": int, "provider": "engagelab",
            "provider_message_id": str | None}``.

        Raises:
            EmailSendError: On a network error, a non-2xx status, or an
                unparseable response body.
        """
        mail_body: dict[str, Any] = {
            "reply_to": [reply_to],
            "subject": subject,
            "content": {"html": html_body},
            "settings": {
                "send_mode": _SEND_MODE_TRANSACTIONAL,
                "return_email_id": True,
            },
        }
        if attachments:
            mail_body["attachments"] = [
                {
                    "filename": att["filename"],
                    "type": att.get("content_type", "application/octet-stream"),
                    "content": base64.b64encode(att["content"]).decode("ascii"),
                    "disposition": "attachment",
                }
                for att in attachments
            ]

        payload = {
            "from": f"{from_name} <{from_email}>",
            "to": [to_email],
            "body": mail_body,
        }

        try:
            response = httpx.post(
                self.send_url,
                json=payload,
                auth=(self.api_user, self.api_key),
                headers={"Accept": "application/json"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            logger.error("EngageLab request error: %s", exc)
            raise EmailSendError(
                f"EngageLab network error sending to {to_email}: {exc}"
            ) from exc

        if not 200 <= response.status_code < 300:
            logger.error(
                "EngageLab rejected send (status=%s): %s",
                response.status_code,
                response.text[:300],
            )
            raise EmailSendError(
                f"EngageLab rejected email to {to_email} "
                f"(status {response.status_code}): {response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError:
            logger.warning("EngageLab returned a non-JSON success body")
            body = {}

        # Individual sends return "email_ids"; address-list sends return
        # "task_id"; fall back to "request_id".
        message_id = None
        email_ids = body.get("email_ids")
        if isinstance(email_ids, list) and email_ids:
            message_id = email_ids[0]
        elif body.get("task_id"):
            message_id = body["task_id"]
        elif body.get("request_id"):
            message_id = body["request_id"]

        logger.info("EngageLab accepted email to %s (status=%s)", to_email, response.status_code)
        return {
            "status_code": response.status_code,
            "provider": self.provider_name,
            "provider_message_id": message_id,
        }
