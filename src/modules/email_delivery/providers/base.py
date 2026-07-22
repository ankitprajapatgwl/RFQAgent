"""Abstract base class and shared logic for every outbound email provider.

All outbound providers subclass :class:`EmailMaster`. The base owns the
behaviour that must stay **identical** no matter which provider transmits a
message, so a supplier reply can be matched back to its conversation
regardless of how the original was sent:

- :meth:`EmailMaster.generate_conversation_id` — mint a conversation id.
- :meth:`EmailMaster.build_dynamic_email` — encode the conv id into a
  per-conversation Reply-To address.
- :meth:`EmailMaster.build_sending_email` — the stable per-user From address.
- :meth:`EmailMaster.parse_dynamic_email` — decode that address back into its
  conv id (also used by the inbound webhook).
- :meth:`EmailMaster.build_rfq_subject` / :meth:`EmailMaster.build_rfq_html` /
  :meth:`EmailMaster.build_message_html` — render outbound content.

Each concrete provider implements only :attr:`provider_name` and
:meth:`send_email` — the one truly provider-specific piece. This mirrors the
Strategy pattern; :class:`~src.modules.email_delivery.providers.factory.EmailProviderFactory`
supplies the matching subclass, so adding a provider is one new subclass plus
one registry line, with no other code changes.
"""

from __future__ import annotations

import html
import re
import uuid
from abc import ABC, abstractmethod
from email.utils import parseaddr
from typing import Any

from src.config import Settings
from src.modules.email_delivery.exceptions import ProviderConfigError
from src.observability import get_logger

logger = get_logger(__name__)


class EmailMaster(ABC):
    """Common base for all outbound email providers.

    Concrete subclasses implement :attr:`provider_name` and
    :meth:`send_email`; everything else is shared here so the address scheme
    and content templates stay identical across providers.

    Args:
        settings: Shared application configuration. The instance resolves its
            own outbound domain and display name from
            ``{PROVIDER}_OUTBOUND_DOMAIN`` / ``{PROVIDER}_COMPANY_NAME`` via
            :meth:`~src.config.Settings.provider_outbound_domain` /
            :meth:`~src.config.Settings.provider_company_name`.

    Raises:
        ProviderConfigError: If this provider's outbound domain is not set.
    """

    def __init__(self, settings: Settings) -> None:
        """Store settings and resolve this provider's outbound domain/name."""
        self.settings = settings
        self.outbound_domain = self._require(
            settings.provider_outbound_domain(self.provider_name),
            f"{self.provider_name.upper()}_OUTBOUND_DOMAIN",
        )
        self.company_name = settings.provider_company_name(self.provider_name)

    # ── Provider identity (must be overridden) ───────────────────────────

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the lowercase provider key, e.g. ``"engagelab"``."""
        raise NotImplementedError

    # ── Shared address helpers ───────────────────────────────────────────

    def generate_conversation_id(self) -> str:
        """Return a short, unique 8-character lowercase hex conversation id."""
        return uuid.uuid4().hex[:8]

    def build_dynamic_email(self, user_name: str, conv_id: str) -> str:
        """Build the per-conversation Reply-To address.

        Converts the display name to CamelCase and joins it to the conv id
        with a dot, so the conv id can be recovered from any reply, e.g.
        ``"James Whitfield"`` + ``"3fa9c1b2"`` →
        ``JamesWhitfield.3fa9c1b2@{outbound_domain}``.

        Args:
            user_name: The user's display name.
            conv_id: The 8-character conversation identifier.

        Returns:
            The fully qualified dynamic address.
        """
        camel = self._camel_case(user_name)
        return f"{camel}.{conv_id}@{self.outbound_domain}"

    def build_sending_email(self, user_name: str) -> str:
        """Build this provider's stable per-user From address (no conv id).

        Args:
            user_name: The user's display name.

        Returns:
            ``{CamelCaseName}@{outbound_domain}``.
        """
        return f"{self._camel_case(user_name)}@{self.outbound_domain}"

    def parse_dynamic_email(self, email_address: str) -> dict[str, str] | None:
        """Recover ``conv_id`` from a dynamic Reply-To address.

        Tries, in order: the current dot format, then two legacy formats
        (hyphen separator, and a ``prefix_conv{id}`` form) for backward
        compatibility with addresses minted by older code.

        Args:
            email_address: The raw ``To`` address from an inbound email.

        Returns:
            ``{"conv_id": str}`` on success, or ``None`` when the address
            matches no known pattern (or the outbound domain is unset).
        """
        if not self.outbound_domain:
            logger.error(
                "%s_OUTBOUND_DOMAIN is not set; cannot match inbound address",
                self.provider_name.upper(),
            )
            return None

        domain = re.escape(self.outbound_domain)
        patterns = [
            rf"[A-Za-z0-9]+\.([a-f0-9]{{8}})@{domain}(?![\w.-])",  # current: Name.{id}
            rf"[A-Za-z0-9]+-([a-f0-9]{{8}})@{domain}(?![\w.-])",  # legacy: Name-{id}
            rf"[a-z0-9._-]+_conv([a-f0-9]{{8}})@{domain}(?![\w.-])",  # legacy: prefix_conv{id}
        ]
        for pattern in patterns:
            match = re.search(pattern, email_address or "", re.IGNORECASE)
            if match:
                return {"conv_id": match.group(1).lower()}
        return None

    def parse_conv_id_from_body(self, *texts: str) -> dict[str, str] | None:
        """Recover ``conv_id`` from the quoted RFQ reference footer.

        Some mail clients mangle the dynamic ``To`` address when a supplier
        forwards a message, dropping the ``.{conv_id}`` suffix. The quoted
        original still contains the ``CONV-{conv_id}`` footer that every
        outbound message carries (see :meth:`build_rfq_html` /
        :meth:`build_message_html`), so it is used as a fallback.

        Args:
            *texts: Candidate bodies to search (e.g. text then HTML); the
                first match wins.

        Returns:
            ``{"conv_id": str}`` (lowercase) on success, or ``None``.
        """
        for text in texts:
            match = re.search(r"CONV-([A-Fa-f0-9]{8})\b", text or "")
            if match:
                return {"conv_id": match.group(1).lower()}
        return None

    @staticmethod
    def extract_email_address(raw: str) -> str:
        """Strip a display name off a ``"Name <a@b.com>"`` header value.

        Args:
            raw: The raw header value, with or without a display name.

        Returns:
            The lowercased bare address, or ``""`` if none could be parsed.
        """
        return (parseaddr(raw or "")[1] or "").strip().lower()

    # ── Shared content rendering ─────────────────────────────────────────

    def build_rfq_subject(self, conv_id: str, product_name: str) -> str:
        """Build the standard RFQ subject line, e.g. ``[RFQ-3FA9] ...``."""
        tag = conv_id[:4].upper()
        return f"[RFQ-{tag}] Request for Quotation — {product_name}"

    def build_rfq_html(
        self,
        *,
        user_id: str,
        conv_id: str,
        supplier_name: str,
        product_name: str,
        quantity: int,
        target_price: str,
    ) -> str:
        """Render the inline-styled HTML body of a standalone RFQ email.

        The markup is intentionally inline-styled so it renders consistently
        across email clients (which strip ``<style>`` blocks) and ends with
        the ``Reference: CONV-{id}`` footer used by
        :meth:`parse_conv_id_from_body`.

        Args:
            user_id: The owning user (shown in the footer reference).
            conv_id: The conversation identifier (shown in the footer).
            supplier_name: Salutation name for the supplier.
            product_name: Product being quoted.
            quantity: Number of units requested.
            target_price: Buyer's target unit price, e.g. ``"$12.00"``.

        Returns:
            A complete HTML fragment ready to use as the email body.
        """
        company = self.company_name
        parts = [
            '<div style="font-family: Arial, sans-serif; max-width: 600px;">',
            f'<img src="https://placehold.co/320x40/blue/white?text={company}" '
            f'alt="{company}" width="320" height="40" '
            'style="display:block; margin-bottom:16px;">',
            f"<p>Dear {supplier_name},</p>",
            "<p>I am writing to request a formal quotation for the following:</p>",
            '<table border="1" cellpadding="8" cellspacing="0"',
            ' style="border-collapse: collapse; width: 100%;">',
            '<tr style="background-color: #f5f5f5;">',
            "<th>Product</th><th>Quantity</th><th>Target Price</th></tr>",
            f"<tr><td>{product_name}</td>",
            f"<td>{quantity} units</td>",
            f"<td>{target_price} per unit</td></tr>",
            "</table>",
            "<p>Please include the following in your quotation:</p>",
            "<ul>",
            "<li>Unit price at stated quantity (FOB)</li>",
            "<li>Minimum order quantity (MOQ)</li>",
            "<li>Lead time and production capacity</li>",
            "<li>Payment terms</li>",
            "<li>Product specifications and certifications</li>",
            "</ul>",
            "<p>We look forward to your response within 3 business days.</p>",
            f"<p>Best regards,<br><strong>{company} Sourcing Team</strong></p>",
            self._reference_footer(user_id, conv_id),
            "</div>",
        ]
        return "".join(parts)

    def build_message_html(self, *, user_id: str, conv_id: str, body_text: str) -> str:
        """Wrap a human-authored plain-text body as a conversation-tracked email.

        Used when sending a verified draft (whose body is plain text): the
        text is HTML-escaped, newlines become ``<br>``, and the same
        ``CONV-{id}`` reference footer is appended so replies whose Reply-To
        address is mangled can still be matched via
        :meth:`parse_conv_id_from_body`.

        Args:
            user_id: The owning user (shown in the footer reference).
            conv_id: The conversation identifier (shown in the footer).
            body_text: The human-verified plain-text body.

        Returns:
            A complete HTML fragment ready to use as the email body.
        """
        escaped = html.escape(body_text or "").replace("\n", "<br>")
        return "".join(
            [
                '<div style="font-family: Arial, sans-serif; max-width: 600px;">',
                f"<p>{escaped}</p>",
                self._reference_footer(user_id, conv_id),
                "</div>",
            ]
        )

    @staticmethod
    def _reference_footer(user_id: str, conv_id: str) -> str:
        """Return the standard hidden ``CONV-/USR-/THREAD-`` reference footer."""
        tag = conv_id.upper()
        return (
            '<hr style="border:none; border-top:1px solid #eee; margin-top:30px;">'
            '<p style="font-size:11px; color:#aaa;">'
            f"Reference: CONV-{tag} | USR-{user_id} | THREAD-{tag}</p>"
        )

    @staticmethod
    def _camel_case(user_name: str) -> str:
        """Convert a display name to CamelCase, e.g. ``"Jane Doe"`` → ``"JaneDoe"``."""
        return "".join(word.capitalize() for word in (user_name or "").split()) or "User"

    @staticmethod
    def sanitize_header(value: str) -> str:
        """Collapse a header value (subject / display name) to a single safe line.

        Newlines or carriage returns in a header are an injection vector that
        many providers accept with a ``2xx`` but then silently drop or mangle
        the message — the exact "status 200 yet no email arrives" symptom seen
        with LLM-drafted subjects that contained a stray line break. Any run of
        control/whitespace characters is collapsed to a single space and the
        result trimmed.

        Args:
            value: The raw header value.

        Returns:
            A single-line, whitespace-collapsed header value.
        """
        return re.sub(r"\s+", " ", (value or "").replace("\x00", "")).strip()

    @staticmethod
    def html_to_text(html_body: str) -> str:
        """Derive a readable plain-text alternative from an HTML body.

        A ``text/plain`` alternative alongside the HTML markedly improves
        deliverability — HTML-only messages are far more likely to be spam-
        filtered or dropped. Block-level tags become line breaks, the rest are
        stripped, and HTML entities are unescaped.

        Args:
            html_body: The HTML body to convert.

        Returns:
            A plain-text rendering of ``html_body``.
        """
        text = re.sub(r"(?i)<\s*br\s*/?>", "\n", html_body or "")
        text = re.sub(r"(?i)</\s*(p|div|tr|li|h[1-6]|table|ul|ol)\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        return text.strip()

    # ── Provider-specific transmission (must be overridden) ──────────────

    @abstractmethod
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
        """Transmit a single email through the concrete provider.

        Implementations perform the provider-specific network call and
        normalise the result so callers never depend on a provider's native
        response shape.

        Args:
            from_email: Sender address for the ``From`` header.
            from_name: Display name for the ``From`` header.
            to_email: Recipient address.
            to_name: Recipient display name.
            subject: Subject line.
            html_body: HTML body of the message.
            reply_to: The dynamic conversation address, so replies route back.
            text_body: Optional plain-text alternative. When omitted the
                provider derives one from ``html_body`` (see
                :meth:`html_to_text`) so no message is ever sent HTML-only.
            attachments: Optional list of dicts, each with ``filename`` (str),
                ``content`` (bytes) and ``content_type`` (str).

        Returns:
            Normalised ``{"status_code": int, "provider": str,
            "provider_message_id": str | None}``.

        Raises:
            ProviderConfigError: If required credentials are missing.
            EmailSendError: If the provider rejects or fails the send.
        """
        raise NotImplementedError

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require(self, value: str | None, name: str) -> str:
        """Return ``value`` or raise :class:`ProviderConfigError` if empty.

        Args:
            value: The configuration value to check.
            name: The environment-variable name, used in the error message.

        Returns:
            The validated, non-empty value.

        Raises:
            ProviderConfigError: If ``value`` is ``None`` or empty.
        """
        if not value:
            raise ProviderConfigError(
                f"Missing required configuration: {name}. Set it in your .env file."
            )
        return value
