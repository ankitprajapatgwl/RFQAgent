---
name: sample-request-email
description: >
  Draft an email requesting product samples from a supplier before placing
  a bulk order. Use this when the user asks to "request samples" or "get a
  sample before ordering".
---

# Sample Request Email Skill

## When to use

The user wants to request physical samples of a product from a supplier
before committing to a larger order.

## Required information (ask only if missing)

- Supplier name
- Product(s) being sampled
- Quantity of samples requested
- Shipping address for the samples
- Who pays for sample cost/shipping (buyer or supplier), if known

## Personalization

If a user profile is available at '/user_data/profile.md', read it first and
use the sender's name, role, and signature when composing the email.

## Structure to follow

1. **Subject**: "Sample Request — {product_name}".
2. **Greeting**: "Dear {supplier_name},".
3. **Opening**: state that samples are needed before a bulk order decision.
4. **Body**: list the product(s), quantity, and shipping address clearly.
5. **Close**: state the desired timeline and thank the supplier.

## Tone rules

- Friendly and clear; keep it short — this is a simple, low-stakes request.

## Output

Write the finished email and hold it for user review. Do NOT send it — the
user will review and approve it first.
