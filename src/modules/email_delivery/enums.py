"""Enumerations used across the email-delivery module."""

from enum import StrEnum


class ConversationStatus(StrEnum):
    """Lifecycle state of a tracked RFQ conversation.

    ``OPEN`` on creation; flips to ``REPLIED`` when a supplier reply is
    recorded, or ``DECLINED`` when a reply is classified as a decline.
    """

    OPEN = "open"
    REPLIED = "replied"
    DECLINED = "declined"


class EmailDirection(StrEnum):
    """Direction of a stored email relative to this application."""

    SENT = "sent"
    RECEIVED = "received"


class ReplyAction(StrEnum):
    """Coarse classification of a supplier reply.

    The integration point for a future negotiation agent — a matched inbound
    reply is bucketed into one of these by simple keyword heuristics.
    """

    QUOTE_RECEIVED = "QUOTE_RECEIVED"
    DECLINED = "DECLINED"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class EmailProcessingStatus(StrEnum):
    """Background-processing state of a stored email.

    Consumed by the ``worker`` module, which polls for the oldest received
    email still ``PENDING`` and hands it to downstream processing. ``PENDING``
    on creation; the worker flips it to ``PROCESSED`` once handled. ``PROCESSING``
    and ``FAILED`` are reserved for the real processing logic added later — an
    in-flight claim and a terminal error state respectively.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class InboundEmailType(StrEnum):
    """Whether an inbound email is a reply, a forward, or a fresh thread."""

    REPLY = "reply"
    FORWARDED = "forwarded"
    NEW_THREAD = "new_thread"


class MatchedVia(StrEnum):
    """How an inbound email was matched back to its conversation."""

    DYNAMIC_ADDRESS = "dynamic_address"
    BODY_REFERENCE = "body_reference"
    NEW_THREAD = "new_thread"


class UnmatchedStatus(StrEnum):
    """Triage state of an inbound email that matched no conversation."""

    NEEDS_REVIEW = "needs_review"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class SendKind(StrEnum):
    """Which outbound flow produced a conversation's first email.

    ``DRAFT`` — a human-verified draft from the ``email_draft`` module.
    ``RFQ`` — a standalone structured RFQ rendered from the built-in template.
    """

    DRAFT = "draft"
    RFQ = "rfq"
