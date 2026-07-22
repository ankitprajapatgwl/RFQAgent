"""Inbound webhook parser for EngageLab.

EngageLab's Inbound Route POSTs a supplier reply to ``POST /webhooks/inbound``
once the MX record for ``ENGAGELAB_OUTBOUND_DOMAIN`` points at EngageLab and a
webhook is bound to the sending API_USER.

A real captured payload is a nested envelope — the supplier's ``from``, the
``subject`` and both bodies live under ``response.response_data``, not at the
top level, and there is no structured ``attachments`` array (attachments are
recovered by parsing ``response_data.raw_message`` as MIME, downloading
``raw_message_url`` first if the inline copy is blank):

.. code-block:: text

    {
      "server": "email",
      "message_id": "...",
      "to": "OliverBennett.8ddfd168 <OliverBennett.8ddfd168@mail.example.com>",
      "response": {
        "event": "route",
        "response_data": {
          "headers": {...}, "raw_message": "<raw MIME>",
          "raw_message_url": "https://.../MXBODY.eml",
          "subject": "...", "from": "supplier@example.com",
          "text": "...", "html": "...",
          "x_mx_rcptto": "our-dynamic-address@mail.example.com",
          "x_mx_mailfrom": "supplier@example.com"
        }
      }
    }

The flat ``sender``/``recipient``/``from``/``to`` keys from EngageLab's setup
guide are kept only as fallbacks.
"""

from __future__ import annotations

import base64
import email
import json
from email.policy import default as email_default_policy
from email.utils import parseaddr
from typing import Any

import httpx
from fastapi import Request

from src.modules.email_delivery.exceptions import WebhookParseError
from src.modules.email_delivery.webhooks.base import (
    InboundEmail,
    RawAttachment,
    WebhookParserMaster,
    logger,
)

# Timeout (seconds) for downloading raw_message_url when the inline MIME copy
# is absent.
_RAW_MESSAGE_DOWNLOAD_TIMEOUT = 10.0


class EngageLabWebhookParser(WebhookParserMaster):
    """Parse EngageLab inbound payloads (JSON or multipart/urlencoded form).

    Inherits attachment persistence and the default (trusted) signature check
    from :class:`WebhookParserMaster` — EngageLab's inbound route is secured by
    an unguessable URL bound to a single API_USER, not by an HMAC signature.
    """

    @property
    def provider_name(self) -> str:
        """Return the provider key ``"engagelab"``."""
        return "engagelab"

    async def parse(self, request: Request) -> InboundEmail:
        """Convert an EngageLab inbound POST into a normalised inbound email.

        Args:
            request: The FastAPI request for the inbound POST.

        Returns:
            The normalised :class:`InboundEmail` with ``provider="engagelab"``.

        Raises:
            WebhookParseError: If the content type is unsupported or the body
                cannot be read/extracted.
        """
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                payload = await request.json()
            except Exception as exc:  # noqa: BLE001 - normalise to one type
                logger.error("Could not read EngageLab JSON body: %s", exc)
                raise WebhookParseError(f"Could not read EngageLab JSON body: {exc}") from exc
            parsed = await self._extract(payload or {})
        elif (
            "multipart/form-data" in content_type
            or "application/x-www-form-urlencoded" in content_type
        ):
            try:
                form = await request.form()
            except Exception as exc:  # noqa: BLE001 - normalise to one type
                logger.error("Could not read EngageLab form body: %s", exc)
                raise WebhookParseError(f"Could not read EngageLab form body: {exc}") from exc
            parsed = await self._extract(form)
        else:
            logger.error("Unsupported content type for EngageLab inbound: %s", content_type)
            raise WebhookParseError(
                f"Unsupported content type for EngageLab inbound: {content_type}"
            )

        try:
            spam_score = float(parsed.get("spam_score") or 0)
        except (TypeError, ValueError):
            spam_score = 0.0

        inbound = InboundEmail(
            from_email=parsed.get("from", ""),
            to_email=parsed.get("to", ""),
            subject=parsed.get("subject", ""),
            body_text=parsed.get("text", ""),
            body_html=parsed.get("html", ""),
            spam_score=spam_score,
            dkim=parsed.get("dkim", ""),
            spf=parsed.get("spf", ""),
            provider_message_id=parsed.get("message_id", ""),
            provider=self.provider_name,
        )
        inbound.attachments = parsed.get("attachments", [])

        logger.info(
            "Parsed EngageLab inbound: %s -> %s (%d attachment(s))",
            inbound.from_email,
            inbound.to_email,
            len(inbound.attachments),
        )
        return inbound

    async def _extract(self, payload: Any) -> dict[str, Any]:
        """Extract common inbound fields from a JSON or form payload.

        Args:
            payload: A ``dict`` (JSON body) or form mapping.

        Returns:
            Normalised keys ``from``, ``to``, ``subject``, ``text``, ``html``,
            ``spam_score``, ``dkim``, ``spf``, ``message_id`` and
            ``attachments`` (a ``list[RawAttachment]``).

        Raises:
            WebhookParseError: If the fields cannot be read.
        """
        try:
            response_data = self._response_data(payload)
            headers = response_data.get("headers") or {}

            from_addr = (
                response_data.get("from") or payload.get("sender") or payload.get("from", "")
            )
            to_addr = (
                payload.get("to")
                or response_data.get("x_mx_rcptto")
                or payload.get("recipient", "")
            )

            data = {
                "from": self._clean_address(from_addr),
                "to": self._clean_address(to_addr),
                "subject": response_data.get("subject") or payload.get("subject", ""),
                "text": response_data.get("text") or payload.get("text", ""),
                "html": response_data.get("html") or payload.get("html", ""),
                "spam_score": payload.get("spam_score", 0) or 0,
                "dkim": response_data.get("dkim")
                or payload.get("dkim")
                or ("pass" if headers.get("DKIM-Signature") else ""),
                "spf": response_data.get("spf")
                or payload.get("spf")
                or headers.get("Received-SPF", ""),
                "message_id": payload.get("message_id")
                or response_data.get("email_id")
                or "",
                "attachments": await self._extract_attachments(response_data, payload),
            }
        except Exception as exc:  # noqa: BLE001 - normalise to one type
            logger.error("Failed to extract EngageLab fields: %s", exc)
            raise WebhookParseError(f"Could not extract EngageLab payload fields: {exc}") from exc
        return data

    @staticmethod
    def _response_data(payload: Any) -> dict[str, Any]:
        """Unwrap ``response.response_data`` (handling a JSON-string ``response``)."""
        response = payload.get("response", {})
        if isinstance(response, str):
            try:
                response = json.loads(response) if response else {}
            except ValueError:
                return {}
        return (response or {}).get("response_data") or {}

    @staticmethod
    def _clean_address(value: str) -> str:
        """Reduce a ``"Name <email>"`` value to the bare email address."""
        if not value:
            return ""
        _, addr = parseaddr(value)
        return addr or value

    async def _extract_attachments(
        self, response_data: dict[str, Any], payload: Any
    ) -> list[RawAttachment]:
        """Recover attachments from the raw MIME message (or an explicit array).

        Checks, in order: an explicit ``attachments`` array (kept for the setup
        guide's guessed shape), the inline ``raw_message``, then a download of
        ``raw_message_url`` when no inline copy is present.

        Args:
            response_data: The unwrapped ``response.response_data`` object.
            payload: The full JSON/form payload (checked for a top-level
                ``attachments`` fallback).

        Returns:
            One entry per decodable attachment; empty when none were recovered.
        """
        explicit = response_data.get("attachments") or payload.get("attachments")
        if explicit:
            return self._parse_explicit_attachments(explicit)

        raw_eml = response_data.get("raw_message")
        raw_url = response_data.get("raw_message_url")

        if not raw_eml and raw_url:
            logger.debug("EngageLab raw_message blank, downloading from raw_message_url...")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(raw_url, timeout=_RAW_MESSAGE_DOWNLOAD_TIMEOUT)
                if response.status_code == 200:
                    raw_eml = response.text
                else:
                    logger.error(
                        "EngageLab raw_message_url returned status %d", response.status_code
                    )
            except httpx.HTTPError as exc:
                logger.error("Could not download EngageLab raw_message_url %s: %s", raw_url, exc)

        if not raw_eml:
            return []

        msg = email.message_from_string(raw_eml, policy=email_default_policy)
        attachments: list[RawAttachment] = []
        for part in msg.walk():
            if part.get_content_disposition() != "attachment" and not part.get_filename():
                continue
            filename = part.get_filename() or "unnamed_attachment"
            content_type = part.get_content_type() or "application/octet-stream"
            content = part.get_payload(decode=True)
            if isinstance(content, bytes) and content:
                attachments.append(RawAttachment(filename, content_type, content))
        return attachments

    def _parse_explicit_attachments(self, raw_attachments: Any) -> list[RawAttachment]:
        """Decode base64 attachment entries from an explicit attachments array."""
        if isinstance(raw_attachments, str):
            try:
                raw_attachments = json.loads(raw_attachments) if raw_attachments else []
            except ValueError:
                logger.debug("EngageLab attachments field is not valid JSON")
                return []

        attachments: list[RawAttachment] = []
        for index, item in enumerate(raw_attachments or [], start=1):
            if not isinstance(item, dict):
                logger.debug("Skipping EngageLab attachment %d: not an object", index)
                continue
            filename = item.get("filename") or item.get("name") or f"attachment_{index}"
            content_type = (
                item.get("content_type") or item.get("type") or "application/octet-stream"
            )
            encoded = item.get("content") or item.get("data")
            if not encoded:
                logger.debug("EngageLab attachment %s has no content", filename)
                continue
            try:
                content = base64.b64decode(encoded)
            except (TypeError, ValueError) as exc:
                logger.error("Could not base64-decode EngageLab attachment %s: %s", filename, exc)
                continue
            attachments.append(RawAttachment(filename, content_type, content))
        return attachments
