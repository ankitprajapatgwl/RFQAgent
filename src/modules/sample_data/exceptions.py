"""Domain-specific exceptions for the sample-data module."""


class SampleQueryGenerationError(Exception):
    """Raised when the LLM fails to produce a valid sample email query."""


class SampleQueryNotFoundError(Exception):
    """Raised when a requested saved sample query does not exist or isn't owned by the caller."""
