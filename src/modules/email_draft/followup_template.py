"""Renders the RFQ follow-up (reminder) HTML email template.

Backs the "Send Follow-up" action on an existing tracked conversation
(``email_delivery``): a handful of fields — mostly a fresh submission
deadline — are filled straight into
``templates/email_templates/rfq_follow_up_email_template.html``. No drafting
LLM call is involved, the same no-LLM convention as
:mod:`~src.modules.email_draft.rfq_template`.
"""

from __future__ import annotations

from src.config.settings import PROJECT_ROOT
from src.modules.email_draft.template_engine import has_value, render_template

_TEMPLATE_PATH = (
    PROJECT_ROOT / "templates" / "email_templates" / "rfq_follow_up_email_template.html"
)


def build_followup_subject(conversation_subject: str) -> str:
    """Build the subject line for a follow-up email.

    Args:
        conversation_subject: The subject of the conversation's original email.

    Returns:
        ``conversation_subject`` prefixed with ``"Re: "`` (unless already so
        prefixed), or a generic follow-up subject if none is available.
    """
    subject = (conversation_subject or "").strip()
    if not subject:
        return "Reminder: Request for Quotation (RFQ)"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def render_followup_email_html(
    *,
    original_issue_date: str,
    submission_deadline: str,
    rfq_reference: str = "",
    portal_link: str = "",
    include_qa_note: bool = False,
    contact_name: str,
    contact_email: str,
    company_name: str,
) -> str:
    """Fill the follow-up HTML template with the given values.

    Args:
        original_issue_date: When the original RFQ was sent, e.g. "July 10, 2026".
        submission_deadline: The (possibly new) deadline to highlight.
        rfq_reference: Optional label naming the original RFQ.
        portal_link: Optional URL to a submission portal.
        include_qa_note: Whether to include the "questions welcome" reminder.
        contact_name: Signed-in user's display name (buyer contact).
        contact_email: Signed-in user's email address (buyer contact).
        company_name: The sender's company name.

    Returns:
        The complete, rendered HTML email body.
    """
    values = {
        "originalIssueDate": original_issue_date,
        "rfqReference": rfq_reference,
        "submissionDeadline": submission_deadline,
        "buyerName": contact_name,
        "buyerEmail": contact_email,
        "portalLink": portal_link,
        "companyName": company_name,
        "companyAddress": "",
        "companyWebsite": "",
    }
    conditions = {
        "rfqReference": has_value(rfq_reference),
        "buyerContact": True,  # contact details always come from the signed-in user
        "portalLink": has_value(portal_link),
        "qaDetails": include_qa_note,
    }
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return render_template(template, values, conditions)
