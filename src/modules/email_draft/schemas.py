"""Pydantic schemas for the email-draft module.

Per the coding standards' contract-first rule, the LLM's raw output
(:class:`GeneratedDraft`) is a separate, narrower contract from the
persisted/API shape (:class:`EmailDraftRead`) — the model only ever gets to
supply ``subject``/``body``; every other field (id, status, timestamps) is
owned by this service, never by the LLM response.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.modules.email_draft.enums import DraftStatus
from src.modules.email_patterns import EmailType


class EmailDraftGenerateRequest(BaseModel):
    """Input contract for drafting a new email.

    Attributes:
        query_text: The user's natural-language request — a freshly typed
            request, a follow-up query, or a previously generated/saved
            sample query. Any kind of query is accepted; the email type
            (path parameter) determines which skill is loaded to draft it.
    """

    query_text: str = Field(min_length=1)


class GeneratedDraft(BaseModel):
    """The raw shape produced by the LLM for one drafting call.

    Attributes:
        subject: The email subject line the model wrote.
        body: The full email body the model wrote.
    """

    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


class EmailDraftUpdate(BaseModel):
    """Input contract for a human edit to an existing draft.

    Every field is optional — only the fields actually supplied are changed;
    omitted fields keep their current value. This can never change
    ``status``: verifying a draft is a separate, explicit action (see
    ``POST /email-drafts/{id}/verify``), never a side effect of an edit.

    Attributes:
        recipient: The recipient's email address.
        subject: The (possibly human-edited) subject line.
        body: The (possibly human-edited) body.
    """

    recipient: EmailStr | None = None
    subject: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)


class EmailDraftRead(BaseModel):
    """Output contract for a persisted drafted email.

    Attributes:
        id: The draft's id.
        email_type: Which email pattern this draft was generated for.
        query_text: The natural-language request the draft was generated from.
        recipient: The recipient's email address, if set.
        subject: The current subject line.
        body: The current body.
        status: Lifecycle state — ``"draft"`` until a human verifies it.
        created_at: When the draft was generated.
        updated_at: When the draft was last edited or verified.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_type: EmailType
    query_text: str
    recipient: str | None
    subject: str
    body: str
    status: DraftStatus
    created_at: datetime
    updated_at: datetime
