"""Data-access layer for the email-delivery module.

Implements the *Repository pattern*: every SQL/ORM query for conversations,
emails, attachments and unmatched inbound payloads lives behind this class, so
the service never touches SQLAlchemy directly.

It imports the auth module's :class:`~src.modules.auth.models.User` for exactly
one query — :meth:`get_user_by_sending_email`, which the inbound *new-thread*
matcher needs to recover a headerless supplier email's owning user. That is
the single, deliberate cross-module read; everything else stays within this
module's own tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.modules.auth.models import User
from src.modules.email_delivery.enums import (
    ConversationStatus,
    EmailDirection,
    EmailProcessingStatus,
)
from src.modules.email_delivery.exceptions import DuplicateConversationTokenError
from src.modules.email_delivery.models import Attachment, Conversation, Email, UnmatchedEmail


class EmailDeliveryRepository:
    """Read/write access to email-delivery records for a single session.

    Args:
        session: The active SQLAlchemy session this repository operates on.
    """

    def __init__(self, session: Session) -> None:
        """Bind the repository to a database session."""
        self._session = session

    # ── Conversations ────────────────────────────────────────────────────

    def create_conversation(
        self,
        *,
        user_id: uuid.UUID,
        token: str,
        reply_to_address: str,
        provider: str,
        supplier_email: str,
        supplier_name: str = "",
        subject: str = "",
        send_kind: str | None = None,
        product_name: str | None = None,
        quantity: str | None = None,
        target_price: str | None = None,
    ) -> Conversation:
        """Insert a new conversation, isolating a token collision in a savepoint.

        Args:
            user_id: Owning user's id.
            token: The unique 8-char conversation id.
            reply_to_address: The dynamic per-conversation address.
            provider: Provider key that will send the first message.
            supplier_email: Destination supplier address.
            supplier_name: Supplier display name.
            subject: Subject of the first email.
            send_kind: Which outbound flow opened this conversation.
            product_name: RFQ product, for standalone RFQ sends.
            quantity: RFQ quantity (stored as text), for standalone RFQ sends.
            target_price: RFQ target price, for standalone RFQ sends.

        Returns:
            The newly created, flushed :class:`Conversation`.

        Raises:
            DuplicateConversationTokenError: If ``token`` already exists. The
                savepoint is rolled back so the caller can retry with a fresh
                token without discarding earlier work in the transaction.
        """
        conversation = Conversation(
            user_id=user_id,
            token=token,
            reply_to_address=reply_to_address,
            provider=provider,
            supplier_email=supplier_email,
            supplier_name=supplier_name,
            subject=subject,
            send_kind=send_kind,
            product_name=product_name,
            quantity=quantity,
            target_price=target_price,
        )
        try:
            with self._session.begin_nested():
                self._session.add(conversation)
        except IntegrityError as exc:
            raise DuplicateConversationTokenError(
                f"Conversation token {token!r} already exists."
            ) from exc
        return conversation

    def get_by_token(self, token: str) -> Conversation | None:
        """Return the conversation with the given token, or ``None``."""
        stmt = select(Conversation).where(Conversation.token == token)
        return self._session.scalars(stmt).first()

    def get_for_user(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        """Return one conversation owned by the given user, if it exists."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
        return self._session.scalars(stmt).first()

    def get_detail_for_user(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        """Return one owned conversation with its emails+attachments eager-loaded."""
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .options(selectinload(Conversation.emails).selectinload(Email.attachments))
        )
        return self._session.scalars(stmt).first()

    def list_for_user(self, *, user_id: uuid.UUID) -> list[Conversation]:
        """Return a user's conversations, newest first."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def delete_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[str] | None:
        """Delete one owned conversation and its whole thread.

        The ORM cascade (``delete-orphan`` on ``emails`` → ``attachments``)
        removes every email and attachment row belonging to the conversation.
        The stored attachment URLs are collected first and returned so the
        service can delete the backing files from local storage.

        Args:
            user_id: The requesting user's id (owns the conversation).
            conversation_id: The conversation to delete.

        Returns:
            The list of attachment URLs that were attached to the deleted
            conversation (possibly empty), or ``None`` if no such conversation
            exists for this user.
        """
        conversation = self.get_detail_for_user(
            user_id=user_id, conversation_id=conversation_id
        )
        if conversation is None:
            return None
        urls = [
            attachment.url
            for email in conversation.emails
            for attachment in email.attachments
            if attachment.url
        ]
        self._session.delete(conversation)
        self._session.flush()
        return urls

    def find_latest_conversation_by_supplier(
        self, *, user_id: uuid.UUID, supplier_email: str
    ) -> Conversation | None:
        """Return the user's most recent conversation with a given supplier."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.supplier_email == supplier_email,
            )
            .order_by(Conversation.created_at.desc())
        )
        return self._session.scalars(stmt).first()

    def update_conversation(self, conversation: Conversation, **changes: Any) -> Conversation:
        """Apply field changes to an attached conversation and flush."""
        for field_name, value in changes.items():
            setattr(conversation, field_name, value)
        self._session.flush()
        return conversation

    def record_reply(self, conversation: Conversation, received_at: datetime) -> Conversation:
        """Bump reply bookkeeping when a supplier reply is recorded.

        Increments ``reply_count``, sets ``last_reply_at``, and moves an
        ``open`` conversation to ``replied`` (a ``declined`` one is left
        as-is — a decline is a terminal state).

        Args:
            conversation: The attached conversation being replied to.
            received_at: Timestamp of the reply.

        Returns:
            The updated conversation.
        """
        conversation.reply_count += 1
        conversation.last_reply_at = received_at
        if conversation.status == ConversationStatus.OPEN.value:
            conversation.status = ConversationStatus.REPLIED.value
        self._session.flush()
        return conversation

    # ── Emails & attachments ─────────────────────────────────────────────

    def add_email(
        self,
        *,
        conversation_id: uuid.UUID,
        direction: EmailDirection,
        from_email: str,
        to_email: str,
        subject: str,
        body_text: str | None = None,
        body_html: str | None = None,
        provider: str | None = None,
        provider_message_id: str | None = None,
        inbound_type: str | None = None,
        matched_via: str | None = None,
        reply_action: str | None = None,
        dkim: str | None = None,
        spf: str | None = None,
        spam_score: float | None = None,
        status_code: int | None = None,
    ) -> Email:
        """Persist one sent or received message and return the managed instance."""
        email = Email(
            conversation_id=conversation_id,
            direction=direction.value,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            provider=provider,
            provider_message_id=provider_message_id,
            inbound_type=inbound_type,
            matched_via=matched_via,
            reply_action=reply_action,
            dkim=dkim,
            spf=spf,
            spam_score=spam_score,
            status_code=status_code,
        )
        self._session.add(email)
        self._session.flush()
        return email

    def add_attachments(
        self, *, email_id: uuid.UUID, metas: list[dict[str, Any]]
    ) -> list[Attachment]:
        """Persist attachment metadata rows for an email."""
        rows = [
            Attachment(
                email_id=email_id,
                filename=meta.get("filename", "attachment"),
                url=meta.get("url", ""),
                content_type=meta.get("content_type"),
                size_bytes=meta.get("size"),
            )
            for meta in metas
        ]
        if rows:
            self._session.add_all(rows)
            self._session.flush()
        return rows

    def get_oldest_unprocessed_received_email(self) -> Email | None:
        """Return the earliest-saved received email still awaiting processing.

        Powers the background ``worker``: received (inbound supplier) emails
        whose ``processing_status`` is ``pending``, ordered oldest-first by
        ``created_at`` so the queue is drained in arrival order (FIFO).

        Returns:
            The oldest pending received :class:`Email`, or ``None`` when the
            queue is empty.
        """
        stmt = (
            select(Email)
            .where(
                Email.direction == EmailDirection.RECEIVED.value,
                Email.processing_status == EmailProcessingStatus.PENDING.value,
            )
            .order_by(Email.created_at.asc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def mark_email_processed(self, email: Email) -> Email:
        """Flag an email as processed so the worker does not pick it up again.

        Args:
            email: The attached email to update.

        Returns:
            The updated email.
        """
        email.processing_status = EmailProcessingStatus.PROCESSED.value
        self._session.flush()
        return email

    # ── Unmatched inbound ─────────────────────────────────────────────────

    def insert_unmatched(
        self,
        *,
        raw_payload: dict[str, Any],
        from_email: str,
        to_email: str,
        subject: str,
        reason: str,
        provider: str,
    ) -> UnmatchedEmail:
        """Persist an inbound email that matched no conversation, for review."""
        record = UnmatchedEmail(
            raw_payload=raw_payload,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            reason=reason,
            provider=provider,
        )
        self._session.add(record)
        self._session.flush()
        return record

    # ── Cross-module read (auth) ──────────────────────────────────────────

    def get_user_by_sending_email(self, sending_email: str) -> User | None:
        """Return the user whose permanent ``sending_email`` matches, if any.

        The one deliberate cross-module read (see module docstring): used only
        by the inbound new-thread matcher. The comparison is case-insensitive.

        Args:
            sending_email: The bare recipient address to match.

        Returns:
            The matching :class:`User`, or ``None``.
        """
        normalized = (sending_email or "").strip().lower()
        if not normalized:
            return None
        stmt = select(User).where(User.sending_email == normalized)
        return self._session.scalars(stmt).first()
