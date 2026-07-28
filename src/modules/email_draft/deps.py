"""FastAPI dependency wiring for the email-draft module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.integrations.database import get_db_session
from src.integrations.llm import LLMClient, get_llm_client
from src.modules.email_draft.repository import EmailDraftRepository
from src.modules.email_draft.service import EmailDraftService


def get_email_draft_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> EmailDraftRepository:
    """Return a request-scoped :class:`EmailDraftRepository`."""
    return EmailDraftRepository(session)


def get_email_draft_service(
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    repository: Annotated[EmailDraftRepository, Depends(get_email_draft_repository)],
) -> EmailDraftService:
    """Compose an :class:`EmailDraftService` for the current request.

    Args:
        llm_client: Shared LLM client.
        repository: Request-scoped drafted-email data access.

    Returns:
        A fully wired :class:`EmailDraftService`.
    """
    return EmailDraftService(llm_client, repository)


EmailDraftServiceDep = Annotated[EmailDraftService, Depends(get_email_draft_service)]
