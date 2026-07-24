"""Catalog of available email-drafting patterns and their on-disk specs.

Reads straight from ``skills/emails-patterns/`` (and the project's RFQ field
checklist) so every consumer's view of "which patterns exist" and "what a
pattern requires" always tracks whatever the skill files currently say — no
label or field list duplicated in Python.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class RfqField:
    """One field of the RFQ checklist (``rfq_fields.md``), machine-usable.

    Attributes:
        name: Machine key the value is stored under in generated/extracted
            JSON (``lower_snake_case``).
        label: Human-readable field name, matching ``rfq_fields.md`` verbatim.
        required: Whether this field is mandatory (marked ``*`` in the checklist).
    """

    name: str
    label: str
    required: bool


# Mirrors ``rfq_fields.md`` one-to-one. Kept as typed Python (rather than
# re-parsing the markdown at runtime) so every consumer that needs a stable
# JSON key per field — not just the raw checklist text — shares one
# definition instead of each inventing its own field names.
RFQ_FIELD_CATALOG: tuple[RfqField, ...] = (
    RfqField("supplier_email_address", "Supplier Email Address", False),
    RfqField("cover_letter_invitation", "Cover Letter / Invitation", False),
    RfqField("overview", "Overview", False),
    RfqField("buyer_information", "Buyer Information", False),
    RfqField("supplier_instructions", "Supplier Instructions", False),
    RfqField("rfq_timeline", "RFQ Timeline", True),
    RfqField("scope_of_supply", "Scope of Supply", False),
    RfqField("product_service_requirements", "Product / Service Requirements", True),
    RfqField("quantity_volume", "Quantity / Volume", True),
    RfqField("line_items_boq", "Line Items / Bill of Quantities (BOQ)", False),
    RfqField("technical_specifications", "Technical Specifications", True),
    RfqField(
        "certifications_compliance_product",
        "Certifications and Compliance (for the product/service)",
        True,
    ),
    RfqField("pricing_schedule_quotation_form", "Pricing Schedule / Quotation Form", True),
    RfqField("cost_breakdown", "Cost Breakdown (Optional)", False),
    RfqField("commercial_terms", "Commercial Terms", True),
    RfqField("delivery_requirements", "Delivery Requirements", True),
    RfqField("logistics_shipping_requirements", "Logistics & Shipping Requirements", True),
    RfqField("supplier_information", "Supplier Information", True),
    RfqField("company_profile", "Company Profile", True),
    RfqField("manufacturing_capacity", "Manufacturing Capacity", False),
    RfqField("quality_certifications_supplier", "Quality Certifications (for supplier)", True),
    RfqField(
        "compliance_questionnaire_supplier", "Compliance Questionnaire (for supplier)", True
    ),
    RfqField("sustainability_esg_requirements", "Sustainability / ESG Requirements", False),
    RfqField("risk_assessment_questionnaire", "Risk Assessment Questionnaire", False),
    RfqField("required_attachments", "Required Attachments", False),
    RfqField(
        "buyer_attachments",
        "Buyer Attachments (Drawings, BOM, Specifications, CAD Files, etc.)",
        False,
    ),
    RfqField("questions_clarifications", "Questions & Clarifications (Q&A)", False),
    RfqField(
        "alternative_offers_value_engineering",
        "Alternative Offers / Value Engineering Proposals",
        False,
    ),
    RfqField("supplier_declaration", "Supplier Declaration", False),
    RfqField("terms_and_conditions", "Terms & Conditions", False),
    RfqField("confidentiality_nda_acknowledgement", "Confidentiality / NDA Acknowledgement", False),
    RfqField("signature_authorization", "Signature & Authorization", False),
)
