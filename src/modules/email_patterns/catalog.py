"""Catalog of available email-drafting patterns and their on-disk specs.

Reads straight from ``skills/emails-patterns/`` (and the project's RFQ field
checklist) so every consumer's view of "which patterns exist" and "what a
pattern requires" always tracks whatever the skill files currently say — no
label or field list duplicated in Python.
"""

from __future__ import annotations

from src.config.settings import PROJECT_ROOT
from src.modules.email_patterns.enums import EmailType

SKILLS_DIR = PROJECT_ROOT / "skills" / "emails-patterns"
_RFQ_FIELDS_PATH = PROJECT_ROOT / "rfq_fields.md"

EMAIL_TYPE_LABELS: dict[EmailType, str] = {
    EmailType.APOLOGY: "Apology Email",
    EmailType.FOLLOW_UP: "Follow-Up Email",
    EmailType.NEGOTIATION: "Negotiation Email",
    EmailType.RFQ: "RFQ Email",
    EmailType.SAMPLE_REQUEST: "Sample Request Email",
}


def read_skill_spec(email_type: EmailType) -> str:
    """Return the raw contents of the given email type's ``SKILL.md``.

    Args:
        email_type: Which email pattern's skill spec to read.

    Returns:
        The full markdown text of the skill's ``SKILL.md``.
    """
    return (SKILLS_DIR / email_type.value / "SKILL.md").read_text(encoding="utf-8")


def read_rfq_fields() -> str:
    """Return the raw contents of the project's ``rfq_fields.md`` checklist."""
    return _RFQ_FIELDS_PATH.read_text(encoding="utf-8")
