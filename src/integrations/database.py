"""Database engine and session management.

The :class:`Database` class encapsulates SQLAlchemy engine creation and session
handling behind a single object (a lightweight *facade*). A module-level
:func:`get_database` accessor returns a process-wide singleton so the whole app
shares one connection pool.

:class:`Base` is the single declarative base shared by every module's ORM
models (``modules/auth/models.py``, ``modules/sample_data/models.py``, ...) so
:meth:`Database.create_all` creates every module's tables in one call. It
lives here — shared infrastructure — rather than inside any one module, to
keep modules independent of each other.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import Settings, get_settings
from src.observability import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base class shared by every module's ORM models."""

# Retry policy for the initial connection — a freshly started Postgres container
# may not accept connections immediately (coding standards: every external call
# gets a timeout and a bounded retry policy).
_MAX_CONNECT_RETRIES = 10
_RETRY_BACKOFF_SECONDS = 2.0

# Additive columns introduced after the initial schema shipped. ``create_all``
# only creates missing *tables*, never new columns on an existing one, and this
# project carries no Alembic setup — so a plain SQLite/Postgres ``ADD COLUMN``
# is applied idempotently at startup. Each entry is ``table -> {column:
# column_type_ddl}``; extend it when a column is added to a model that may
# already exist in a deployed database. Prefer nullable, no-default columns
# (portable everywhere); a ``NOT NULL DEFAULT <const>`` is also portable
# (SQLite + Postgres) and backfills existing rows — used for
# ``email_messages.processing_status`` so replies stored before the worker
# shipped start out ``pending`` and get picked up.
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "users": {"phone_number": "VARCHAR(32)"},
    "email_messages": {"processing_status": "VARCHAR(16) NOT NULL DEFAULT 'pending'"},
}


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
                self._apply_additive_columns()
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

    def _apply_additive_columns(self) -> None:
        """Add any nullable columns from :data:`_ADDITIVE_COLUMNS` that are missing.

        A tiny, forward-only migration step covering the one thing
        ``create_all`` cannot do — add a column to a table that already exists
        in a deployed database. Only additive, nullable columns are handled, so
        the statement is safe to run on every startup and a no-op once applied.
        Missing tables are skipped (``create_all`` will have just made them with
        the column already present).
        """
        inspector = inspect(self._engine)
        existing_tables = set(inspector.get_table_names())
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for column, ddl_type in columns.items():
                if column in present:
                    continue
                try:
                    with self._engine.begin() as connection:
                        connection.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
                        )
                    logger.info("Added missing column %s.%s.", table, column)
                except SQLAlchemyError as exc:  # pragma: no cover - defensive
                    logger.error("Could not add column %s.%s: %s", table, column, exc)

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


def get_db_session() -> Iterator[Session]:
    """Yield a request-scoped session, committing on success.

    Shared by every module's ``deps.py`` — the surrounding
    :meth:`Database.session` context manager commits when the request handler
    returns normally and rolls back if it raises.

    Yields:
        An active SQLAlchemy :class:`~sqlalchemy.orm.Session`.
    """
    with get_database().session() as session:
        yield session
