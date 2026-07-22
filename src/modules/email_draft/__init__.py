"""Email-draft module — LLM-backed email drafting, review, and history.

Given a natural-language query and an email type, loads the matching
``skills/emails-patterns/*/SKILL.md`` skill spec (via the shared
``email_patterns`` catalog) and drafts a complete email (subject + body).
Every draft is persisted immediately with status ``"draft"`` so it survives a
reload and shows up in the dashboard's draft history — the same
"generate → save → list" pattern ``modules/sample_data`` uses.

Drafting is a single, narrow responsibility: it never sends an email and it
never marks a draft "verified" itself. Verifying a draft is a separate,
explicit human action (``EmailDraftService.verify``, exposed only via
``POST /email-drafts/{id}/verify``) — the generation and edit code paths can
never reach that status. This mirrors Rule 6 ("Approval Gates Are Reusable
Infrastructure" — approval is a human action, never something an agent
writes for itself) from ``AgenticAI_Rules_Diagram.md``, adapted to this
codebase's service/repository architecture rather than LangGraph's
``interrupt()``.

    enums.py       -- DraftStatus (draft / verified)
    models.py      -- DraftedEmail ORM model
    schemas.py     -- Pydantic request/response contracts
    exceptions.py  -- typed domain errors
    prompts.py     -- builds LLM prompts from the skill files on disk
    repository.py  -- DraftedEmail data access
    service.py     -- EmailDraftService (draft, persist, list, modify, verify)
    deps.py        -- FastAPI dependency wiring
    router.py      -- JSON API (/api/v1/email-drafts...)

``api_router`` is the piece the app factory mounts.
"""

from src.modules.email_draft.router import router as api_router

__all__ = ["api_router"]
