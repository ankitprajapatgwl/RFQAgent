"""FastAPI dependency wiring for the sample-data module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.integrations.database import get_db_session
from src.integrations.llm import LLMClient, get_llm_client
from src.modules.sample_data.repository import SampleQueryRepository
from src.modules.sample_data.service import SampleQueryService


def get_sample_query_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> SampleQueryRepository:
    """Return a request-scoped :class:`SampleQueryRepository`."""
    return SampleQueryRepository(session)


def get_sample_query_service(
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    repository: Annotated[SampleQueryRepository, Depends(get_sample_query_repository)],
) -> SampleQueryService:
    """Compose a :class:`SampleQueryService` for the current request.

    Args:
        llm_client: Shared LLM client.
        repository: Request-scoped saved-sample data access.

    Returns:
        A fully wired :class:`SampleQueryService`.
    """
    return SampleQueryService(llm_client, repository)


SampleQueryServiceDep = Annotated[SampleQueryService, Depends(get_sample_query_service)]
