"""Abstract base and shared logic for inbound webhook parsers.

Every provider posts inbound mail in a slightly different shape. To keep the
single ``POST /webhooks/inbound`` route provider-agnostic, each provider has a
parser that converts its native payload into one normalised
:class:`InboundEmail`.

:class:`WebhookParserMaster` owns the behaviour that does not vary by provider:

- :meth:`WebhookParserMaster.persist_attachments` — write extracted attachment
  bytes to disk and return metadata for the UI/DB.
- :meth:`WebhookParserMaster.verify_signature` — a default "trusted"
  implementation for providers that secure inbound by an unguessable URL /
  network controls rather than an HMAC signature.

Subclasses implement only :meth:`WebhookParserMaster.parse`.
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from src.config import Settings
from src.observability import get_logger

logger = get_logger(__name__)


@dataclass
class RawAttachment:
    """An attachment extracted from an inbound payload, still in memory.

    Attributes:
        filename: Original filename supplied by the sender.
        content_type: MIME type, e.g. ``"application/pdf"``.
        content: Raw file bytes, ready to be written to disk.
    """

    filename: str
    content_type: str
    content: bytes


@dataclass
class InboundEmail:
    """Normalised inbound email, identical across all providers.

    A parser's :meth:`WebhookParserMaster.parse` returns this so the service
    layer can process inbound mail without knowing which provider produced it.

    Attributes:
        from_email: Sender address.
        to_email: Recipient (the dynamic conversation address).
        subject: Subject line.
        body_text: Plain-text body.
        body_html: HTML body.
        spam_score: Provider spam score (``0.0`` if not supplied).
        dkim: DKIM verification result, if provided.
        spf: SPF verification result, if provided.
        provider_message_id: The provider's message id, if supplied.
        attachments: In-memory attachments.
        signature_verified: Whether authenticity was confirmed (always
            ``True`` for providers that do not sign).
        provider: The provider key that produced this payload.
    """

    from_email: str = ""
    to_email: str = ""
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    spam_score: float = 0.0
    dkim: str = ""
    spf: str = ""
    provider_message_id: str = ""
    attachments: list[RawAttachment] = field(default_factory=list)
    signature_verified: bool = True
    provider: str = ""


class WebhookParserMaster(ABC):
    """Common base for all inbound webhook parsers.

    Subclasses implement :meth:`parse`; the base provides attachment
    persistence and a default signature check.

    Args:
        settings: Shared application configuration.
    """

    def __init__(self, settings: Settings) -> None:
        """Store shared configuration."""
        self.settings = settings

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the lowercase provider key this parser handles."""
        raise NotImplementedError

    @abstractmethod
    async def parse(self, request: Request) -> InboundEmail:
        """Convert a provider payload into a normalised inbound email.

        Args:
            request: The FastAPI request for the inbound POST.

        Returns:
            The normalised :class:`InboundEmail`.

        Raises:
            WebhookParseError: If the payload is malformed or unreadable.
        """
        raise NotImplementedError

    def verify_signature(self, request: Request) -> bool:
        """Return whether the inbound request is authentic.

        The default trusts the request (EngageLab's inbound route is secured
        by an unguessable URL bound to a single API_USER, not by an HMAC
        signature). A signing provider would override this.

        Args:
            request: The FastAPI request for the inbound POST.

        Returns:
            ``True`` — trusted by default.
        """
        return True

    def persist_attachments(
        self, conv_id: str, attachments: list[RawAttachment]
    ) -> list[dict[str, Any]]:
        """Write attachment bytes to disk and return their metadata.

        Each file is saved under :attr:`Settings.attachments_dir` with a
        collision-resistant name (``{conv_id}_{batch}_{index}_{filename}``) and
        exposed at ``{attachments_url_path}/{name}``. The per-call ``batch``
        token prevents a later reply on the same conversation from overwriting
        an earlier one whose attachment shares a filename.

        Args:
            conv_id: The conversation the attachments belong to.
            attachments: In-memory attachments from a parsed inbound email.

        Returns:
            One metadata dict per saved file with keys ``filename``,
            ``content_type``, ``size`` and ``url``.
        """
        saved: list[dict[str, Any]] = []
        directory = self.settings.attachments_dir
        directory.mkdir(parents=True, exist_ok=True)
        url_base = self.settings.attachments_url_path.rstrip("/")

        batch = uuid.uuid4().hex[:8]
        for index, att in enumerate(attachments, start=1):
            safe_base = self._safe_filename(att.filename or f"file_{index}")
            safe_name = f"{conv_id}_{batch}_{index}_{safe_base}"
            path = directory / safe_name
            try:
                with open(path, "wb") as handle:
                    handle.write(att.content)
            except OSError as exc:
                # A single bad attachment must not abort the whole reply.
                logger.error("Failed to save attachment %s: %s", safe_name, exc)
                continue
            saved.append(
                {
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "size": len(att.content),
                    "url": f"{url_base}/{safe_name}",
                }
            )
            logger.debug("Saved attachment %s", safe_name)
        return saved

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Strip directory components and unsafe characters from a name.

        Prevents path traversal (``../``) and keeps only characters that are
        safe on common filesystems.

        Args:
            filename: The sender-supplied filename.

        Returns:
            A sanitised basename, never empty.
        """
        base = filename.replace("\\", "/").split("/")[-1]
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
        return cleaned or "attachment"
