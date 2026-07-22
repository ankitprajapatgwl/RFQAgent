"""Authentication business logic.

:class:`AuthService` orchestrates the collaborators — repository, password
hasher, token service — to implement registration, login, and token-based user
resolution. It is deliberately free of any FastAPI/HTTP concept, so it can be
driven directly from a unit test with in-memory fakes.
"""

from __future__ import annotations

import uuid

from src.config import Settings
from src.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from src.modules.auth.models import User
from src.modules.auth.password_hasher import PasswordHasher
from src.modules.auth.repository import UserRepository
from src.modules.auth.schemas import TokenResponse, UserCreate
from src.modules.auth.token_service import TokenService
from src.observability import get_logger

logger = get_logger(__name__)

# Upper bound on the numeric suffix tried when a user's derived sending
# address collides with an existing one (two users with the same display
# name). Far more than enough in practice; guards against an infinite loop.
_MAX_SENDING_EMAIL_ATTEMPTS = 1000

# A pre-computed hash of a throwaway value. Verifying against it when a user is
# not found makes failed logins take roughly the same time whether the email
# exists or not, mitigating user-enumeration via timing.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO3f8Xb9Yf1r3H9r4Yf1r3H9r4Yf1r3H"


class AuthService:
    """Coordinates registration and authentication use-cases.

    Args:
        repository: Data access for user records.
        password_hasher: Strategy used to hash and verify passwords.
        token_service: Issues and validates JWT access tokens.
    """

    def __init__(
        self,
        repository: UserRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        settings: Settings | None = None,
    ) -> None:
        """Store injected collaborators.

        Args:
            repository: Data access for user records.
            password_hasher: Strategy used to hash and verify passwords.
            token_service: Issues and validates JWT access tokens.
            settings: Application settings, used only to derive each user's
                permanent ``sending_email`` at registration. Optional so the
                service can still be constructed with in-memory fakes in unit
                tests; when omitted (or no sending domain is configured) the
                ``sending_email`` is simply left unset.
        """
        self._repository = repository
        self._hasher = password_hasher
        self._tokens = token_service
        self._settings = settings

    def register(self, payload: UserCreate) -> User:
        """Register a new user account.

        Args:
            payload: Validated registration data.

        Returns:
            The newly created :class:`User`.

        Raises:
            EmailAlreadyRegisteredError: If the email is already in use.
        """
        if self._repository.get_by_email(payload.email) is not None:
            logger.info("Registration blocked: email already registered.")
            raise EmailAlreadyRegisteredError("An account with this email already exists.")

        hashed = self._hasher.hash(payload.password)
        user = self._repository.create(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hashed,
            sending_email=self._assign_sending_email(payload.full_name),
        )
        logger.info("Registered new user id=%s (sending_email=%s).", user.id, user.sending_email)
        return user

    def _assign_sending_email(self, full_name: str) -> str | None:
        """Derive a unique permanent outbound address for a new user.

        The local part is the user's display name in CamelCase (matching the
        email-delivery module's ``build_sending_email``), combined with the
        configured default outbound domain. If two users share a display name,
        an incrementing numeric suffix keeps the address unique. Returns
        ``None`` when no settings/sending domain is configured — the app then
        runs without new-thread inbound matching, which is acceptable.

        Args:
            full_name: The registering user's display name.

        Returns:
            A unique sending address, or ``None`` if unconfigured.
        """
        if self._settings is None:
            return None
        domain = self._settings.default_outbound_domain
        if not domain:
            return None

        local = "".join(word.capitalize() for word in full_name.split()) or "User"
        candidate = f"{local}@{domain}"
        for suffix in range(1, _MAX_SENDING_EMAIL_ATTEMPTS):
            if self._repository.get_by_sending_email(candidate) is None:
                return candidate
            candidate = f"{local}{suffix}@{domain}"
        # Exhausted every suffix (astronomically unlikely) — leave it unset
        # rather than block registration on an addressing edge case.
        logger.warning("Could not derive a unique sending_email for %r.", full_name)
        return None

    def authenticate(self, email: str, password: str) -> User:
        """Verify credentials and return the matching active user.

        Args:
            email: Submitted email address.
            password: Submitted plaintext password.

        Returns:
            The authenticated :class:`User`.

        Raises:
            InvalidCredentialsError: If the email is unknown or the password is
                wrong.
            InactiveUserError: If the account exists but is deactivated.
        """
        user = self._repository.get_by_email(email)
        if user is None:
            # Perform a dummy verify to keep timing consistent, then fail.
            self._hasher.verify(password, _DUMMY_HASH)
            raise InvalidCredentialsError("Incorrect email or password.")

        if not self._hasher.verify(password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect email or password.")

        if not user.is_active:
            raise InactiveUserError("This account has been deactivated.")

        logger.info("Authenticated user id=%s.", user.id)
        return user

    def issue_token(self, user: User) -> TokenResponse:
        """Create an access-token response for an authenticated user.

        Args:
            user: The authenticated user.

        Returns:
            A :class:`TokenResponse` carrying the signed JWT and its lifetime.
        """
        token = self._tokens.create_access_token(user_id=user.id, email=user.email)
        return TokenResponse(access_token=token, expires_in=self._tokens.expires_in_seconds)

    def login(self, email: str, password: str) -> tuple[User, TokenResponse]:
        """Authenticate a user and issue an access token in one step.

        Args:
            email: Submitted email address.
            password: Submitted plaintext password.

        Returns:
            A tuple of the authenticated user and their token response.
        """
        user = self.authenticate(email, password)
        return user, self.issue_token(user)

    def resolve_user_from_token(self, token: str) -> User:
        """Resolve the active user referenced by a JWT access token.

        Args:
            token: The encoded JWT string.

        Returns:
            The :class:`User` the token belongs to.

        Raises:
            InvalidTokenError: If the token is invalid or its user no longer
                exists / is inactive.
        """
        payload = self._tokens.decode_access_token(token)
        try:
            user_id = uuid.UUID(payload.sub)
        except ValueError as exc:
            raise InvalidTokenError("Token subject is not a valid user id.") from exc

        user = self._repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise InvalidTokenError("Token refers to a missing or inactive user.")
        return user
