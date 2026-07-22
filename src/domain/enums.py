"""Enumerations used across the authentication domain."""

from enum import StrEnum


class UserRole(StrEnum):
    """Role assigned to a user account.

    The values map directly to the roles referenced in the platform rules
    (e.g. buyer/manager approval gates). ``BUYER`` is the default role granted
    at registration.
    """

    BUYER = "buyer"
    MANAGER = "manager"
    ADMIN = "admin"


class TokenType(StrEnum):
    """Type of JWT token issued by the service."""

    ACCESS = "access"


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
