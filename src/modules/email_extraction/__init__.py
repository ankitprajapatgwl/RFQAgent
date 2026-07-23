"""Email-extraction module — the EmailExtractorAgent + stored extraction history.

The background ``worker`` hands each received supplier email to the
:class:`EmailExtractorAgent`, which reads the body and attachments, extracts
structured details with the shared LLM client, and stores them as an
``ExtractedEmail`` row (original content + extracted details) bound to the
conversation. The dashboard reads those rows back for the RFQ Monitoring view
and the dispatch-history JSON popup.

    enums.py               -- ExtractedEmailType, ExtractionStatus
    constants.py           -- editable per-type extraction structures (Requirement 5)
    exceptions.py          -- EmailExtractionError
    schemas.py             -- LLM-output + API contracts
    models.py              -- ExtractedEmail ORM model (the new table, Requirement 1)
    attachments_reader.py  -- reads stored attachment files back into text
    prompts.py             -- builds the extraction prompt from the constants
    repository.py          -- ExtractedEmail data access
    agent.py               -- EmailExtractorAgent (classify + extract + store)
    service.py             -- read-side service for the dashboard
    deps.py                -- FastAPI dependency wiring
    router.py              -- JSON API (/api/v1/email-extraction/...)

``api_router`` is mounted by the app factory; ``EmailExtractorAgent`` is wired
into the worker by ``src.modules.worker.runner``.
"""

from src.modules.email_extraction.agent import EmailExtractorAgent
from src.modules.email_extraction.router import router as api_router

__all__ = ["EmailExtractorAgent", "api_router"]
