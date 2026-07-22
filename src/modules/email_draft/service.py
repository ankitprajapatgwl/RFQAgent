"""Email drafting, review, and verification.

:class:`EmailDraftService` orchestrates prompt-building, the shared LLM
client, and persistence to draft a real email (subject + body) for one of the
``skills/emails-patterns`` email types from a user-supplied natural-language
query, and saves it immediately so it survives a reload and shows up in the
dashboard's draft history — the same "generate then save" pattern
``modules/sample_data`` uses for sample queries.

One agent, one responsibility (see ``AgenticAI_Rules_Diagram.md``, Rule 2):
this service only drafts. It never sends an email, and — critically — it can
never mark a draft "verified" itself. Verifying a draft is a distinct human
approval action (:meth:`verify`), reachable only from a dedicated endpoint,
never a side effect of generation or a modify. That mirrors Rule 6 (approval
gates are human-only infrastructure, never something an agent writes for
itself) adapted to this codebase's service/repository architecture rather
than LangGraph's ``interrupt()``.
"""

from __future__ import annotations

import json
import uuid

from pydantic import ValidationError

from src.integrations.llm import LLMClient, LLMGenerationError
from src.modules.email_draft.enums import DraftStatus
from src.modules.email_draft.exceptions import EmailDraftGenerationError, EmailDraftNotFoundError
from src.modules.email_draft.models import DraftedEmail
from src.modules.email_draft.prompts import build_prompts
from src.modules.email_draft.repository import EmailDraftRepository
from src.modules.email_draft.schemas import GeneratedDraft
from src.modules.email_patterns import EmailType
from src.observability import get_logger

logger = get_logger(__name__)


def _parse_json_object(raw: str) -> dict[str, object]:
    """Parse the model's response into a JSON object, tolerating code fences.

    Args:
        raw: The raw text returned by the LLM.

    Returns:
        The decoded JSON object.

    Raises:
        EmailDraftGenerationError: If the text is not a valid JSON object.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EmailDraftGenerationError("The model did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise EmailDraftGenerationError("The model's JSON response was not an object.")
    return parsed


class EmailDraftService:
    """Drafts, persists, and manages review state for email-drafting skills.

    Args:
        llm_client: Shared client used to call the underlying language model.
        repository: Data access for drafted emails.
    """

    def __init__(self, llm_client: LLMClient, repository: EmailDraftRepository) -> None:
        """Store the injected collaborators."""
        self._llm_client = llm_client
        self._repository = repository

    def generate_and_save(
        self,
        *,
        user_id: uuid.UUID,
        email_type: EmailType,
        query_text: str,
        sender_name: str = "",
        sender_email: str = "",
        sender_role: str = "",
        company_name: str = "",
    ) -> DraftedEmail:
        """Draft one email from a query and persist it as a new draft.

        Loads the skill matching ``email_type``, asks the LLM to draft a
        complete email following it, and saves the result with status
        ``"draft"``. This method can never save any other status — every
        draft it produces awaits human review.

        Args:
            user_id: The requesting user's id — the saved draft's owner.
            email_type: Which email pattern to draft (selects the skill).
            query_text: The user's natural-language request — any kind of
                query (freshly typed, a follow-up, or a previously
                generated/saved sample query) is accepted as-is.
            sender_name: The signed-in user's name, used for the sign-off.
            sender_email: The signed-in user's email, used for the sign-off.
            sender_role: The signed-in user's role, used for the sign-off.
            company_name: The sender's company, used for the sign-off.

        Returns:
            The saved :class:`DraftedEmail`.

        Raises:
            EmailDraftGenerationError: If the LLM call fails or its response
                does not match the expected shape. Never raised as a bare
                exception from the underlying SDK — always translated here
                so the caller (and the pipeline) never crashes on a bad or
                failed generation.
        """
        system_prompt, user_prompt = build_prompts(
            email_type,
            query_text,
            sender_name=sender_name,
            sender_email=sender_email,
            sender_role=sender_role,
            company_name=company_name,
        )
        try:
            raw = self._llm_client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        except LLMGenerationError as exc:
            logger.warning("Email draft generation failed for %s: %s", email_type, exc)
            raise EmailDraftGenerationError("Could not draft an email.") from exc

        payload = _parse_json_object(raw)
        try:
            generated = GeneratedDraft.model_validate(payload)
        except ValidationError as exc:
            raise EmailDraftGenerationError(
                "The model's response did not match the expected schema."
            ) from exc

        return self._repository.save(
            user_id=user_id,
            email_type=email_type,
            query_text=query_text,
            subject=generated.subject,
            body=generated.body,
        )

    def list_saved(
        self, *, user_id: uuid.UUID, email_type: EmailType | None = None
    ) -> list[DraftedEmail]:
        """Return a user's drafted emails, newest first.

        Args:
            user_id: The requesting user's id.
            email_type: Optional email pattern to filter by. When ``None``
                (the default), the user's complete draft history is returned.

        Returns:
            Matching :class:`DraftedEmail` rows, most recent first.
        """
        return self._repository.list_for_user(user_id=user_id, email_type=email_type)

    def get_saved(self, *, user_id: uuid.UUID, draft_id: uuid.UUID) -> DraftedEmail:
        """Return one drafted email owned by the given user.

        Args:
            user_id: The requesting user's id.
            draft_id: The draft's id.

        Returns:
            The matching :class:`DraftedEmail`.

        Raises:
            EmailDraftNotFoundError: If no such draft exists for this user.
        """
        draft = self._repository.get_for_user(user_id=user_id, draft_id=draft_id)
        if draft is None:
            raise EmailDraftNotFoundError(f"No draft {draft_id} found for this user.")
        return draft

    def modify(
        self,
        *,
        user_id: uuid.UUID,
        draft_id: uuid.UUID,
        recipient: str | None = None,
        subject: str | None = None,
        body: str | None = None,
    ) -> DraftedEmail:
        """Apply a human edit to an existing draft.

        Only fields whose value actually changes are written; omitted or
        unchanged ones are left alone. Editing can never *verify* a draft —
        but the reverse is enforced: editing a draft that was already verified
        returns it to ``"draft"`` so content changed after approval can never
        be sent without a fresh, explicit re-verification (see :meth:`verify`).

        Args:
            user_id: The requesting user's id (drafts are edited by their owner only).
            draft_id: The draft's id.
            recipient: New recipient email address, if changed.
            subject: New subject line, if changed.
            body: New body, if changed.

        Returns:
            The updated :class:`DraftedEmail`.

        Raises:
            EmailDraftNotFoundError: If no such draft exists for this user.
        """
        draft = self.get_saved(user_id=user_id, draft_id=draft_id)
        changes: dict[str, object] = {}
        if recipient is not None and recipient != draft.recipient:
            changes["recipient"] = recipient
        if subject is not None and subject != draft.subject:
            changes["subject"] = subject
        if body is not None and body != draft.body:
            changes["body"] = body
        if not changes:
            return draft
        # A real edit invalidates a prior approval: drop back to "draft" so the
        # human must verify the new content before it can be sent.
        if draft.status == DraftStatus.VERIFIED.value:
            changes["status"] = DraftStatus.DRAFT.value
        return self._repository.update(draft, **changes)

    def verify(self, *, user_id: uuid.UUID, draft_id: uuid.UUID) -> DraftedEmail:
        """Mark a draft as verified — the sole human-approval action.

        This is the only method in the module that can set
        ``status = "verified"``. Neither :meth:`generate_and_save` nor
        :meth:`modify` can reach it, so a draft only ever becomes verified
        through an explicit, separate call to this method — reflecting Rule
        6's hard rule that approval is a human action an agent can never
        grant itself.

        Args:
            user_id: The requesting user's id (drafts are verified by their owner only).
            draft_id: The draft's id.

        Returns:
            The updated :class:`DraftedEmail`, with ``status = "verified"``.

        Raises:
            EmailDraftNotFoundError: If no such draft exists for this user.
        """
        draft = self.get_saved(user_id=user_id, draft_id=draft_id)
        return self._repository.update(draft, status=DraftStatus.VERIFIED.value)
