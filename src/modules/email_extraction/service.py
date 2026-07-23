"""Read-side orchestration for stored email extractions.

:class:`EmailExtractionService` is the query surface the dashboard reads from —
the RFQ Monitoring list (every extraction for a user) and the dispatch-history
JSON popup (one conversation's extractions). The *writing* of extractions is the
:class:`~src.modules.email_extraction.agent.EmailExtractorAgent`'s job, driven by
the background worker; this service never generates anything, so it takes no LLM
client.
"""

from __future__ import annotations

import uuid

from src.modules.email_extraction.models import ExtractedEmail
from src.modules.email_extraction.repository import ExtractionRepository


class EmailExtractionService:
    """Read access to stored extractions for the dashboard.

    Args:
        repository: Request-scoped data access for stored extractions.
    """

    def __init__(self, repository: ExtractionRepository) -> None:
        """Store the injected repository."""
        self._repository = repository

    def list_for_user(self, *, user_id: uuid.UUID) -> list[ExtractedEmail]:
        """Return every extraction owned by the user, newest first.

        Args:
            user_id: The requesting user's id.

        Returns:
            The user's extractions, most recent first (the RFQ Monitoring list).
        """
        return self._repository.list_for_user(user_id=user_id)

    def list_for_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[ExtractedEmail]:
        """Return one conversation's extractions for the owning user.

        Args:
            user_id: The requesting user's id (ownership guard).
            conversation_id: The conversation whose extractions to return.

        Returns:
            Matching extractions, oldest first.
        """
        return self._repository.list_for_conversation(
            user_id=user_id, conversation_id=conversation_id
        )
