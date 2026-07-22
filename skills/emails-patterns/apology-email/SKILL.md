---
name: apology-email
description: >
  Draft a sincere, accountable apology email after a mistake, delay, or service
  issue. Use this when the user asks to "apologize", "say sorry", or "make
  amends" to a contact or client.
---

# Apology Email Skill

## When to use

The user needs to acknowledge a fault and rebuild trust with the recipient.

## Required information (ask only if missing)

- Recipient name
- What went wrong (the specific issue)
- Any remedy or next step being offered

## Personalization

If a user profile is available at '/user_data/profile.md', read it first and
use the sender's name, role, and signature when composing the email.

## Structure to follow

1. **Subject**: clear + accountable, e.g. "Apology regarding <issue>".
2. **Greeting**: "Dear <Name>,".
3. **Opening**: state the apology plainly and early.
4. **Body**: acknowledge impact, take responsibility (no excuses), describe the
   concrete fix or next step.
5. **Close**: reaffirm commitment, invite further contact, professional sign-off.

## Tone rules

- Be genuine and specific; do not over-apologize or grovel.
- Take ownership; never blame the recipient.

## Output

Write the finished email and SAVE it to '/drafts/email.md' using the
filesystem tools. Do NOT send it — the user will review and approve it first.
