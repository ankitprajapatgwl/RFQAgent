"""Pydantic request/response contracts for the email-extraction module.

Every value crossing a boundary is validated against one of these models rather
than a loose ``dict`` (the contract-first rule): the LLM's raw output is
validated into :class:`ExtractionResult` before it is ever persisted, and stored
rows are mapped to the ``*Read`` shapes via ``from_attributes``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.email_extraction.enums import ExtractedEmailType, ExtractionStatus


class ExtractionResult(BaseModel):
    """The validated shape the LLM must return for one extraction call.

    Attributes:
        email_type: The classified inbound email type.
        summary: One or two sentence plain-language summary of the email.
        details: The extracted field values, keyed by the field names defined
            for the classified type (plus the common fields). Missing values
            are omitted or ``null`` rather than invented.
        confidence: Optional self-reported confidence in ``[0, 1]``.
    """

    model_config = ConfigDict(extra="ignore")

    email_type: ExtractedEmailType = ExtractedEmailType.GENERAL
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None


class AttachmentSnapshot(BaseModel):
    """A lightweight snapshot of one attachment, stored with the extraction."""

    model_config = ConfigDict(from_attributes=True)

    filename: str
    url: str
    content_type: str | None = None
    size_bytes: int | None = None


class ExtractedEmailRead(BaseModel):
    """Output contract for one stored extraction record.

    Backs both the RFQ Monitoring list (Requirement 3) and the dispatch-history
    "view extracted JSON" popup (Requirement 4).

    Attributes:
        id: The extraction record's id.
        email_id: The received email this extraction was produced from.
        conversation_id: The conversation (thread) the email belongs to.
        email_type: The classified inbound email type.
        email_type_label: Human-readable label for ``email_type``.
        status: Whether the extraction completed or failed.
        summary: Short summary of the email.
        supplier_email: The supplier address (snapshot of the conversation's).
        original_subject: Subject line of the original message.
        original_body: Plain-text body of the original message.
        original_attachments: Snapshot of the message's attachments.
        details: The extracted field values.
        confidence: Self-reported confidence, if any.
        error: Failure reason when ``status == "failed"``, else ``None``.
        model: The LLM model id that produced the extraction.
        created_at: When the extraction was recorded.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_id: uuid.UUID
    conversation_id: uuid.UUID
    email_type: ExtractedEmailType
    email_type_label: str
    status: ExtractionStatus
    summary: str
    supplier_email: str
    original_subject: str
    original_body: str
    original_attachments: list[AttachmentSnapshot] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    error: str | None = None
    model: str | None = None
    created_at: datetime
