"""Renders the RFQ negotiation/counter-offer HTML email template.

Backs the "Send Negotiation" action on an existing tracked conversation
(``email_delivery``): the requested adjustments (price, volume, terms, lead
time, clarifications — each optional) are filled straight into
``templates/email_templates/rfq_negotiation_template.html``. No drafting LLM
call is involved, the same no-LLM convention as
:mod:`~src.modules.email_draft.rfq_template`.
"""

from __future__ import annotations

from src.config.settings import PROJECT_ROOT
from src.modules.email_draft.template_engine import has_value, render_template

_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "email_templates" / "rfq_negotiation_template.html"


def build_negotiation_subject(conversation_subject: str) -> str:
    """Build the subject line for a negotiation email.

    Args:
        conversation_subject: The subject of the conversation's original email.

    Returns:
        ``conversation_subject`` prefixed with ``"Re: "`` (unless already so
        prefixed), or a generic negotiation subject if none is available.
    """
    subject = (conversation_subject or "").strip()
    if not subject:
        return "RFQ Review & Counter-Offer"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def render_negotiation_email_html(
    *,
    response_deadline: str,
    rfq_reference: str = "",
    original_quoted_price: str = "",
    target_price: str = "",
    new_quantity: str = "",
    quoted_terms: str = "",
    requested_terms: str = "",
    quoted_lead_time: str = "",
    target_date: str = "",
    clarifications: str = "",
    portal_link: str = "",
    include_meeting_request: bool = False,
    company_name: str,
) -> str:
    """Fill the negotiation HTML template with the given values.

    Every adjustment is optional and independently gated — a pricing/volume/
    terms/lead-time/clarification block only renders once its value(s) are
    supplied.

    Args:
        response_deadline: Deadline for the supplier to respond.
        rfq_reference: Optional label naming the original RFQ.
        original_quoted_price: The supplier's quoted price, if negotiating price.
        target_price: The buyer's target price, if negotiating price.
        new_quantity: A proposed new order quantity, if negotiating volume.
        quoted_terms: The supplier's quoted payment terms, if negotiating terms.
        requested_terms: The buyer's requested payment terms.
        quoted_lead_time: The supplier's quoted lead time, if negotiating schedule.
        target_date: The buyer's requested delivery date.
        clarifications: A free-text technical/scope note, if any.
        portal_link: Optional URL to a revised-quote submission portal.
        include_meeting_request: Whether to include the "let's hop on a call" note.
        company_name: The sender's company name.

    Returns:
        The complete, rendered HTML email body.
    """
    values = {
        "rfqReference": rfq_reference,
        "originalQuotedPrice": original_quoted_price,
        "targetPrice": target_price,
        "newQuantity": new_quantity,
        "quotedTerms": quoted_terms,
        "requestedTerms": requested_terms,
        "quotedLeadTime": quoted_lead_time,
        "targetDate": target_date,
        "clarifications": clarifications,
        "responseDeadline": response_deadline,
        "portalLink": portal_link,
        "companyName": company_name,
        "companyAddress": "",
        "companyWebsite": "",
    }
    conditions = {
        "targetPrice": has_value(original_quoted_price) and has_value(target_price),
        "volumeAdjustment": has_value(new_quantity),
        "paymentTerms": has_value(quoted_terms) and has_value(requested_terms),
        "leadTime": has_value(quoted_lead_time) and has_value(target_date),
        "clarifications": has_value(clarifications),
        "portalLink": has_value(portal_link),
        "meetingRequest": include_meeting_request,
    }
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return render_template(template, values, conditions)
