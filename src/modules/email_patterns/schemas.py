"""Pydantic schemas shared by every module that lists email patterns."""

from pydantic import BaseModel

from src.modules.email_patterns.enums import EmailType


class EmailTypeOption(BaseModel):
    """A selectable email pattern shown in a dashboard picker.

    Attributes:
        value: The underlying :class:`EmailType` value.
        label: Human-readable label for display.
    """

    value: EmailType
    label: str
