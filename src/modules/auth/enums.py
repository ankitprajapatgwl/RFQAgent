"""Enumerations used across the auth module."""

from enum import StrEnum


class UserRole(StrEnum):
    """Role assigned to a user account.

    ``BUYER`` is the default role granted at registration.
    """

    BUYER = "buyer"
    MANAGER = "manager"
    ADMIN = "admin"


class TokenType(StrEnum):
    """Type of JWT token issued by the service."""

    ACCESS = "access"
