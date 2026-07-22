"""Unit tests for the authentication service orchestration."""

import pytest
from src.modules.auth.enums import UserRole
from src.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from src.modules.auth.schemas import UserCreate
from src.modules.auth.service import AuthService


def _new_user_payload(email: str = "ada@example.com") -> UserCreate:
    return UserCreate(email=email, full_name="Ada Lovelace", password="password123")


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
