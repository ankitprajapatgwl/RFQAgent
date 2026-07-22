"""Enumerations used across every module that deals with email patterns."""

from enum import StrEnum


class EmailType(StrEnum):
    """Supplier-email pattern the user can draft.

    Values match the skill directory names under
    ``skills/emails-patterns/`` one-to-one, so an :class:`EmailType` can be
    used directly to locate its ``SKILL.md`` on disk.
    """

    APOLOGY = "apology-email"
    FOLLOW_UP = "follow-up-email"
    NEGOTIATION = "negotiation-email"
    RFQ = "rfq-email"
    SAMPLE_REQUEST = "sample-request-email"
