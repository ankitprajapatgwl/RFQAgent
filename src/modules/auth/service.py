"""Authentication business logic.

:class:`AuthService` orchestrates the collaborators — repository, password
hasher, token service — to implement registration, login, and token-based user
resolution. It is deliberately free of any FastAPI/HTTP concept, so it can be
driven directly from a unit test with in-memory fakes.
"""

from __future__ import annotations

import re
import uuid

from src.config import Settings
from src.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    SendingEmailAlreadyInUseError,
)
from src.modules.auth.models import User
from src.modules.auth.password_hasher import PasswordHasher
from src.modules.auth.repository import UserRepository
from src.modules.auth.schemas import TokenResponse, UserCreate
from src.modules.auth.token_service import TokenService
from src.observability import get_logger

logger = get_logger(__name__)

# Characters kept in a derived/confirmed sending-email local part. Anything
# else (spaces, ``@`` from a pasted full address, exotic punctuation) is
# dropped so the result is always a safe, single-label local part.
_LOCAL_PART_ALLOWED = re.compile(r"[^a-z0-9._+-]+")

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

        The outbound ``sending_email`` is taken from the address the user
        confirmed on the form (``payload.sending_email``) when present, else
        derived from their login email's local part; either way it is
        re-anchored to the configured outbound domain and must be globally
        unique. Unlike the old auto-suffixing behaviour, a collision is now
        surfaced to the user (per the registration flow) rather than silently
        resolved.

        Args:
            payload: Validated registration data.

        Returns:
            The newly created :class:`User`.

        Raises:
            EmailAlreadyRegisteredError: If the email is already in use.
            SendingEmailAlreadyInUseError: If the resolved ``sending_email`` is
                already claimed by another account.
        """
        if self._repository.get_by_email(payload.email) is not None:
            logger.info("Registration blocked: email already registered.")
            raise EmailAlreadyRegisteredError("An account with this email already exists.")

        sending_email = self._resolve_sending_email(payload.sending_email, payload.email)
        if (
            sending_email is not None
            and self._repository.get_by_sending_email(sending_email) is not None
        ):
            logger.info("Registration blocked: sending_email already in use.")
            raise SendingEmailAlreadyInUseError(
                f"The sending address '{sending_email}' is already in use. "
                "Please choose another."
            )

        hashed = self._hasher.hash(payload.password)
        user = self._repository.create(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hashed,
            phone_number=payload.phone_number,
            sending_email=sending_email,
        )
        logger.info("Registered new user id=%s (sending_email=%s).", user.id, user.sending_email)
        return user

    def suggest_sending_email(self, email: str) -> str | None:
        """Return the default outbound address derived from a login email.

        The local part before ``@`` in ``email`` is combined with the
        configured outbound domain (per the active provider). Returns ``None``
        when no outbound domain is configured. Does **not** check uniqueness —
        that is :meth:`is_sending_email_available` / the registration guard.

        Args:
            email: The user's login email address.

        Returns:
            The suggested ``{local}@{domain}`` address, or ``None``.
        """
        return self._resolve_sending_email(None, email)

    def is_sending_email_available(self, sending_email: str) -> bool:
        """Return whether a resolved sending address is free to claim.

        Args:
            sending_email: The fully qualified address to check.

        Returns:
            ``True`` if no existing user holds this address.
        """
        return self._repository.get_by_sending_email(sending_email) is None

    def _resolve_sending_email(self, chosen: str | None, email: str) -> str | None:
        """Resolve the outbound address to store for a registering user.

        The local part is taken from ``chosen`` when the user supplied/edited
        one, otherwise from ``email``; it is sanitised and re-anchored to the
        configured outbound domain so a user can never point their sending
        address at a domain the app does not control. Returns ``None`` when no
        settings/outbound domain is configured (the app then runs without
        per-user sending addresses / new-thread inbound matching).

        Args:
            chosen: The address the user confirmed on the form, if any.
            email: The user's login email, used as the fallback source of the
                local part.

        Returns:
            A fully qualified ``{local}@{domain}`` address, or ``None``.
        """
        if self._settings is None:
            return None
        domain = self._settings.default_outbound_domain
        if not domain:
            return None
        local = self._sanitize_local_part(chosen or email)
        return f"{local}@{domain}"

    @staticmethod
    def _sanitize_local_part(value: str) -> str:
        """Extract and clean the local part from an email or bare local part.

        Everything after the first ``@`` is discarded, the result is lowercased
        and stripped of characters outside ``[a-z0-9._+-]``. Falls back to
        ``"user"`` if nothing usable remains.

        Args:
            value: A full email address or a bare local part.

        Returns:
            A safe, non-empty local part.
        """
        local = (value or "").split("@", 1)[0].strip().lower()
        local = _LOCAL_PART_ALLOWED.sub("", local).strip("._+-")
        return local or "user"

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
