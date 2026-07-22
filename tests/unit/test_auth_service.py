"""Unit tests for the authentication service orchestration."""

import pytest
from sqlalchemy.orm import Session
from src.config.settings import Settings
from src.modules.auth.enums import UserRole
from src.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    SendingEmailAlreadyInUseError,
)
from src.modules.auth.password_hasher import BcryptPasswordHasher
from src.modules.auth.repository import UserRepository
from src.modules.auth.schemas import UserCreate
from src.modules.auth.service import AuthService
from src.modules.auth.token_service import TokenService

_DOMAIN = "mail.example.com"


def _new_user_payload(email: str = "ada@example.com") -> UserCreate:
    return UserCreate(email=email, full_name="Ada Lovelace", password="password123")


@pytest.fixture
def auth_service_with_domain(
    db_session: Session, password_hasher: BcryptPasswordHasher
) -> AuthService:
    """An auth service whose settings configure an outbound sending domain."""
    settings = Settings(
        database_url="sqlite:///:memory:",
        jwt_secret_key="test-secret-key-for-unit-tests-only",
        engagelab_outbound_domain=_DOMAIN,
    )
    return AuthService(
        UserRepository(db_session), password_hasher, TokenService(settings), settings
    )


def test_register_creates_user_with_default_role(auth_service: AuthService) -> None:
    user = auth_service.register(_new_user_payload())
    assert user.id is not None
    assert user.email == "ada@example.com"
    assert user.role is UserRole.BUYER
    assert user.hashed_password != "password123"


def test_register_normalizes_email(auth_service: AuthService) -> None:
    user = auth_service.register(_new_user_payload(email="ADA@Example.com"))
    assert user.email == "ada@example.com"


def test_register_duplicate_email_raises(auth_service: AuthService) -> None:
    auth_service.register(_new_user_payload())
    with pytest.raises(EmailAlreadyRegisteredError):
        auth_service.register(_new_user_payload(email="ADA@example.com"))


def test_authenticate_succeeds_with_correct_password(auth_service: AuthService) -> None:
    auth_service.register(_new_user_payload())
    user = auth_service.authenticate("ada@example.com", "password123")
    assert user.email == "ada@example.com"


def test_authenticate_wrong_password_raises(auth_service: AuthService) -> None:
    auth_service.register(_new_user_payload())
    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate("ada@example.com", "wrong-password")


def test_authenticate_unknown_email_raises(auth_service: AuthService) -> None:
    with pytest.raises(InvalidCredentialsError):
        auth_service.authenticate("nobody@example.com", "whatever12")


def test_authenticate_inactive_user_raises(auth_service: AuthService) -> None:
    user = auth_service.register(_new_user_payload())
    user.is_active = False
    with pytest.raises(InactiveUserError):
        auth_service.authenticate("ada@example.com", "password123")


def test_login_returns_token(auth_service: AuthService) -> None:
    auth_service.register(_new_user_payload())
    user, token = auth_service.login("ada@example.com", "password123")
    assert token.token_type == "bearer"
    assert token.access_token
    assert token.expires_in > 0
    assert user.email == "ada@example.com"


def test_resolve_user_from_token_roundtrip(auth_service: AuthService) -> None:
    registered = auth_service.register(_new_user_payload())
    _, token = auth_service.login("ada@example.com", "password123")
    resolved = auth_service.resolve_user_from_token(token.access_token)
    assert resolved.id == registered.id


def test_resolve_user_from_invalid_token_raises(auth_service: AuthService) -> None:
    with pytest.raises(InvalidTokenError):
        auth_service.resolve_user_from_token("garbage.token.value")


# ── Registration: phone number + sending-email derivation (reqs 1 & 2) ────────


def test_register_stores_phone_number(auth_service: AuthService) -> None:
    payload = UserCreate(
        email="ada@example.com",
        full_name="Ada Lovelace",
        password="password123",
        phone_number="+1 555 0100",
    )
    user = auth_service.register(payload)
    assert user.phone_number == "+1 555 0100"


def test_register_derives_sending_email_from_email_prefix(
    auth_service_with_domain: AuthService,
) -> None:
    payload = UserCreate(
        email="Jane.Doe@corp.com", full_name="Jane Doe", password="password123"
    )
    user = auth_service_with_domain.register(payload)
    assert user.sending_email == f"jane.doe@{_DOMAIN}"


def test_register_honours_confirmed_sending_email_local_part(
    auth_service_with_domain: AuthService,
) -> None:
    # The user edited the local part; the domain is always re-anchored.
    payload = UserCreate(
        email="jane@corp.com",
        full_name="Jane Doe",
        password="password123",
        sending_email="jane.custom@whatever.com",
    )
    user = auth_service_with_domain.register(payload)
    assert user.sending_email == f"jane.custom@{_DOMAIN}"


def test_register_duplicate_sending_email_raises(
    auth_service_with_domain: AuthService,
) -> None:
    auth_service_with_domain.register(
        UserCreate(email="jane.doe@a.com", full_name="Jane Doe", password="password123")
    )
    with pytest.raises(SendingEmailAlreadyInUseError):
        auth_service_with_domain.register(
            UserCreate(
                email="other@b.com",
                full_name="Other",
                password="password123",
                sending_email="jane.doe",
            )
        )


def test_suggest_and_availability(auth_service_with_domain: AuthService) -> None:
    assert auth_service_with_domain.suggest_sending_email("bob@x.com") == f"bob@{_DOMAIN}"
    assert auth_service_with_domain.is_sending_email_available(f"bob@{_DOMAIN}") is True
    auth_service_with_domain.register(
        UserCreate(email="bob@x.com", full_name="Bob", password="password123")
    )
    assert auth_service_with_domain.is_sending_email_available(f"bob@{_DOMAIN}") is False


def test_sending_email_none_when_domain_unconfigured(auth_service: AuthService) -> None:
    # The default fixture has no settings/domain — sending_email stays unset.
    user = auth_service.register(_new_user_payload())
    assert user.sending_email is None
    assert auth_service.suggest_sending_email("ada@example.com") is None
