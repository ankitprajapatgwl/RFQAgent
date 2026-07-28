"""Domain-specific exceptions for the email-draft module."""


class EmailDraftGenerationError(Exception):
    """Raised when the LLM fails to produce a valid email draft."""


class EmailDraftNotFoundError(Exception):
    """Raised when a requested drafted email does not exist or isn't owned by the caller."""
