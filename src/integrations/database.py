"""Database engine and session management.

The :class:`Database` class encapsulates SQLAlchemy engine creation and session
handling behind a single object (a lightweight *facade*). A module-level
:func:`get_database` accessor returns a process-wide singleton so the whole app
shares one connection pool.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings, get_settings
from src.domain.models import Base
from src.observability import get_logger

logger = get_logger(__name__)

# Retry policy for the initial connection — a freshly started Postgres container
# may not accept connections immediately (coding standards: every external call
# gets a timeout and a bounded retry policy).
_MAX_CONNECT_RETRIES = 10
_RETRY_BACKOFF_SECONDS = 2.0


class Database:
    """Owns the SQLAlchemy engine and hands out scoped sessions.

    Args:
        settings: Application settings providing the database URL.
    """

    def __init__(self, settings: Settings) -> None:
        """Create the engine and session factory for the configured database."""
        self._settings = settings
        self._engine: Engine = self._create_engine(settings)
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self._engine, autoflush=False, expire_on_commit=False
        )

    @staticmethod
    def _create_engine(settings: Settings) -> Engine:
        """Build a SQLAlchemy engine, applying SQLite-specific tuning.

        For SQLite the parent directory is created and ``check_same_thread`` is
        disabled so the connection can be shared across FastAPI's threadpool.

        Args:
            settings: Application settings.

        Returns:
            A configured SQLAlchemy :class:`~sqlalchemy.Engine`.
        """
        if settings.is_sqlite:
            db_path = settings.database_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            return create_engine(
                settings.database_url,
                connect_args={"check_same_thread": False},
                echo=settings.debug and settings.environment == "development",
            )
        return create_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=False,
        )

    def create_all(self) -> None:
        """Create all tables, retrying while the database is still starting up.

        Raises:
            OperationalError: If the database is unreachable after the maximum
                number of retries.
        """
        last_error: OperationalError | None = None
        for attempt in range(1, _MAX_CONNECT_RETRIES + 1):
            try:
                Base.metadata.create_all(self._engine)
                logger.info("Database schema ready (attempt %d).", attempt)
                return
            except OperationalError as exc:  # pragma: no cover - timing dependent
                last_error = exc
                logger.warning(
                    "Database not ready (attempt %d/%d): %s",
                    attempt,
                    _MAX_CONNECT_RETRIES,
                    exc,
                )
                time.sleep(_RETRY_BACKOFF_SECONDS)
        assert last_error is not None
        logger.error("Database unreachable after %d attempts.", _MAX_CONNECT_RETRIES)
        raise last_error

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a transactional session, committing on success and rolling back on error.

        Yields:
            An active SQLAlchemy :class:`~sqlalchemy.orm.Session`.
        """
        db_session = self._session_factory()
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.close()


_database: Database | None = None


def get_database() -> Database:
    """Return the process-wide :class:`Database` singleton, creating it on first use.

    Returns:
        The shared :class:`Database` instance.
    """
    global _database
    if _database is None:
        _database = Database(get_settings())
    return _database
