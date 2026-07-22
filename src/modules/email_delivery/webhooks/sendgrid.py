"""Inbound webhook parser for SendGrid Inbound Parse.

SendGrid's Inbound Parse webhook POSTs a supplier reply to
``POST /webhooks/inbound`` as ``multipart/form-data`` once the MX record for
``SENDGRID_OUTBOUND_DOMAIN`` points at ``mx.sendgrid.net`` and the domain is
configured under *Settings → Inbound Parse*.

Unlike EngageLab's nested envelope, SendGrid delivers a **flat** form whose
fields map almost directly onto :class:`InboundEmail`:

.. code-block:: text

    from        "Supplier <supplier@acme.com>"
    to          "OliverBennett.8ddfd168 <OliverBennett.8ddfd168@mail.example.com>"
    subject     "Re: Request for Quotation"
    text        "<plain-text body>"
    html        "<html body>"
    envelope    {"to":["...@mail.example.com"],"from":"supplier@acme.com"}
    dkim        {@acme.com : pass}
    SPF         pass
    spam_score  0.1                      # only when spam checking is enabled
    attachments 2                        # count of file parts
    attachment-info  {"attachment1": {"filename": "quote.pdf", "type": "application/pdf"}}
    attachment1 <uploaded file>
    attachment2 <uploaded file>

The Inbound Parse route is secured by an unguessable URL (there is no HMAC on
the inbound POST), so the default trusted :meth:`verify_signature` is inherited.
"""

from __future__ import annotations

import json
from email.utils import parseaddr
from typing import Any

from fastapi import Request
from starlette.datastructures import UploadFile

from src.modules.email_delivery.exceptions import WebhookParseError
from src.modules.email_delivery.webhooks.base import (
    InboundEmail,
    RawAttachment,
    WebhookParserMaster,
    logger,
)


class SendGridWebhookParser(WebhookParserMaster):
    """Parse SendGrid Inbound Parse payloads (``multipart/form-data``).

    Inherits attachment persistence and the default (trusted) signature check
    from :class:`WebhookParserMaster` — SendGrid's Inbound Parse route is
    secured by an unguessable URL, not by an HMAC signature.
    """

    @property
    def provider_name(self) -> str:
        """Return the provider key ``"sendgrid"``."""
        return "sendgrid"

    async def parse(self, request: Request) -> InboundEmail:
        """Convert a SendGrid Inbound Parse POST into a normalised inbound email.

        Args:
            request: The FastAPI request for the inbound POST.

        Returns:
            The normalised :class:`InboundEmail` with ``provider="sendgrid"``.

        Raises:
            WebhookParseError: If the content type is unsupported or the body
                cannot be read.
        """
        content_type = request.headers.get("content-type", "")
        if (
            "multipart/form-data" not in content_type
            and "application/x-www-form-urlencoded" not in content_type
        ):
            logger.error("Unsupported content type for SendGrid inbound: %s", content_type)
            raise WebhookParseError(
                f"Unsupported content type for SendGrid inbound: {content_type}"
            )

        try:
            form = await request.form()
        except Exception as exc:  # noqa: BLE001 - normalise to one type
            logger.error("Could not read SendGrid form body: %s", exc)
            raise WebhookParseError(f"Could not read SendGrid form body: {exc}") from exc

        try:
            spam_score = float(str(form.get("spam_score") or 0))
        except (TypeError, ValueError):
            spam_score = 0.0

        to_addr = self._clean_address(str(form.get("to") or "")) or self._envelope_to(form)

        inbound = InboundEmail(
            from_email=self._clean_address(str(form.get("from") or "")),
            to_email=to_addr,
            subject=str(form.get("subject") or ""),
            body_text=str(form.get("text") or ""),
            body_html=str(form.get("html") or ""),
            spam_score=spam_score,
            dkim=str(form.get("dkim") or ""),
            spf=str(form.get("SPF") or form.get("spf") or ""),
            provider=self.provider_name,
        )
        inbound.attachments = await self._extract_attachments(form)

        logger.info(
            "Parsed SendGrid inbound: %s -> %s (%d attachment(s))",
            inbound.from_email,
            inbound.to_email,
            len(inbound.attachments),
        )
        return inbound

    @staticmethod
    def _clean_address(value: str) -> str:
        """Reduce a ``"Name <email>"`` value to the bare email address."""
        if not value:
            return ""
        _, addr = parseaddr(value)
        return addr or value

    def _envelope_to(self, form: Any) -> str:
        """Recover the recipient from the ``envelope`` JSON when ``to`` is blank.

        SendGrid's ``envelope`` field carries the SMTP-level recipients as
        ``{"to": ["addr@domain", ...], "from": "..."}``; its first entry is the
        dynamic conversation address the message was delivered to.
        """
        raw = form.get("envelope")
        if not raw:
            return ""
        try:
            envelope = json.loads(raw)
        except (TypeError, ValueError):
            return ""
        recipients = envelope.get("to") if isinstance(envelope, dict) else None
        if isinstance(recipients, list) and recipients:
            return self._clean_address(str(recipients[0]))
        return ""

    async def _extract_attachments(self, form: Any) -> list[RawAttachment]:
        """Read the uploaded ``attachmentN`` file parts into memory.

        SendGrid names each file part ``attachment1``, ``attachment2``, … and
        reports the count in ``attachments``; per-file metadata (filename, MIME
        type) is in the ``attachment-info`` JSON but the ``UploadFile`` itself
        already carries both, so it is the primary source.

        Args:
            form: The parsed multipart form.

        Returns:
            One entry per readable file part; empty when none were sent.
        """
        try:
            count = int(form.get("attachments") or 0)
        except (TypeError, ValueError):
            count = 0

        info: dict[str, Any] = {}
        raw_info = form.get("attachment-info")
        if raw_info:
            try:
                info = json.loads(raw_info) or {}
            except (TypeError, ValueError):
                logger.debug("SendGrid attachment-info is not valid JSON")

        attachments: list[RawAttachment] = []
        # Iterate by the reported count, but also tolerate a missing/zero count
        # by scanning the form keys directly.
        keys = [f"attachment{i}" for i in range(1, count + 1)] or [
            key for key in form.keys() if key.startswith("attachment") and key[10:].isdigit()
        ]
        for key in keys:
            part = form.get(key)
            if not isinstance(part, UploadFile):
                continue
            meta = info.get(key, {}) if isinstance(info, dict) else {}
            filename = part.filename or meta.get("filename") or f"{key}"
            content_type = (
                part.content_type or meta.get("type") or "application/octet-stream"
            )
            content = await part.read()
            if isinstance(content, bytes) and content:
                attachments.append(RawAttachment(filename, content_type, content))
        return attachments
