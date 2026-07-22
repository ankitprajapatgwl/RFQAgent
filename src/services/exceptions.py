"""Domain-specific exceptions for the authentication feature.

Raising typed exceptions (rather than returning ``None`` or booleans) lets the
API layer translate each failure into the correct HTTP status without leaking
implementation details. Catching a specific type is mandated by the coding
standards (file ``04``, rule 2.3 "No bare except").
"""


class AuthError(Exception):
    """Base class for all authentication-related errors."""


class EmailAlreadyRegisteredError(AuthError):
    """Raised when registering an email that already exists."""


class InvalidCredentialsError(AuthError):
    """Raised when a login attempt has an unknown email or wrong password."""


class InactiveUserError(AuthError):
    """Raised when a valid user account has been deactivated."""


class InvalidTokenError(AuthError):
    """Raised when a JWT is missing, malformed, or expired."""
