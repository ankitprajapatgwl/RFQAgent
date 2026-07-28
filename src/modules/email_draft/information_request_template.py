"""Renders the Information Request Email HTML template.

Backs the "Send Information Request" action on an existing tracked conversation
when supplier has replied with incomplete information: missing required fields
can be requested from the supplier. Supports dynamic field addition on the fly.
"""

from __future__ import annotations

from src.config.settings import PROJECT_ROOT
from src.modules.email_draft.template_engine import has_value, render_template

_TEMPLATE_PATH = (
    PROJECT_ROOT / "templates" / "email_templates" / "information_request_template.html"
)


def build_information_request_subject(conversation_subject: str) -> str:
    """Build the subject line for an information request email.

    Args:
        conversation_subject: The subject of the conversation's original email.

    Returns:
        ``conversation_subject`` prefixed with ``"Re: "`` (unless already so
        prefixed), or a generic subject if none is available.
    """
    subject = (conversation_subject or "").strip()
    if not subject:
        return "Additional Information Required"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def render_information_request_email_html(
    *,
    missing_fields: str,
    additional_requests: str = "",
    deadline: str = "",
    include_urgency_note: bool = False,
    contact_name: str,
    contact_email: str,
    company_name: str,
) -> str:
    """Fill the information request HTML template with the given values.

    Args:
        missing_fields: Comma-separated list of required fields missing from the quote.
        additional_requests: Any additional information or clarifications needed.
        deadline: Optional deadline for providing the information.
        include_urgency_note: Whether to include an urgency note.
        contact_name: Signed-in user's display name (buyer contact).
        contact_email: Signed-in user's email address (buyer contact).
        company_name: The sender's company name.

    Returns:
        The complete, rendered HTML email body.
    """
    values = {
        "missingFields": missing_fields,
        "additionalRequests": additional_requests,
        "deadline": deadline,
        "buyerName": contact_name,
        "buyerEmail": contact_email,
        "companyName": company_name,
        "companyAddress": "",
        "companyWebsite": "",
    }
    conditions = {
        "additionalRequests": has_value(additional_requests),
        "deadline": has_value(deadline),
        "urgency": include_urgency_note,
        "buyerContact": True,  # contact details always come from the signed-in user
    }
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return render_template(template, values, conditions)
