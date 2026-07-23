"""Domain-specific exceptions for the email-extraction module."""


class EmailExtractionError(Exception):
    """Raised when the LLM fails to produce a valid, parsable extraction.

    Always translated from the underlying SDK/parse error at the service
    boundary so the background worker never sees a bare third-party exception
    (agent rule: every agent handles its own failure).
    """
