"""Pydantic schemas for the sample-data module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.modules.email_patterns import EmailType


class GeneratedSample(BaseModel):
    """The raw shape produced by the LLM for one generation call.

    Attributes:
        fields: The mandatory (and any volunteered optional) field values the
            model invented, keyed by field name.
        query_text: A ready-to-use natural-language request a user could send
            to an email-drafting agent, containing every mandatory field.
    """

    fields: dict[str, str] = Field(min_length=1)
    query_text: str = Field(min_length=1)


class SavedSampleQueryRead(BaseModel):
    """Output contract for a persisted sample query.

    Attributes:
        id: The saved record's id.
        email_type: Which email pattern this sample was generated for.
        fields: The field values that make up the sample.
        query_text: The generated natural-language request.
        created_at: When the sample was generated.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email_type: EmailType
    fields: dict[str, str]
    query_text: str
    created_at: datetime
