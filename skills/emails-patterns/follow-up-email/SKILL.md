---
name: follow-up-email
description: >
  Draft a polite, professional follow-up email when a previous message or
  request (e.g. an invoice, proposal, or question) has not yet received a
  response. Use this when the user asks to "follow up", "send a reminder", or
  "check in" with a contact.
---

# Follow-up Email Skill

## When to use

The user wants to gently chase a pending item (unpaid invoice, unanswered
proposal, awaited reply) without sounding pushy.

## Required information (ask only if missing)

- Recipient name
- The item being followed up on (e.g. invoice number, proposal title)
- Any deadline or amount, if relevant

## Personalization

If a user profile is available at '/user_data/profile.md', read it first and
use the sender's name, role, and signature when composing the email.

## Structure to follow

1. **Subject**: concise + reference the item, e.g. "Following up: Invoice #4521".
2. **Greeting**: "Dear <Name>,".
3. **Opening**: a friendly line acknowledging the prior contact.
4. **Body**: one short, courteous, non-accusatory paragraph restating the
   pending item and the desired action.
5. **Close**: offer help / availability, then a professional sign-off.

## Output

Write the finished email and SAVE it to '/drafts/email.md' using the
filesystem tools. Do NOT send it — the user will review and approve it first.
