"""FastAPI dependency wiring for the email-extraction module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.integrations.database import get_db_session
from src.modules.email_extraction.repository import ExtractionRepository
from src.modules.email_extraction.service import EmailExtractionService


def get_extraction_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> ExtractionRepository:
    """Return a request-scoped :class:`ExtractionRepository`."""
    return ExtractionRepository(session)


def get_extraction_service(
    repository: Annotated[ExtractionRepository, Depends(get_extraction_repository)],
) -> EmailExtractionService:
    """Compose an :class:`EmailExtractionService` for the current request.

    Args:
        repository: Request-scoped extraction data access.

    Returns:
        A fully wired :class:`EmailExtractionService`.
    """
    return EmailExtractionService(repository)


EmailExtractionServiceDep = Annotated[EmailExtractionService, Depends(get_extraction_service)]
