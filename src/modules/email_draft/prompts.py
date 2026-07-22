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

_SENDER_TEMPLATE = """
You are drafting on behalf of the signed-in user, whose real details are \
below. Sign the email off ("Best regards", "Kind regards", etc.) using these \
actual details — never a "[Your Name]" placeholder. Use only the fields that \
are present; omit any that are blank.

{sender_lines}
"""


def _build_sender_context(
    sender_name: str,
    sender_email: str,
    sender_role: str,
    company_name: str,
    sender_phone: str,
) -> str:
    """Render the sender's real profile into a sign-off instruction block.

    Args:
        sender_name: The user's full name.
        sender_email: The user's email address.
        sender_role: The user's role (e.g. buyer), if meaningful.
        company_name: The user's company/organisation name, if known.
        sender_phone: The user's contact phone number, if provided.

    Returns:
        The formatted sender context block, or ``""`` when no details are set
        (so unauthenticated/legacy callers get the original prompt verbatim).
    """
    fields = [
        ("Name", sender_name),
        ("Email", sender_email),
        ("Phone", sender_phone),
        ("Role", sender_role),
        ("Company", company_name),
    ]
    lines = [f"- {label}: {value.strip()}" for label, value in fields if value and value.strip()]
    if not lines:
        return ""
    return _SENDER_TEMPLATE.format(sender_lines="\n".join(lines))


def build_prompts(
    email_type: EmailType,
    query_text: str,
    *,
    sender_name: str = "",
    sender_email: str = "",
    sender_role: str = "",
    company_name: str = "",
    sender_phone: str = "",
) -> tuple[str, str]:
    """Build the system and user prompts for a drafting call.

    Args:
        email_type: Which email pattern to draft.
        query_text: The user's natural-language request to draft from.
        sender_name: The signed-in user's full name, used in the sign-off.
        sender_email: The signed-in user's email, used in the sign-off.
        sender_role: The signed-in user's role, used in the sign-off if set.
        company_name: The sender's company/organisation, used in the sign-off.
        sender_phone: The signed-in user's phone number, used in the sign-off
            so the drafted "Best regards" block carries a real contact number.

    Returns:
        A ``(system_prompt, user_prompt)`` pair. Unlike sample-query
        generation, the user prompt here is the caller's own query — the
        draft must actually reflect what they asked for. Sender details are
        folded into the *system* prompt only, so the returned user prompt is
        always exactly ``query_text``.
    """
    extra_context = ""
    if email_type is EmailType.RFQ:
        extra_context = _RFQ_EXTRA_TEMPLATE.format(rfq_fields_text=read_rfq_fields())
    extra_context += _build_sender_context(
        sender_name, sender_email, sender_role, company_name, sender_phone
    )

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        label=EMAIL_TYPE_LABELS[email_type],
        skill_text=read_skill_spec(email_type),
        extra_context=extra_context,
    )
    return system_prompt, query_text
