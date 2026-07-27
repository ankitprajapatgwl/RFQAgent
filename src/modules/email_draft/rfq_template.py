"""Renders the RFQ HTML email template directly from generated field data.

Backs the "Graft Email Content" flow: the sample-data agent's RFQ field
values (:data:`~src.modules.email_patterns.RFQ_FIELD_CATALOG`) and the
signed-in user's own contact details are filled straight into
``templates/email_templates/rfq_email_template.html``. No drafting LLM call
is involved — every value already has a concrete source, so there is
nothing left for a drafting agent to invent.

The template encodes two authoring conventions this module implements:

* ``<!-- BEGIN-IF: key --> ... <!-- END-IF: key -->`` — the enclosed block
  is kept only when ``key`` resolves to a real (non-placeholder) value.
* ``{{token}}`` — replaced with the matching value, HTML-escaped.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from src.config.settings import PROJECT_ROOT

_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "email_templates" / "rfq_email_template.html"

# Values that count as "no real answer" — mirrors
# ``modules.sample_data.service._PLACEHOLDER_VALUES`` — so a field the
# sample-data agent left blank/placeholder doesn't render an empty section.
_PLACEHOLDER_VALUES = {"", "tbd", "n/a", "na", "todo", "unknown", "none"}

_CONDITIONAL_RE = re.compile(r"<!-- BEGIN-IF: (\w+) -->(.*?)<!-- END-IF: \1 -->", re.DOTALL)
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")


def _has_value(value: str | None) -> bool:
    """Return whether ``value`` is a real, concrete answer (not blank/placeholder)."""
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


def _combine(*parts: str) -> str:
    """Join the given parts that have a real value with an em dash separator."""
    return " — ".join(part.strip() for part in parts if _has_value(part))


def build_rfq_graft_subject(fields: dict[str, str]) -> str:
    """Build the subject line for a grafted RFQ email.

    Args:
        fields: The RFQ field values (see
            :data:`~src.modules.email_patterns.RFQ_FIELD_CATALOG`).

    Returns:
        A subject line naming the requested product/service when available,
        else a generic RFQ subject.
    """
    product = fields.get("product_service_requirements", "").strip()
    if not product:
        return "Request for Quotation (RFQ)"
    snippet = product if len(product) <= 80 else product[:77] + "..."
    return f"Request for Quotation — {snippet}"


def render_rfq_email_html(
    fields: dict[str, str],
    *,
    contact_name: str,
    contact_email: str,
    company_name: str,
) -> str:
    """Fill the RFQ HTML template with the given field values.

    Args:
        fields: The RFQ field values to fill into the template, as generated
            by the sample-data agent (or subsequently hand-edited).
        contact_name: Signed-in user's display name (buyer contact).
        contact_email: Signed-in user's email address (buyer contact).
        company_name: The sender's company name.

    Returns:
        The complete, rendered HTML email body.
    """
    values = {
        "coverLetter": fields.get("cover_letter_invitation", ""),
        "overview": fields.get("overview", ""),
        "rfqIssueDate": datetime.now(UTC).strftime("%B %d, %Y"),
        "submissionDeadline": fields.get("rfq_timeline", ""),
        "buyerCompanyName": company_name,
        "contactName": contact_name,
        "contactEmail": contact_email,
        "supplierInstructions": fields.get("supplier_instructions", ""),
        "scopeOfSupply": fields.get("scope_of_supply", ""),
        "productServiceReq": fields.get("product_service_requirements", ""),
        "technicalSpecs": fields.get("technical_specifications", ""),
        "requiredQuantity": fields.get("quantity_volume", ""),
        "unitOfMeasure": "",
        "productCertifications": fields.get("certifications_compliance_product", ""),
        "lineItems": fields.get("line_items_boq", ""),
        "pricingSchedule": fields.get("pricing_schedule_quotation_form", ""),
        "costBreakdown": fields.get("cost_breakdown", ""),
        "commercialTerms": fields.get("commercial_terms", ""),
        "deliveryRequirements": fields.get("delivery_requirements", ""),
        "logisticsShipping": fields.get("logistics_shipping_requirements", ""),
        "supplierInfo": _combine(
            fields.get("supplier_information", ""), fields.get("company_profile", "")
        ),
        "qualityCertifications": fields.get("quality_certifications_supplier", ""),
        "complianceDetails": fields.get("compliance_questionnaire_supplier", ""),
        "capacity": fields.get("manufacturing_capacity", ""),
        "esgRequirements": fields.get("sustainability_esg_requirements", ""),
        "riskAssessment": fields.get("risk_assessment_questionnaire", ""),
        "requiredAttachments": fields.get("required_attachments", ""),
        "buyerAttachments": fields.get("buyer_attachments", ""),
        "qaDetails": fields.get("questions_clarifications", ""),
        "alternativeOffers": fields.get("alternative_offers_value_engineering", ""),
        "termsAndConditions": fields.get("terms_and_conditions", ""),
        "ndaRequired": fields.get("confidentiality_nda_acknowledgement", ""),
        "companyName": company_name,
        "companyAddress": "",
        "companyWebsite": "",
    }
    # Template section keys, mapped to whether that section should render.
    # Most mirror the same-named value above; a couple (allowAlternatives,
    # signatureRequired) gate a differently-named value or a static line.
    conditions = {
        "coverLetter": _has_value(values["coverLetter"]),
        "overview": _has_value(values["overview"]),
        "buyerInfo": True,  # contact details always come from the signed-in user
        "supplierInstructions": _has_value(values["supplierInstructions"]),
        "scopeOfSupply": _has_value(values["scopeOfSupply"]),
        "lineItems": _has_value(values["lineItems"]),
        "costBreakdown": _has_value(values["costBreakdown"]),
        "capacity": _has_value(values["capacity"]),
        "esgRequirements": _has_value(values["esgRequirements"]),
        "riskAssessment": _has_value(values["riskAssessment"]),
        "requiredAttachments": _has_value(values["requiredAttachments"]),
        "buyerAttachments": _has_value(values["buyerAttachments"]),
        "qaDetails": _has_value(values["qaDetails"]),
        "allowAlternatives": _has_value(values["alternativeOffers"]),
        "termsAndConditions": _has_value(values["termsAndConditions"]),
        "ndaRequired": _has_value(values["ndaRequired"]),
        "signatureRequired": _has_value(fields.get("signature_authorization", "")),
    }

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    def _resolve_conditional(match: re.Match[str]) -> str:
        key, body = match.group(1), match.group(2)
        return body if conditions.get(key, False) else ""

    rendered = _CONDITIONAL_RE.sub(_resolve_conditional, template)
    return _TOKEN_RE.sub(lambda m: html.escape(values.get(m.group(1), "")), rendered)
