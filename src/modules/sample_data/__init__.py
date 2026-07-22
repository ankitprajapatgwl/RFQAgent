"""Sample-data module — LLM-backed sample email-query generation and history.

Self-contained: everything needed to understand or change this feature lives
in this one folder.

    enums.py           -- EmailType
    models.py           -- SavedSampleQuery ORM model
    schemas.py          -- Pydantic request/response contracts
    exceptions.py        -- typed domain errors
    prompts.py             -- builds LLM prompts from the skill files on disk
    llm_client.py           -- thin Anthropic SDK wrapper (timeout + retry)
    repository.py             -- SavedSampleQuery data access
    service.py                 -- SampleQueryService (generate, persist, list)
    deps.py                     -- FastAPI dependency wiring
    router.py                    -- JSON API (/api/v1/email-types, /api/v1/sample-queries)

``api_router`` is the piece the app factory mounts.
"""

from src.modules.sample_data.router import router as api_router

__all__ = ["api_router"]
