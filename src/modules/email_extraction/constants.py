"""Editable catalog of inbound email types and the fields to extract for each.

This is the single place to change *what the extractor pulls out of a supplier
email* (Requirement 5: "email types ke structure/format ko constant file se
read karna"). Nothing else in the module hardcodes a field list — the prompt
builder (``prompts.py``) renders its instructions straight from
:data:`EMAIL_TYPE_STRUCTURES` and :data:`COMMON_FIELDS`, and the UI labels come
from :func:`label_for`. To add or change what is extracted:

* **Change a type's fields** — edit that type's ``fields`` tuple below. No other
  file changes.
* **Add a brand-new type** — add a member to
  :class:`~src.modules.email_extraction.enums.ExtractedEmailType`, then add its
  :class:`EmailTypeStructure` entry here.

Keeping this as typed Python (rather than a JSON/YAML file) means a bad edit is
caught by ``mypy``/import-time errors instead of failing silently at runtime,
while still being a one-file, human-readable "constants" source.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.modules.email_extraction.enums import ExtractedEmailType


@dataclass(frozen=True)
class ExtractionField:
    """One field the extractor should try to pull from an email.

    Attributes:
        name: Machine key the value is stored under in the extracted-details
            JSON (``lower_snake_case``).
        description: Plain-language description handed to the model so it knows
            exactly what to look for.
    """

    name: str
    description: str


@dataclass(frozen=True)
class EmailTypeStructure:
    """The classification + extraction spec for one inbound email type.

    Attributes:
        email_type: The type this structure defines.
        label: Human-readable label shown in the dashboard (RFQ Monitoring
            list, dispatch-history badges).
        description: When this type applies — used both to help the model
            classify an email and as documentation for whoever edits this file.
        fields: The type-specific fields to extract, on top of
            :data:`COMMON_FIELDS`.
    """

    email_type: ExtractedEmailType
    label: str
    description: str
    fields: tuple[ExtractionField, ...]


# Fields extracted for EVERY email regardless of its classified type. Kept
# separate so common bookkeeping is defined once rather than repeated per type.
COMMON_FIELDS: tuple[ExtractionField, ...] = (
    ExtractionField("supplier_company", "Name of the supplier/company that sent the email."),
    ExtractionField("contact_person", "Name of the person who wrote the email, if stated."),
    ExtractionField("contact_email", "A reply/contact email address mentioned in the message."),
    ExtractionField("contact_phone", "A phone number mentioned in the message."),
    ExtractionField("product", "The product or service the email is about."),
    ExtractionField(
        "reference_number",
        "Any RFQ/quote/order reference or ticket number quoted in the email.",
    ),
    ExtractionField(
        "sentiment",
        "Overall tone: one of positive, neutral, or negative.",
    ),
    ExtractionField(
        "requested_action",
        "What the supplier is asking the buyer to do next, in one short phrase.",
    ),
    ExtractionField(
        "key_dates",
        "Any dates/deadlines mentioned (validity, delivery, response-by), as text.",
    ),
)


EMAIL_TYPE_STRUCTURES: dict[ExtractedEmailType, EmailTypeStructure] = {
    ExtractedEmailType.QUOTE: EmailTypeStructure(
        email_type=ExtractedEmailType.QUOTE,
        label="Quote / Pricing",
        description=(
            "The supplier has provided pricing — a quotation, price list, or unit "
            "prices in response to an RFQ."
        ),
        fields=(
            ExtractionField("unit_price", "Quoted price per unit, with currency."),
            ExtractionField("currency", "Currency of the quote, e.g. USD, EUR, INR."),
            ExtractionField("total_price", "Quoted total/extended price, if given."),
            ExtractionField("quantity", "Quantity the quote is for."),
            ExtractionField("minimum_order_quantity", "Stated MOQ, if any."),
            ExtractionField("lead_time", "Production/delivery lead time quoted."),
            ExtractionField("payment_terms", "Payment terms, e.g. 30% advance, Net 30."),
            ExtractionField("incoterms", "Shipping terms, e.g. FOB, CIF, EXW."),
            ExtractionField("quote_validity", "How long the quoted price is valid."),
            ExtractionField("warranty", "Any warranty or guarantee offered."),
        ),
    ),
    ExtractedEmailType.FOLLOW_UP: EmailTypeStructure(
        email_type=ExtractedEmailType.FOLLOW_UP,
        label="Follow-Up",
        description=(
            "The supplier is following up or checking in on an earlier message, "
            "without adding a new quote or decision."
        ),
        fields=(
            ExtractionField("follow_up_reason", "What the follow-up is chasing."),
            ExtractionField("references_previous", "Which earlier message/RFQ it refers to."),
            ExtractionField("response_requested_by", "Any deadline the supplier is asking for."),
        ),
    ),
    ExtractedEmailType.NEGOTIATION: EmailTypeStructure(
        email_type=ExtractedEmailType.NEGOTIATION,
        label="Negotiation",
        description=(
            "The supplier is negotiating — a counter-offer, a revised price, or "
            "changed commercial terms."
        ),
        fields=(
            ExtractionField("proposed_price", "The new/counter price the supplier proposes."),
            ExtractionField("previous_price", "The prior price being revised, if referenced."),
            ExtractionField("revised_terms", "Any changed terms (MOQ, payment, delivery)."),
            ExtractionField("conditions", "Conditions attached to the new offer."),
        ),
    ),
    ExtractedEmailType.CLARIFICATION: EmailTypeStructure(
        email_type=ExtractedEmailType.CLARIFICATION,
        label="Clarification / Question",
        description=(
            "The supplier is asking a question or requesting more information "
            "before they can quote or proceed."
        ),
        fields=(
            ExtractionField("questions", "The questions the supplier is asking."),
            ExtractionField("information_needed", "What information they need from the buyer."),
        ),
    ),
    ExtractedEmailType.DECLINE: EmailTypeStructure(
        email_type=ExtractedEmailType.DECLINE,
        label="Decline / Unable",
        description=(
            "The supplier is declining — cannot supply, out of stock, not "
            "interested, or otherwise says no."
        ),
        fields=(
            ExtractionField("decline_reason", "Why the supplier is declining."),
            ExtractionField("alternative_offered", "Any alternative product/supplier suggested."),
        ),
    ),
    ExtractedEmailType.SAMPLE: EmailTypeStructure(
        email_type=ExtractedEmailType.SAMPLE,
        label="Sample",
        description="The email is about product samples — offering, sending, or discussing them.",
        fields=(
            ExtractionField("sample_availability", "Whether samples are available."),
            ExtractionField("sample_cost", "Cost of the sample, if any."),
            ExtractionField("sample_lead_time", "How long the sample takes to arrive."),
            ExtractionField("tracking_details", "Any shipment/tracking details provided."),
        ),
    ),
    ExtractedEmailType.ORDER_CONFIRMATION: EmailTypeStructure(
        email_type=ExtractedEmailType.ORDER_CONFIRMATION,
        label="Order Confirmation",
        description="The supplier is confirming/acknowledging an order or accepting terms.",
        fields=(
            ExtractionField("order_reference", "Order/PO reference confirmed."),
            ExtractionField("confirmed_quantity", "Quantity confirmed."),
            ExtractionField("confirmed_price", "Price confirmed."),
            ExtractionField("delivery_date", "Confirmed/expected delivery date."),
        ),
    ),
    ExtractedEmailType.GENERAL: EmailTypeStructure(
        email_type=ExtractedEmailType.GENERAL,
        label="General",
        description=(
            "A general or miscellaneous message that does not fit any of the more "
            "specific types above. Use this as the fallback."
        ),
        fields=(ExtractionField("topic", "What the email is broadly about."),),
    ),
}


def label_for(email_type: ExtractedEmailType) -> str:
    """Return the display label for an email type, defaulting to the raw value.

    Args:
        email_type: The classified email type.

    Returns:
        The human-readable label from :data:`EMAIL_TYPE_STRUCTURES`, or the
        enum's value if (defensively) no structure is registered.
    """
    structure = EMAIL_TYPE_STRUCTURES.get(email_type)
    return structure.label if structure is not None else email_type.value
