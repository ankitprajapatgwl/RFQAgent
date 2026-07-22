"""Shared email-pattern catalog — the vocabulary every email-related module builds on.

    enums.py    -- EmailType, the single enum identifying which
                   ``skills/emails-patterns/`` folder applies
    catalog.py  -- EMAIL_TYPE_LABELS + raw skill-spec/RFQ-checklist file readers
    schemas.py  -- EmailTypeOption, the picker-display contract

Deliberately the one non-self-contained piece shared between the
``sample_data`` and ``email_draft`` modules: which email patterns exist and
where their ``SKILL.md`` files live is a single fact, owned once here, rather
than duplicated (and risking drift) in every module that needs it.
"""

from src.modules.email_patterns.catalog import EMAIL_TYPE_LABELS, read_rfq_fields, read_skill_spec
from src.modules.email_patterns.enums import EmailType
from src.modules.email_patterns.schemas import EmailTypeOption

__all__ = [
    "EMAIL_TYPE_LABELS",
    "EmailType",
    "EmailTypeOption",
    "read_rfq_fields",
    "read_skill_spec",
]
