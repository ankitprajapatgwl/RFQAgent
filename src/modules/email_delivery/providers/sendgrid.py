"""Outbound email provider backed by the SendGrid v3 Mail Send API.

:class:`SendGridEmailProvider` implements :meth:`EmailMaster.send_email` by
POSTing JSON to SendGrid's ``/v3/mail/send`` endpoint with :mod:`httpx`
(SendGrid ships a Python SDK, but a direct HTTP call keeps this provider's
dependency surface identical to EngageLab's and avoids an extra package).
Authentication is a Bearer token: the API key created under
*Settings → API Keys* with the *Mail Send* scope.

Because ``SENDGRID_OUTBOUND_DOMAIN`` is an authenticated sending domain, the
local-part of the ``from``/``reply_to`` addresses can be defined dynamically at
send time with no per-address pre-registration — the same dynamic Reply-To
scheme EngageLab uses, so replies still thread back to their conversation.

Configuration consumed (see :class:`src.config.Settings`):

- ``SENDGRID_API_KEY`` *(required)* — API key with the *Mail Send* scope.
- ``SENDGRID_API_BASE`` — REST base URL (``https://api.sendgrid.com`` default).
- ``SENDGRID_OUTBOUND_DOMAIN`` *(required)* — the authenticated sending domain.
- ``SENDGRID_COMPANY_NAME`` — From-header display name (default ``"Your Company"``).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from src.config import Settings
from src.modules.email_delivery.exceptions import EmailSendError
from src.modules.email_delivery.providers.base import EmailMaster, logger


class SendGridEmailProvider(EmailMaster):
    """Send RFQ/draft emails through the SendGrid v3 Mail Send API.

    Inherits all address and template helpers from :class:`EmailMaster` and
    adds SendGrid-specific transmission via :mod:`httpx`.

    Args:
        settings: Shared application configuration.

    Raises:
        ProviderConfigError: If ``SENDGRID_OUTBOUND_DOMAIN`` or
            ``SENDGRID_API_KEY`` is not set.
    """

    def __init__(self, settings: Settings) -> None:
        """Validate credentials and pre-build the send endpoint URL."""
        super().__init__(settings)
        self.api_key = self._require(settings.sendgrid_api_key, "SENDGRID_API_KEY")
        self.send_url = f"{settings.sendgrid_api_base.rstrip('/')}/v3/mail/send"
        self._timeout = httpx.Timeout(
            connect=settings.email_connect_timeout_seconds,
            read=settings.email_read_timeout_seconds,
            write=settings.email_read_timeout_seconds,
            pool=settings.email_connect_timeout_seconds,
        )
        logger.info("SendGrid provider initialised")

    @property
    def provider_name(self) -> str:
        """Return the provider key ``"sendgrid"``."""
        return "sendgrid"

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
        text_body: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send one email via ``POST {base}/v3/mail/send`` (JSON, Bearer auth).

        The payload follows SendGrid's v3 shape: recipients live under
        ``personalizations``, and ``content`` is an array whose entries must be
        ordered by increasing precedence (``text/plain`` before ``text/html``).

        Deliverability hardening (mirrors the EngageLab provider — why a draft
        could 200 yet never arrive):

        * ``subject`` and ``from_name`` are collapsed to a single safe line — a
          stray newline in an LLM-drafted subject is a header-injection.
        * A ``text/plain`` part always accompanies the HTML (derived from it
          when not supplied) — HTML-only mail is far more likely to be
          spam-filtered.
        * ``to`` carries the recipient's display name when known.

        Args:
            from_email: Dynamic sender address (suffix must match the
                authenticated ``SENDGRID_OUTBOUND_DOMAIN``).
            from_name: Display name for the ``from`` header.
            to_email: Recipient address.
            to_name: Recipient display name; included when non-empty.
            subject: Subject line.
            html_body: HTML body.
            reply_to: Dynamic conversation address sent as ``reply_to``.
            text_body: Optional plain-text alternative; derived from
                ``html_body`` when omitted.
            attachments: Optional attachments, each base64-encoded into the
                ``attachments`` array.

        Returns:
            ``{"status_code": int, "provider": "sendgrid",
            "provider_message_id": str | None}``.

        Raises:
            EmailSendError: On a network error or a non-2xx status.
        """
        clean_subject = self.sanitize_header(subject)
        clean_from_name = self.sanitize_header(from_name)
        clean_to_name = self.sanitize_header(to_name)
        text_content = text_body if text_body is not None else self.html_to_text(html_body)

        recipient: dict[str, str] = {"email": to_email}
        if clean_to_name:
            recipient["name"] = clean_to_name

        from_field: dict[str, str] = {"email": from_email}
        if clean_from_name:
            from_field["name"] = clean_from_name

        # SendGrid requires content parts ordered by increasing precedence:
        # the plain-text alternative must come before the HTML part.
        payload: dict[str, Any] = {
            "personalizations": [{"to": [recipient], "subject": clean_subject}],
            "from": from_field,
            "reply_to": {"email": reply_to},
            "subject": clean_subject,
            "content": [
                {"type": "text/plain", "value": text_content},
                {"type": "text/html", "value": html_body},
            ],
        }
        if attachments:
            payload["attachments"] = [
                {
                    "filename": att["filename"],
                    "type": att.get("content_type", "application/octet-stream"),
                    "content": base64.b64encode(att["content"]).decode("ascii"),
                    "disposition": "attachment",
                }
                for att in attachments
            ]

        try:
            response = httpx.post(
                self.send_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            logger.error("SendGrid request error: %s", exc)
            raise EmailSendError(
                f"SendGrid network error sending to {to_email}: {exc}"
            ) from exc

        if not 200 <= response.status_code < 300:
            logger.error(
                "SendGrid rejected send (status=%s): %s",
                response.status_code,
                response.text[:300],
            )
            raise EmailSendError(
                f"SendGrid rejected email to {to_email} "
                f"(status {response.status_code}): {response.text[:200]}"
            )

        # A successful send is a 202 with an empty body; the id is a header.
        message_id = response.headers.get("X-Message-Id") or response.headers.get(
            "x-message-id"
        )

        logger.info("SendGrid accepted email to %s (status=%s)", to_email, response.status_code)
        return {
            "status_code": response.status_code,
            "provider": self.provider_name,
            "provider_message_id": message_id,
        }
