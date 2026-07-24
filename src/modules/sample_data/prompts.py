"""Prompt construction for sample email-drafting query generation.

Reads the relevant skill spec (and, for RFQ, the structured field catalog)
via the shared email-pattern catalog, so the generated sample data always
tracks whatever the skill files/catalog currently require — no field list
duplicated in code. For RFQ specifically, the model is required to return
every field in :data:`~src.modules.email_patterns.RFQ_FIELD_CATALOG` under its
exact key, so the generated JSON has a stable, predictable shape.
"""

from __future__ import annotations

from src.modules.email_patterns import (
    EMAIL_TYPE_LABELS,
    RFQ_FIELD_CATALOG,
    EmailType,
    read_skill_spec,
)

_SYSTEM_PROMPT_TEMPLATE = """\
You generate realistic, entirely fictional sample data for a "{label}", so a \
developer can test an email-drafting agent end-to-end.

Below is the skill specification the eventual email-drafting agent will \
follow. Pay close attention to its "Required information" section.

---
{skill_text}
---
{extra_context}
Invent one plausible, self-consistent, fictional scenario (invented company \
names, people, products, dates, and numbers — never real entities). Every \
field called out as required/mandatory above MUST be populated with a \
specific, concrete value — never a placeholder like "TBD", "N/A", or "TODO". \
Keep every field value SHORT: one compact phrase or sentence, not a \
multi-sentence paragraph — this is sample test data, not final copy.

Respond with ONLY a single JSON object — no markdown code fences, no \
commentary — matching exactly this shape:

{{"fields": {{"<field_name>": "<value>", ...}}, "query_text": "<a natural-\
language paragraph, written as if the buyer is typing a request to the \
email-drafting agent, that mentions every one of the fields above>"}}

Field names in "fields" must be lower_snake_case, derived from the required \
field names above.\
"""

_USER_PROMPT = "Generate one sample scenario now."

_RFQ_EXTRA_TEMPLATE = """
Additionally, populate the full RFQ field checklist below into "fields", \
using EXACTLY these JSON keys — do not invent, rename, omit, or add any key. \
Fields marked (required) MUST be populated with a specific, concrete value; \
fields marked (optional) should also get a plausible fictional value when one \
fits the scenario, or an empty string "" if it genuinely does not apply:

---
{rfq_fields_text}
---
"""


def _render_rfq_field_catalog() -> str:
    """Render the RFQ field checklist as ``"key": Label (required|optional)`` lines."""
    return "\n".join(
        f'- "{field.name}": {field.label} ({"required" if field.required else "optional"})'
        for field in RFQ_FIELD_CATALOG
    )


def build_prompts(email_type: EmailType) -> tuple[str, str]:
    """Build the system and user prompts for a sample-query generation call.

    Args:
        email_type: Which email pattern to generate a sample for.

    Returns:
        A ``(system_prompt, user_prompt)`` pair.
    """
    extra_context = ""
    if email_type is EmailType.RFQ:
        extra_context = _RFQ_EXTRA_TEMPLATE.format(rfq_fields_text=_render_rfq_field_catalog())

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        label=EMAIL_TYPE_LABELS[email_type],
        skill_text=read_skill_spec(email_type),
        extra_context=extra_context,
    )
    return system_prompt, _USER_PROMPT
