"""Pydantic schemas for the sample email-query generation feature."""

from pydantic import BaseModel, Field

from src.domain.enums import EmailType


class EmailTypeOption(BaseModel):
    """A selectable email pattern shown in the dashboard's picker.

    Attributes:
        value: The underlying :class:`EmailType` value.
        label: Human-readable label for display.
    """

    value: EmailType
    label: str


class SampleQueryResponse(BaseModel):
    """Output contract for a generated sample email-drafting query.

    Attributes:
        email_type: Which email pattern this sample was generated for.
        fields: The mandatory (and any volunteered optional) field values the
            model invented, keyed by field name.
        query_text: A ready-to-use natural-language request a user could send
            to an email-drafting agent, containing every mandatory field.
    """

    email_type: EmailType
    fields: dict[str, str] = Field(min_length=1)
    query_text: str = Field(min_length=1)
