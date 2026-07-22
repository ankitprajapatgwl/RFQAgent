"""Shared pytest fixtures.

Tests run against an in-memory SQLite database so they are fast, isolated, and
require no external services (coding standards, file ``04`` §5). The bcrypt cost
factor is lowered to keep hashing snappy in tests.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from src.config.settings import Settings
from src.integrations.database import Base
from src.modules.auth.password_hasher import BcryptPasswordHasher
from src.modules.auth.repository import UserRepository
from src.modules.auth.service import AuthService
from src.modules.auth.token_service import TokenService
from src.modules.sample_data.repository import SampleQueryRepository


@pytest.fixture
def settings() -> Settings:
    """Return isolated test settings with a short-lived JWT secret."""
    return Settings(
        database_url="sqlite:///:memory:",
        jwt_secret_key="test-secret-key-for-unit-tests-only",
        access_token_expire_minutes=15,
        environment="testing",
        debug=False,
    )


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Yield a session bound to a fresh in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def password_hasher() -> BcryptPasswordHasher:
    """Return a bcrypt hasher with a low cost factor for fast tests."""
    return BcryptPasswordHasher(rounds=4)


@pytest.fixture
def token_service(settings: Settings) -> TokenService:
    """Return a token service configured from test settings."""
    return TokenService(settings)


@pytest.fixture
def auth_service(
    db_session: Session,
    password_hasher: BcryptPasswordHasher,
    token_service: TokenService,
) -> AuthService:
    """Return a fully wired auth service backed by the in-memory database."""
    return AuthService(UserRepository(db_session), password_hasher, token_service)


@pytest.fixture
def sample_query_repository(db_session: Session) -> SampleQueryRepository:
    """Return a sample-query repository backed by the in-memory database."""
    return SampleQueryRepository(db_session)
