---
name: negotiation-email
description: >
  Draft a professional email negotiating price, quantity, or terms with a
  supplier who has already sent a quote. Use this when the user asks to
  "negotiate", "counter-offer", or "push back on price/MOQ/lead time".
---

# Negotiation Email Skill

## When to use

The user has an existing supplier quote and wants to request a better
price, lower minimum order quantity (MOQ), shorter lead time, or different
payment terms.

## Required information (ask only if missing)

- Supplier name
- What is being negotiated (price, MOQ, lead time, and/or payment terms)
- The specific counter-ask (e.g. target unit price, target MOQ)
- Reference to the original quote/conversation being negotiated

## Personalization

If a user profile is available at '/user_data/profile.md', read it first and
use the sender's name, role, and signature when composing the email.

## Structure to follow

1. **Subject**: "Re: [previous subject] — Follow-up on Pricing/Terms".
2. **Greeting**: "Dear {supplier_name},".
3. **Opening**: thank the supplier for their quote, reference it directly.
4. **Body**: state the specific counter-ask clearly, with the reasoning
   (e.g. competitive quotes, order volume, long-term partnership).
5. **Close**: invite a revised quote, offer to discuss further.

## Tone rules

- Firm but collegial — this is a negotiation, not a demand.
- Never commit to placing an order or accepting terms on the buyer's
  behalf; this email only requests a revised offer.

## Output

Write the finished email and hold it for user review. Do NOT send it — the
user will review and approve it first.
