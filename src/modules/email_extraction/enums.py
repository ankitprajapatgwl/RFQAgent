"""Enumerations used across the email-extraction module.

The vocabulary an :class:`~src.modules.email_extraction.agent.EmailExtractorAgent`
classifies an inbound supplier email into, plus the lifecycle state of a stored
extraction. The *structure* (which fields to pull) for each
:class:`ExtractedEmailType` lives in ``constants.py`` — deliberately separated so
the field list can be edited in one place without touching this enum (see the
module docstring in ``constants.py``).
"""

from enum import StrEnum


class ExtractedEmailType(StrEnum):
    """The kind of inbound supplier email the extractor classified a message as.

    This is the *inbound* counterpart to the outbound drafting vocabulary in
    :class:`~src.modules.email_patterns.enums.EmailType`: it describes what a
    supplier *sent us*, not what we drafted. Each member has a matching entry in
    :data:`~src.modules.email_extraction.constants.EMAIL_TYPE_STRUCTURES`
    defining the fields to extract for it. ``GENERAL`` is the always-valid
    fallback when a message fits none of the specific types.
    """

    QUOTE = "quote"
    FOLLOW_UP = "follow_up"
    NEGOTIATION = "negotiation"
    CLARIFICATION = "clarification"
    DECLINE = "decline"
    SAMPLE = "sample"
    ORDER_CONFIRMATION = "order_confirmation"
    GENERAL = "general"


class ExtractionStatus(StrEnum):
    """Lifecycle state of a stored extraction record.

    A row is written only *after* the worker has processed a received email, so
    there is no ``pending`` state here (that lives on the source email's
    ``processing_status``). ``COMPLETED`` — the AI returned a valid, parsed
    result. ``FAILED`` — the LLM call or its parsing failed after retries; the
    original content is still stored for manual review.
    """

    COMPLETED = "completed"
    FAILED = "failed"
