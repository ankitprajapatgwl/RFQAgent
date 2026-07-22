"""Unit tests for JWT creation and verification."""

import uuid

import pytest
from src.config.settings import Settings
from src.services import TokenService
from src.services.exceptions import InvalidTokenError


def test_roundtrip_encodes_and_decodes(token_service: TokenService) -> None:
    user_id = uuid.uuid4()
    token = token_service.create_access_token(user_id=user_id, email="user@example.com")
    payload = token_service.decode_access_token(token)
    assert payload.sub == str(user_id)
    assert payload.email == "user@example.com"


def test_expires_in_seconds_matches_settings(
    token_service: TokenService, settings: Settings
) -> None:
    assert token_service.expires_in_seconds == settings.access_token_expire_minutes * 60


def test_decode_rejects_garbage(token_service: TokenService) -> None:
    with pytest.raises(InvalidTokenError):
        token_service.decode_access_token("this.is.not.a.jwt")


def test_decode_rejects_token_signed_with_other_secret(settings: Settings) -> None:
    issuer = TokenService(settings)
    token = issuer.create_access_token(user_id=uuid.uuid4(), email="a@b.com")

    other_settings = settings.model_copy(update={"jwt_secret_key": "a-different-secret"})
    verifier = TokenService(other_settings)
    with pytest.raises(InvalidTokenError):
        verifier.decode_access_token(token)
