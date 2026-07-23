"""The EmailExtractorAgent — reads a received email and extracts structured detail.

One agent, one responsibility (AgenticAI Rule 2): this agent reads a single
inbound supplier email (body + attachments), classifies it, and extracts the
fields defined in ``constants.py`` using the shared LLM client — nothing else.
It does not schedule work, decide *which* email to process, or update the
source email's processing status; the background ``worker`` module owns that
(orchestrator separate from agent, Rule 4).

It also handles its own failure (Rule 5): a failed LLM call or an unparsable
response is caught, recorded as a ``failed`` extraction (with the original
content preserved for manual review), and reported back as ``False`` — the agent
never lets an exception escape into the worker loop.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.config import Settings
from src.integrations.llm import LLMClient, LLMGenerationError
from src.modules.email_delivery.models import Email
from src.modules.email_extraction.attachments_reader import (
    AttachmentContent,
    AttachmentRef,
    read_attachments,
)
from src.modules.email_extraction.enums import ExtractedEmailType, ExtractionStatus
from src.modules.email_extraction.exceptions import EmailExtractionError
from src.modules.email_extraction.prompts import build_prompts
from src.modules.email_extraction.repository import ExtractionRepository
from src.modules.email_extraction.schemas import ExtractionResult
from src.observability import get_logger

logger = get_logger(__name__)


def _parse_result(raw: str) -> ExtractionResult:
    """Parse the model's response into a validated :class:`ExtractionResult`.

    Tolerates markdown code fences and coerces an unknown ``email_type`` to
    ``general`` rather than failing, so a slightly-off classification does not
    lose the whole extraction.

    Args:
        raw: The raw text returned by the LLM.

    Returns:
        The validated extraction result.

    Raises:
        EmailExtractionError: If the text is not a valid JSON object or does not
            match the expected schema.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EmailExtractionError("The model did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise EmailExtractionError("The model's JSON response was not an object.")

    valid_types = {member.value for member in ExtractedEmailType}
    if parsed.get("email_type") not in valid_types:
        parsed["email_type"] = ExtractedEmailType.GENERAL.value

    try:
        return ExtractionResult.model_validate(parsed)
    except ValidationError as exc:
        raise EmailExtractionError(
            "The model's response did not match the expected schema."
        ) from exc


class EmailExtractorAgent:
    """Extracts structured details from one received email and stores them.

    Args:
        llm_client: Shared client used to call the underlying language model.
        settings: Application settings (locates stored attachment files, and
            supplies the model id recorded for traceability).
    """

    def __init__(self, llm_client: LLMClient, settings: Settings) -> None:
        """Store the injected collaborators."""
        self._llm_client = llm_client
        self._settings = settings

    def extract_and_store(self, *, session: Session, email: Email) -> bool:
        """Extract details from ``email`` and persist an :class:`ExtractedEmail`.

        Runs within the worker tick's transaction (the passed ``session``), so
        the stored extraction commits atomically with the worker's status
        update. Never raises — a failure is recorded as a ``failed`` extraction
        and reported as ``False``.

        Args:
            session: The active session for this worker tick.
            email: The received email to process.

        Returns:
            ``True`` if extraction completed and was stored; ``False`` if it
            failed (a ``failed`` record is still stored either way).
        """
        repository = ExtractionRepository(session)

        # Idempotency: never extract the same email twice (Rule: idempotency
        # where it matters). A re-picked email short-circuits without an LLM call.
        if repository.exists_for_email(email.id):
            logger.info("Extraction already exists for email %s; skipping.", email.id)
            return True

        conversation = email.conversation
        user_id: uuid.UUID = conversation.user_id
        supplier_email = conversation.supplier_email
        original_subject = email.subject or ""
        original_body = email.body_text or email.body_html or ""
        attachment_snapshots = self._attachment_snapshots(email)
        attachments = read_attachments(self._settings, self._attachment_refs(email))

        try:
            result = self._run(original_subject, original_body, attachments)
        except EmailExtractionError as exc:
            logger.warning("Extraction failed for email %s: %s", email.id, exc)
            repository.save(
                user_id=user_id,
                conversation_id=email.conversation_id,
                email_id=email.id,
                email_type=ExtractedEmailType.GENERAL,
                status=ExtractionStatus.FAILED,
                summary="",
                supplier_email=supplier_email,
                original_subject=original_subject,
                original_body=original_body,
                original_attachments=attachment_snapshots,
                details={},
                confidence=None,
                error=str(exc),
                model=self._settings.llm_model,
            )
            return False

        repository.save(
            user_id=user_id,
            conversation_id=email.conversation_id,
            email_id=email.id,
            email_type=result.email_type,
            status=ExtractionStatus.COMPLETED,
            summary=result.summary,
            supplier_email=supplier_email,
            original_subject=original_subject,
            original_body=original_body,
            original_attachments=attachment_snapshots,
            details=result.details,
            confidence=result.confidence,
            error=None,
            model=self._settings.llm_model,
        )
        logger.info(
            "Extracted email id=%s type=%s (conversation=%s)",
            email.id,
            result.email_type.value,
            email.conversation_id,
        )
        return True

    def _run(self, subject: str, body: str, attachments: AttachmentContent) -> ExtractionResult:
        """Call the LLM and parse its response into an :class:`ExtractionResult`.

        The text prompt goes first; any native media (PDF/image) blocks the
        reader produced are appended so Claude reads them as part of the same
        user turn.

        Args:
            subject: The email subject.
            body: The email body.
            attachments: Pre-rendered attachment content (text + media blocks).

        Returns:
            The validated extraction result.

        Raises:
            EmailExtractionError: If the LLM call fails after retries or its
                response cannot be parsed/validated.
        """
        system_prompt, user_prompt = build_prompts(
            subject=subject, body=body, attachments_text=attachments.text
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        content.extend(attachments.media_blocks)
        try:
            raw = self._llm_client.generate_multimodal(system_prompt=system_prompt, content=content)
        except LLMGenerationError as exc:
            raise EmailExtractionError("The extraction LLM call failed.") from exc
        return _parse_result(raw)

    @staticmethod
    def _attachment_refs(email: Email) -> list[AttachmentRef]:
        """Map an email's attachment rows to reader refs."""
        return [
            AttachmentRef(
                filename=attachment.filename,
                url=attachment.url,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
            )
            for attachment in email.attachments
        ]

    @staticmethod
    def _attachment_snapshots(email: Email) -> list[dict[str, Any]]:
        """Build the JSON attachment snapshot stored on the extraction row."""
        return [
            {
                "filename": attachment.filename,
                "url": attachment.url,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
            }
            for attachment in email.attachments
        ]
