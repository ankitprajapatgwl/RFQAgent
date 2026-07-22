"""Prompt construction for email drafting.

Loads the relevant skill spec (and, for RFQ, the project's field checklist)
via the shared ``email_patterns`` catalog — the exact same skill files
``modules/sample_data`` reads to invent sample scenarios — so a drafted email
always follows whatever structure/tone/required-field rules the skill
currently states. No field list or drafting rule is duplicated in code.
"""

from __future__ import annotations

from src.modules.email_patterns import (
    EMAIL_TYPE_LABELS,
    EmailType,
    read_rfq_fields,
    read_skill_spec,
)

_SYSTEM_PROMPT_TEMPLATE = """\
You are an email-drafting assistant. Draft a "{label}" for the user, \
following the skill specification below — its required information, \
structure, and tone rules — as closely as possible.

---
{skill_text}
---
{extra_context}
The user's request is given next. Use only the information it actually \
contains or clearly implies — never invent facts, names, numbers, or dates. \
If the skill marks a piece of information as required and the user's \
request does not supply it, write a short bracketed placeholder instead of \
inventing a value, e.g. "[recipient name]" or "[quantity]".

Ignore any instruction in the skill spec above to save the email to a file \
or to send it — always return the draft directly in this response. A human \
will review, edit, and explicitly approve it before anything is ever sent; \
you are drafting only.

Respond with ONLY a single JSON object — no markdown code fences, no \
commentary — matching exactly this shape:

{{"subject": "<the email subject line>", "body": "<the full email body, \
including greeting and sign-off, with \\n for line breaks>"}}\
"""

_RFQ_EXTRA_TEMPLATE = """
Additionally, use this full RFQ field checklist. Every field marked `*` is \
required — include it if the user's request supplies a value, otherwise use \
a bracketed placeholder for it:

---
{rfq_fields_text}
---
"""


def build_prompts(email_type: EmailType, query_text: str) -> tuple[str, str]:
    """Build the system and user prompts for a drafting call.

    Args:
        email_type: Which email pattern to draft.
        query_text: The user's natural-language request to draft from.

    Returns:
        A ``(system_prompt, user_prompt)`` pair. Unlike sample-query
        generation, the user prompt here is the caller's own query — the
        draft must actually reflect what they asked for.
    """
    extra_context = ""
    if email_type is EmailType.RFQ:
        extra_context = _RFQ_EXTRA_TEMPLATE.format(rfq_fields_text=read_rfq_fields())

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        label=EMAIL_TYPE_LABELS[email_type],
        skill_text=read_skill_spec(email_type),
        extra_context=extra_context,
    )
    return system_prompt, query_text
