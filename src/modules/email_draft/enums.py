"""Enumerations used across the email-draft module."""

from enum import StrEnum


class DraftStatus(StrEnum):
    """Lifecycle state of a drafted email.

    ``DRAFT`` is the only status the agent itself can ever write — set once,
    at generation time. ``VERIFIED`` is a human approval action (see
    ``EmailDraftService.verify``) and is never set by the generation or
    modification code paths.
    """

    DRAFT = "draft"
    VERIFIED = "verified"
