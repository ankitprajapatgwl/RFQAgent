"""Pydantic schemas for the sample-data module."""

from pydantic import BaseModel, Field


class SampleRfqRead(BaseModel):
    """One hard-coded sample RFQ scenario a user can pick from the list.

    Attributes:
        id: Stable slug identifying this sample (used as the React/DOM key).
        label: Short human-readable title shown in the picker.
        fields: The full RFQ field checklist values (see
            :data:`~src.modules.email_patterns.RFQ_FIELD_CATALOG`), keyed by
            field name.
        query_text: A ready-to-use natural-language request mentioning every
            field, kept for parity with what the RFQ-drafting flow expects.
    """

    id: str
    label: str
    fields: dict[str, str] = Field(min_length=1)
    query_text: str = Field(min_length=1)
