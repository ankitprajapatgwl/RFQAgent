"""Conversation orchestration for outbound sends and inbound replies.

:class:`EmailDeliveryService` is the single coordinator between the database
(:class:`~src.modules.email_delivery.repository.EmailDeliveryRepository`), the
outbound providers (``providers/``) and the inbound webhook parser
(``webhooks/``). It exposes the high-level operations the routes call:

1. :meth:`send_draft` — open a conversation and send a human-verified draft.
2. :meth:`send_rfq` — open a conversation and send a template-rendered RFQ.
3. :meth:`handle_inbound` — parse an inbound webhook, match it to a
   conversation, persist the reply (against its owning user) and classify it.

Provider instances are built lazily and cached (via
:class:`~src.modules.email_delivery.providers.factory.EmailProviderFactory`,
which validates that provider's credentials), so the app boots fine with email
unconfigured and only fails when a send is actually attempted. The inbound
parser is likewise built on demand from ``settings.email_provider``.

Async/sync note: only :meth:`handle_inbound` is ``async`` — it must ``await``
the parser reading the request body. Everything downstream (matching, DB
writes, attachment persistence) is synchronous, matching this project's sync
SQLAlchemy session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any

from fastapi import Request

from src.config import Settings
from src.modules.auth.models import User
from src.modules.email_delivery.attachments import RawAttachment, store_attachments
from src.modules.email_delivery.enums import (
    ConversationStatus,
    EmailDirection,
    InboundEmailType,
    MatchedVia,
    ReplyAction,
    SendKind,
)
from src.modules.email_delivery.exceptions import (
    ConversationNotFoundError,
    DuplicateConversationTokenError,
    EmailProviderError,
    WebhookParseError,
)
from src.modules.email_delivery.models import Conversation, Email
from src.modules.email_delivery.providers import EmailMaster, EmailProviderFactory
from src.modules.email_delivery.reply_extraction import extract_reply_html, extract_reply_text
from src.modules.email_delivery.repository import EmailDeliveryRepository
from src.modules.email_delivery.webhooks import (
    InboundEmail,
    WebhookParserFactory,
    WebhookParserMaster,
)
from src.modules.email_draft.followup_template import (
    build_followup_subject,
    render_followup_email_html,
)
from src.modules.email_draft.negotiation_template import (
    build_negotiation_subject,
    render_negotiation_email_html,
)
from src.observability import get_logger

logger = get_logger(__name__)

# Bounded retry for the rare case a freshly generated 8-char conversation
# token collides with an existing one. The DB's UNIQUE constraint is the real
# backstop; this loop just turns a collision into a silent re-pick.
_MAX_TOKEN_ATTEMPTS = 5


class EmailDeliveryService:
    """Coordinate conversations, outbound sends and inbound replies.

    Args:
        repository: Request-scoped data access for email-delivery records.
        settings: Shared application configuration.
    """

    def __init__(self, repository: EmailDeliveryRepository, settings: Settings) -> None:
        """Store collaborators and initialise the lazy provider/parser caches."""
        self._repository = repository
        self._settings = settings
        self._provider_cache: dict[str, EmailMaster] = {}
        self._webhook: WebhookParserMaster | None = None

    # ── Provider / parser resolution ─────────────────────────────────────

    def get_provider(self, provider_name: str | None = None) -> EmailMaster:
        """Return the :class:`EmailMaster` for ``provider_name`` (cached).

        Args:
            provider_name: Provider key; defaults to the active configured
                ``email_provider`` when omitted.

        Returns:
            The (possibly newly built) provider instance.

        Raises:
            ProviderConfigError: If the provider is unknown or misconfigured.
        """
        key = (provider_name or self._settings.email_provider or "").strip().lower()
        if key not in self._provider_cache:
            self._provider_cache[key] = EmailProviderFactory.create(key, self._settings)
        return self._provider_cache[key]

    def _webhook_parser(self) -> WebhookParserMaster:
        """Return the inbound parser for the configured provider (cached)."""
        if self._webhook is None:
            self._webhook = WebhookParserFactory.create(
                self._settings.email_provider, self._settings
            )
        return self._webhook

    # ── Conversation creation ─────────────────────────────────────────────

    def create_conversation(
        self,
        *,
        user_id: uuid.UUID,
        user_name: str,
        supplier_email: str,
        supplier_name: str = "",
        subject: str = "",
        send_kind: SendKind | None = None,
        product_name: str | None = None,
        quantity: str | None = None,
        target_price: str | None = None,
        provider_name: str | None = None,
    ) -> Conversation:
        """Mint a unique conversation and its dynamic Reply-To address.

        Retries with a freshly generated token up to :data:`_MAX_TOKEN_ATTEMPTS`
        times if the token collides; the DB's UNIQUE constraint on
        ``conversations.token`` is the actual guarantee.

        Args:
            user_id: Owning user's id.
            user_name: Owning user's display name (used to build addresses).
            supplier_email: Destination supplier address.
            supplier_name: Supplier display name.
            subject: Subject of the first email.
            send_kind: Which outbound flow opened this conversation.
            product_name: RFQ product name (standalone RFQ sends only).
            quantity: RFQ quantity as text (standalone RFQ sends only).
            target_price: RFQ target unit price (standalone RFQ sends only).
            provider_name: Provider key; defaults to the configured provider.

        Returns:
            The newly created :class:`Conversation`.

        Raises:
            DuplicateConversationTokenError: If every attempt collides.
            ProviderConfigError: If the provider is unknown or misconfigured.
        """
        provider = self.get_provider(provider_name)
        last_error: DuplicateConversationTokenError | None = None
        for _ in range(_MAX_TOKEN_ATTEMPTS):
            token = provider.generate_conversation_id()
            reply_to = provider.build_dynamic_email(user_name, token)
            try:
                conversation = self._repository.create_conversation(
                    user_id=user_id,
                    token=token,
                    reply_to_address=reply_to,
                    provider=provider.provider_name,
                    supplier_email=supplier_email,
                    supplier_name=supplier_name,
                    subject=subject,
                    send_kind=send_kind.value if send_kind else None,
                    product_name=product_name,
                    quantity=quantity,
                    target_price=target_price,
                )
            except DuplicateConversationTokenError as exc:
                last_error = exc
                logger.warning("Conversation token collision on %s, retrying", token)
                continue
            logger.info(
                "Created conversation %s (user=%s provider=%s kind=%s)",
                token,
                user_id,
                provider.provider_name,
                send_kind.value if send_kind else "none",
            )
            return conversation
        assert last_error is not None
        raise last_error

    # ── Outbound: verified draft ──────────────────────────────────────────

    def send_draft(
        self,
        *,
        user_id: uuid.UUID,
        user_name: str,
        sender_email: str | None,
        recipient: str,
        recipient_name: str,
        subject: str,
        body_text: str,
        is_html_body: bool = False,
        attachments: list[RawAttachment] | None = None,
        provider_name: str | None = None,
    ) -> Conversation:
        """Open a conversation and send a human-verified draft.

        The draft's body is wrapped as tracked HTML (with the ``CONV-``
        reference footer) so replies thread back. The ``From`` header is the
        user's permanent ``sending_email`` when set, else one derived from
        their name on the provider's outbound domain.

        Args:
            user_id: Sending user's id.
            user_name: Sending user's display name.
            sender_email: The user's permanent ``sending_email``, or ``None``.
            recipient: Supplier address to send to.
            recipient_name: Supplier display name.
            subject: The verified subject.
            body_text: The verified body — plain text unless ``is_html_body``.
            is_html_body: Whether ``body_text`` is already a complete,
                rendered HTML document (e.g. a grafted RFQ email) rather than
                plain text. When ``True``, the body is sent as-is (just the
                reference footer appended) instead of being HTML-escaped.
            attachments: Optional files the user attached to the draft; they
                are transmitted with the email and persisted to local storage.
            provider_name: Provider key; defaults to the configured provider.

        Returns:
            The created :class:`Conversation`, with the sent email recorded.

        Raises:
            EmailProviderError: If the provider is misconfigured or the send fails.
        """
        provider = self.get_provider(provider_name)
        conversation = self.create_conversation(
            user_id=user_id,
            user_name=user_name,
            supplier_email=recipient,
            supplier_name=recipient_name,
            subject=subject,
            send_kind=SendKind.DRAFT,
            provider_name=provider.provider_name,
        )
        if is_html_body:
            html_body = provider.wrap_prerendered_html(
                user_id=str(user_id), conv_id=conversation.token, html_body=body_text
            )
            text_body = provider.html_to_text(body_text)
        else:
            html_body = provider.build_message_html(
                user_id=str(user_id), conv_id=conversation.token, body_text=body_text
            )
            text_body = body_text
        from_email = sender_email or provider.build_sending_email(user_name)
        result = provider.send_email(
            from_email=from_email,
            from_name=user_name,
            to_email=recipient,
            to_name=recipient_name,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=conversation.reply_to_address,
            attachments=self._provider_attachments(attachments),
        )
        email = self._repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.SENT,
            from_email=from_email,
            to_email=recipient,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
            provider=result.get("provider"),
            provider_message_id=result.get("provider_message_id"),
            status_code=result.get("status_code"),
        )
        self._persist_sent_attachments(conversation.token, email.id, attachments)
        logger.info("Sent draft on conversation %s to %s", conversation.token, recipient)
        return conversation

    # ── Outbound: standalone RFQ ──────────────────────────────────────────

    def send_rfq(
        self,
        *,
        user_id: uuid.UUID,
        user_name: str,
        sender_email: str | None,
        supplier_email: str,
        supplier_name: str,
        product_name: str,
        quantity: int,
        target_price: str,
        sender_phone: str = "",
        attachments: list[RawAttachment] | None = None,
        provider_name: str | None = None,
    ) -> Conversation:
        """Open a conversation and send a template-rendered RFQ email.

        Args:
            user_id: Sending user's id.
            user_name: Sending user's display name.
            sender_email: The user's permanent ``sending_email``, or ``None``.
            supplier_email: Supplier address to send to.
            supplier_name: Supplier display name.
            product_name: Product being quoted.
            quantity: Number of units requested.
            target_price: Buyer's target unit price.
            sender_phone: The buyer's phone number, added to the RFQ sign-off.
            attachments: Optional files to send with the RFQ (e.g. a quotation
                form); transmitted with the email and persisted to local storage.
            provider_name: Provider key; defaults to the configured provider.

        Returns:
            The created :class:`Conversation`, with the sent email recorded.

        Raises:
            EmailProviderError: If the provider is misconfigured or the send fails.
        """
        provider = self.get_provider(provider_name)
        conversation = self.create_conversation(
            user_id=user_id,
            user_name=user_name,
            supplier_email=supplier_email,
            supplier_name=supplier_name,
            send_kind=SendKind.RFQ,
            product_name=product_name,
            quantity=str(quantity),
            target_price=target_price,
            provider_name=provider.provider_name,
        )
        subject = provider.build_rfq_subject(conversation.token, product_name)
        html_body = provider.build_rfq_html(
            user_id=str(user_id),
            conv_id=conversation.token,
            supplier_name=supplier_name,
            product_name=product_name,
            quantity=quantity,
            target_price=target_price,
            sender_phone=sender_phone,
        )
        from_email = sender_email or provider.build_sending_email(user_name)
        result = provider.send_email(
            from_email=from_email,
            from_name=provider.company_name,
            to_email=supplier_email,
            to_name=supplier_name,
            subject=subject,
            html_body=html_body,
            reply_to=conversation.reply_to_address,
            attachments=self._provider_attachments(attachments),
        )
        self._repository.update_conversation(conversation, subject=subject)
        email = self._repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.SENT,
            from_email=from_email,
            to_email=supplier_email,
            subject=subject,
            body_html=html_body,
            provider=result.get("provider"),
            provider_message_id=result.get("provider_message_id"),
            status_code=result.get("status_code"),
        )
        self._persist_sent_attachments(conversation.token, email.id, attachments)
        logger.info("Sent RFQ on conversation %s to %s", conversation.token, supplier_email)
        return conversation

    # ── Outbound: follow-up / negotiation on an existing conversation ─────

    def send_followup(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_name: str,
        sender_email: str | None,
        contact_email: str,
        submission_deadline: str,
        rfq_reference: str = "",
        portal_link: str = "",
        include_qa_note: bool = False,
        attachments: list[RawAttachment] | None = None,
    ) -> Conversation:
        """Send a template-rendered follow-up reminder on an existing conversation.

        Unlike :meth:`send_draft`/:meth:`send_rfq` (which always open a new
        conversation), this appends to one that already exists — the message
        threads into the same supplier relationship the original RFQ opened,
        reusing its token/Reply-To address so any future reply still matches
        back exactly as it always has.

        Args:
            user_id: Sending user's id (must own ``conversation_id``).
            conversation_id: The conversation to send the follow-up on.
            user_name: Sending user's display name.
            sender_email: The user's permanent ``sending_email``, or ``None``.
            contact_email: The user's own email, shown as the buyer contact
                in the rendered email (distinct from the ``From`` header).
            submission_deadline: The (possibly new) deadline to highlight.
            rfq_reference: Optional label naming the original RFQ; defaults
                to the conversation's subject when left blank.
            portal_link: Optional URL to a submission portal.
            include_qa_note: Whether to include the "questions welcome" reminder.
            attachments: Optional files to send with the follow-up.

        Returns:
            The conversation the follow-up was sent on.

        Raises:
            ConversationNotFoundError: If no such conversation exists for this user.
            EmailProviderError: If the provider is misconfigured or the send fails.
        """
        conversation = self._require_conversation(user_id=user_id, conversation_id=conversation_id)
        provider = self.get_provider(conversation.provider)
        subject = build_followup_subject(conversation.subject)
        body_html = render_followup_email_html(
            original_issue_date=conversation.created_at.strftime("%B %d, %Y"),
            submission_deadline=submission_deadline,
            rfq_reference=rfq_reference or conversation.subject,
            portal_link=portal_link,
            include_qa_note=include_qa_note,
            contact_name=user_name,
            contact_email=contact_email,
            company_name=provider.company_name,
        )
        self._append_to_conversation(
            conversation=conversation,
            provider=provider,
            user_id=user_id,
            user_name=user_name,
            sender_email=sender_email,
            subject=subject,
            body_html=body_html,
            attachments=attachments,
        )
        logger.info(
            "Sent follow-up on conversation %s to %s", conversation.token, conversation.supplier_email
        )
        return conversation

    def send_negotiation(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_name: str,
        sender_email: str | None,
        response_deadline: str,
        rfq_reference: str = "",
        original_quoted_price: str = "",
        target_price: str = "",
        new_quantity: str = "",
        quoted_terms: str = "",
        requested_terms: str = "",
        quoted_lead_time: str = "",
        target_date: str = "",
        clarifications: str = "",
        portal_link: str = "",
        include_meeting_request: bool = False,
        attachments: list[RawAttachment] | None = None,
    ) -> Conversation:
        """Send a template-rendered negotiation/counter-offer on an existing conversation.

        See :meth:`send_followup` for why this appends to ``conversation_id``
        rather than opening a new one. Every adjustment argument is optional
        and independently gated in the rendered email.

        Args:
            user_id: Sending user's id (must own ``conversation_id``).
            conversation_id: The conversation to send the negotiation on.
            user_name: Sending user's display name.
            sender_email: The user's permanent ``sending_email``, or ``None``.
            response_deadline: Deadline for the supplier to respond.
            rfq_reference: Optional label naming the original RFQ; defaults
                to the conversation's subject when left blank.
            original_quoted_price: The supplier's quoted price, if negotiating price.
            target_price: The buyer's target price, if negotiating price.
            new_quantity: A proposed new order quantity, if negotiating volume.
            quoted_terms: The supplier's quoted payment terms, if negotiating terms.
            requested_terms: The buyer's requested payment terms.
            quoted_lead_time: The supplier's quoted lead time, if negotiating schedule.
            target_date: The buyer's requested delivery date.
            clarifications: A free-text technical/scope note, if any.
            portal_link: Optional URL to a revised-quote submission portal.
            include_meeting_request: Whether to include the "let's hop on a call" note.
            attachments: Optional files to send with the negotiation.

        Returns:
            The conversation the negotiation was sent on.

        Raises:
            ConversationNotFoundError: If no such conversation exists for this user.
            EmailProviderError: If the provider is misconfigured or the send fails.
        """
        conversation = self._require_conversation(user_id=user_id, conversation_id=conversation_id)
        provider = self.get_provider(conversation.provider)
        subject = build_negotiation_subject(conversation.subject)
        body_html = render_negotiation_email_html(
            response_deadline=response_deadline,
            rfq_reference=rfq_reference or conversation.subject,
            original_quoted_price=original_quoted_price,
            target_price=target_price,
            new_quantity=new_quantity,
            quoted_terms=quoted_terms,
            requested_terms=requested_terms,
            quoted_lead_time=quoted_lead_time,
            target_date=target_date,
            clarifications=clarifications,
            portal_link=portal_link,
            include_meeting_request=include_meeting_request,
            company_name=provider.company_name,
        )
        self._append_to_conversation(
            conversation=conversation,
            provider=provider,
            user_id=user_id,
            user_name=user_name,
            sender_email=sender_email,
            subject=subject,
            body_html=body_html,
            attachments=attachments,
        )
        logger.info(
            "Sent negotiation on conversation %s to %s",
            conversation.token,
            conversation.supplier_email,
        )
        return conversation

    def _require_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        """Fetch a conversation owned by ``user_id``, or raise if it doesn't exist."""
        conversation = self._repository.get_for_user(
            user_id=user_id, conversation_id=conversation_id
        )
        if conversation is None:
            raise ConversationNotFoundError(f"No conversation {conversation_id} found for this user.")
        return conversation

    def _append_to_conversation(
        self,
        *,
        conversation: Conversation,
        provider: EmailMaster,
        user_id: uuid.UUID,
        user_name: str,
        sender_email: str | None,
        subject: str,
        body_html: str,
        attachments: list[RawAttachment] | None = None,
    ) -> Email:
        """Send one more HTML message on an already-open conversation.

        Reuses ``conversation``'s existing token/Reply-To address rather than
        minting a new one, so the message threads into the same supplier
        relationship the original send opened.

        Args:
            conversation: The existing, owned conversation to send on.
            provider: The conversation's outbound provider (already resolved).
            user_id: Sending user's id (shown in the tracked-reference footer).
            user_name: Sending user's display name (``From`` display name).
            sender_email: The user's permanent ``sending_email``, or ``None``.
            subject: The rendered subject line.
            body_html: The rendered, complete HTML body.
            attachments: Optional files to send with the message.

        Returns:
            The persisted :class:`Email` row for the sent message.
        """
        html_body = provider.wrap_prerendered_html(
            user_id=str(user_id), conv_id=conversation.token, html_body=body_html
        )
        text_body = provider.html_to_text(body_html)
        from_email = sender_email or provider.build_sending_email(user_name)
        result = provider.send_email(
            from_email=from_email,
            from_name=user_name,
            to_email=conversation.supplier_email,
            to_name=conversation.supplier_name,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=conversation.reply_to_address,
            attachments=self._provider_attachments(attachments),
        )
        email = self._repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.SENT,
            from_email=from_email,
            to_email=conversation.supplier_email,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
            provider=result.get("provider"),
            provider_message_id=result.get("provider_message_id"),
            status_code=result.get("status_code"),
        )
        self._persist_sent_attachments(conversation.token, email.id, attachments)
        return email

    @staticmethod
    def _provider_attachments(
        attachments: list[RawAttachment] | None,
    ) -> list[dict[str, Any]] | None:
        """Convert in-memory attachments to the provider ``send_email`` shape.

        Args:
            attachments: The attachments to transmit, if any.

        Returns:
            A list of ``{filename, content, content_type}`` dicts, or ``None``
            when there are no attachments (so the provider payload stays clean).
        """
        if not attachments:
            return None
        return [
            {
                "filename": att.filename,
                "content": att.content,
                "content_type": att.content_type,
            }
            for att in attachments
        ]

    def _persist_sent_attachments(
        self, conv_id: str, email_id: uuid.UUID, attachments: list[RawAttachment] | None
    ) -> None:
        """Write outbound attachments to local storage and record their rows.

        Mirrors the inbound path so files a user attaches to a draft/RFQ show
        up in the conversation thread and survive a reload.

        Args:
            conv_id: The conversation token (used in the on-disk filename).
            email_id: The sent email row the attachments belong to.
            attachments: The attachments to persist, if any.
        """
        if not attachments:
            return
        metas = store_attachments(self._settings, conv_id, attachments)
        self._repository.add_attachments(email_id=email_id, metas=metas)

    # ── Read-side passthroughs ────────────────────────────────────────────

    def list_conversations(self, *, user_id: uuid.UUID) -> list[Conversation]:
        """Return a user's conversations, newest first."""
        return self._repository.list_for_user(user_id=user_id)

    def get_conversation_detail(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        """Return one owned conversation with its full email thread."""
        return self._repository.get_detail_for_user(
            user_id=user_id, conversation_id=conversation_id
        )

    def delete_conversation(self, *, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        """Delete one owned conversation from the dispatch history.

        Removes the conversation and its whole thread (emails + attachment
        rows, via the ORM cascade) and deletes the backing attachment files
        from local storage so nothing is orphaned on disk.

        Args:
            user_id: The requesting user's id (owns the conversation).
            conversation_id: The conversation to delete.

        Returns:
            ``True`` if a conversation was deleted, ``False`` if none matched
            this user.
        """
        urls = self._repository.delete_conversation(
            user_id=user_id, conversation_id=conversation_id
        )
        if urls is None:
            return False
        self._remove_attachment_files(urls)
        logger.info("Deleted conversation %s for user %s", conversation_id, user_id)
        return True

    def _remove_attachment_files(self, urls: list[str]) -> None:
        """Best-effort delete of stored attachment files behind their URLs.

        Each URL is ``{attachments_url_path}/{name}``; only its basename is
        used to locate the file under :attr:`Settings.attachments_dir`, so a
        crafted URL can never escape that directory. A missing or unremovable
        file is logged and skipped — DB rows are already gone by this point.

        Args:
            urls: Served attachment URLs from the deleted conversation.
        """
        directory = self._settings.attachments_dir
        for url in urls:
            name = (url or "").rsplit("/", 1)[-1]
            if not name:
                continue
            path = directory / name
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - defensive
                logger.error("Could not delete attachment file %s: %s", name, exc)

    # ── Inbound ────────────────────────────────────────────────────────────

    async def handle_inbound(self, request: Request) -> dict[str, Any]:
        """Parse and process one inbound webhook request end-to-end.

        Pipeline: parse → reject on failed signature → skip on spam →
        match to a conversation and persist the reply (see
        :meth:`_record_inbound`).

        Args:
            request: The FastAPI request for the inbound POST.

        Returns:
            A status payload: one of ``{"status": "error"|"rejected"|
            "skipped"|"unmatched"|"matched", ...}``.
        """
        try:
            parser = self._webhook_parser()
            inbound = await parser.parse(request)
        except WebhookParseError as exc:
            logger.error("Inbound parse failed: %s", exc)
            return {"status": "error", "reason": str(exc)}
        except EmailProviderError as exc:
            logger.error("Inbound parser misconfigured: %s", exc)
            return {"status": "error", "reason": str(exc)}

        logger.info(
            "[Inbound] %s -> %s | %s",
            inbound.from_email,
            inbound.to_email,
            inbound.subject,
        )

        if not inbound.signature_verified:
            logger.warning("Rejected inbound: signature not verified")
            return {"status": "rejected", "reason": "invalid_signature"}

        if inbound.spam_score > self._settings.email_spam_threshold:
            logger.info("Skipped inbound: spam score %s", inbound.spam_score)
            return {"status": "skipped", "reason": "spam"}

        try:
            return self._record_inbound(inbound, parser)
        except EmailProviderError as exc:
            logger.error("Inbound matching misconfigured: %s", exc)
            return {"status": "error", "reason": str(exc)}

    def _record_inbound(self, inbound: InboundEmail, parser: WebhookParserMaster) -> dict[str, Any]:
        """Match a parsed inbound email to a conversation and persist it.

        Matching is tried in order: the dynamic Reply-To address, then the
        quoted ``CONV-`` body footer (for forwards with a mangled address),
        then the new-thread path (a headerless supplier email addressed to a
        user's permanent ``sending_email``). Unmatched payloads are stored for
        review rather than dropped.

        Args:
            inbound: The normalised inbound email.
            parser: The parser (reused for attachment persistence).

        Returns:
            ``{"status": "unmatched"}`` or ``{"status": "matched", ...}``.
        """
        provider = self.get_provider(self._settings.email_provider)
        received_at = datetime.now(UTC)

        parsed = provider.parse_dynamic_email(inbound.to_email)
        matched_via = MatchedVia.DYNAMIC_ADDRESS if parsed else None
        if not parsed:
            parsed = provider.parse_conv_id_from_body(inbound.body_text, inbound.body_html)
            if parsed:
                matched_via = MatchedVia.BODY_REFERENCE
        if not parsed:
            new_token = self._match_new_thread(inbound, provider)
            if new_token:
                parsed = {"conv_id": new_token}
                matched_via = MatchedVia.NEW_THREAD

        if not parsed:
            self._store_unmatched(inbound, reason="address_not_recognized")
            logger.info("Unmatched inbound address: %s", inbound.to_email)
            return {"status": "unmatched", "reason": "address_not_recognized"}

        conv_id = parsed["conv_id"]
        conversation = self._repository.get_by_token(conv_id)
        if conversation is None:
            self._store_unmatched(inbound, reason="conversation_not_found")
            logger.info("Unmatched conv_id %s from address %s", conv_id, inbound.to_email)
            return {"status": "unmatched", "reason": "conversation_not_found"}

        logger.info("Matched inbound -> user=%s conv=%s", conversation.user_id, conv_id)

        # Persist only the newly written portion of the reply — the quoted
        # prior conversation is stripped so storage and the thread view carry
        # just what the supplier actually typed this time.
        reply_text = extract_reply_text(inbound.body_text)
        reply_html = extract_reply_html(inbound.body_html)

        # Classify first so a decline flips the conversation status before the
        # reply bookkeeping (which never downgrades a declined conversation).
        action = self._classify_reply(conversation, reply_text)
        email = self._repository.add_email(
            conversation_id=conversation.id,
            direction=EmailDirection.RECEIVED,
            from_email=inbound.from_email,
            to_email=inbound.to_email,
            subject=inbound.subject,
            body_text=reply_text,
            body_html=reply_html,
            provider=inbound.provider,
            provider_message_id=inbound.provider_message_id or None,
            inbound_type=self._detect_inbound_type(inbound.subject).value,
            matched_via=matched_via.value if matched_via else None,
            reply_action=action.value,
            dkim=inbound.dkim,
            spf=inbound.spf,
            spam_score=inbound.spam_score,
        )
        metas = parser.persist_attachments(conversation.token, inbound.attachments)
        self._repository.add_attachments(email_id=email.id, metas=metas)
        self._repository.record_reply(conversation, received_at)

        return {"status": "matched", "conv_id": conv_id, "action": action}

    def _match_new_thread(self, inbound: InboundEmail, provider: EmailMaster) -> str | None:
        """Bind a headerless supplier email to its owning user via sending_email.

        A supplier composing a fresh email (not reply/forward) carries no conv
        id anywhere, but can only have addressed it to a user's permanent,
        unique ``sending_email`` — so that address alone identifies the owner.
        The email is filed under the most recent conversation with this
        supplier, or a new conversation is opened.

        Args:
            inbound: The normalised inbound email.
            provider: The active provider (for address extraction helpers).

        Returns:
            The conversation token to record against, or ``None`` if
            ``inbound.to_email`` isn't any user's ``sending_email``.
        """
        to_address = provider.extract_email_address(inbound.to_email)
        user: User | None = (
            self._repository.get_user_by_sending_email(to_address) if to_address else None
        )
        if user is None:
            return None

        supplier_email = provider.extract_email_address(inbound.from_email)
        existing = self._repository.find_latest_conversation_by_supplier(
            user_id=user.id, supplier_email=supplier_email
        )
        if existing is not None:
            logger.info(
                "New-thread inbound from %s bound to existing conversation %s",
                supplier_email,
                existing.token,
            )
            return existing.token

        supplier_name = parseaddr(inbound.from_email or "")[0] or supplier_email
        conversation = self.create_conversation(
            user_id=user.id,
            user_name=user.full_name,
            supplier_email=supplier_email,
            supplier_name=supplier_name,
            subject=inbound.subject or "",
            provider_name=provider.provider_name,
        )
        logger.info(
            "New-thread inbound from %s opened conversation %s for user %s",
            supplier_email,
            conversation.token,
            user.id,
        )
        return conversation.token

    def _classify_reply(self, conversation: Conversation, reply_body: str) -> ReplyAction:
        """Bucket a supplier reply into a coarse action via keyword matching.

        A ``DECLINED`` classification also flips the conversation status to
        ``declined``. This is the integration point for a future negotiation
        agent.

        Args:
            conversation: The conversation receiving the reply.
            reply_body: Plain-text body of the inbound email.

        Returns:
            The classified :class:`ReplyAction`.
        """
        text = (reply_body or "").lower()
        if any(word in text for word in ("price", "quote", "usd", "$", "unit")):
            action = ReplyAction.QUOTE_RECEIVED
        elif any(word in text for word in ("sorry", "cannot", "unable", "no stock")):
            action = ReplyAction.DECLINED
            self._repository.update_conversation(
                conversation, status=ConversationStatus.DECLINED.value
            )
        elif any(word in text for word in ("question", "clarif", "more info", "?")):
            action = ReplyAction.CLARIFICATION_NEEDED
        else:
            action = ReplyAction.MANUAL_REVIEW
        logger.info("Reply on %s classified as %s", conversation.token, action.value)
        return action

    def _store_unmatched(self, inbound: InboundEmail, *, reason: str) -> None:
        """Persist an unmatched inbound payload for manual review."""
        self._repository.insert_unmatched(
            raw_payload={
                "from_email": inbound.from_email,
                "to_email": inbound.to_email,
                "subject": inbound.subject,
                "body_text": inbound.body_text,
                "spam_score": inbound.spam_score,
            },
            from_email=inbound.from_email,
            to_email=inbound.to_email,
            subject=inbound.subject,
            reason=reason,
            provider=inbound.provider,
        )

    @staticmethod
    def _detect_inbound_type(subject: str) -> InboundEmailType:
        """Detect whether an inbound email is a reply, forward, or new thread."""
        normalized = (subject or "").strip().lower()
        if normalized.startswith(("re:", "re ")):
            return InboundEmailType.REPLY
        if normalized.startswith(("fwd:", "fw:", "fwd ")):
            return InboundEmailType.FORWARDED
        return InboundEmailType.NEW_THREAD
