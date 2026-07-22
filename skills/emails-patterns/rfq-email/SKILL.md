---
name: rfq-email
description: >
  Draft a formal Request for Quotation (RFQ) email to a supplier. Use this
  when the user asks to "request a quote", "send an RFQ", or "ask a
  supplier for pricing".
---

# RFQ Email Skill

## When to use

The user wants to request a formal price quotation from a supplier for a
product or service.

## Required information (ask only if missing)

See the full required/optional field checklist in `rfq_fields.md` at the
project root. Fields marked `*` in that file are required; all others are
optional and should only be included if the user volunteers them. The
required fields are:

- RFQ Timeline (deadline for the supplier's response)
- Product / Service Requirements
- Quantity / Volume
- Technical Specifications
- Certifications and Compliance (for the product/service)
- Pricing Schedule / Quotation Form (what format the quote should come back in)
- Commercial Terms (payment terms, currency, Incoterms)
- Delivery Requirements
- Logistics & Shipping Requirements
- Supplier Information (name/contact)
- Company Profile (the buyer's own company, briefly)
- Quality Certifications (required of the supplier)
- Compliance Questionnaire (required of the supplier)

## Personalization

If a user profile is available at '/user_data/profile.md', read it first and
use the sender's name, role, and signature when composing the email.

## Structure to follow

1. **Subject**: `[RFQ-{short-ref}] Request for Quotation — {product_name}`
2. **Greeting**: "Dear {supplier_name},"
3. **Opening**: state the request plainly — what is being quoted and why.
4. **Body**: present each required field the user has provided in a clear
   table or bullet list (Product/Service Requirements, Quantity, Technical
   Specifications, Pricing Schedule, Commercial Terms, Delivery
   Requirements, Logistics, Compliance/Certifications).
5. **Close**: state the RFQ timeline/deadline and invite questions.

## Tone rules

- Formal, precise, unambiguous — this is a commercial document.
- Never invent values for missing fields; only include what was confirmed.

## Output

Write the finished email and hold it for user review. Do NOT send it — the
user will review and approve it first.
