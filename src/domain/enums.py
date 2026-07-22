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
