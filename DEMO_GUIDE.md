# RFQAgent — Team Demo Guide

## 1. Today's Agenda

1. **Project & Workflow Explanation** — what RFQAgent does and how data flows through it
2. **Live Demo** — run the app and show it working in the browser (~15 min)
3. **Code Walkthrough** — open the code and explain the important parts (~15 min)
4. **Questions / Discussion**

---

## 2. Workflow — What to Explain

### One-line summary
RFQAgent helps a buyer send RFQ (Request For Quotation) emails to suppliers, and then **automatically reads and understands the supplier's reply using AI** — no manual reading needed.

### The Full Flow (explain step by step, in this order)

1. **Draft an email**
   The user picks an email type — RFQ, negotiation, follow-up, apology, or sample-request — and types a short request in plain English. AI (Claude) writes the full email (subject + body) based on this request. This is saved only as a **draft** — nothing is sent yet.

2. **Human checks and approves (Verify)**
   A person must review the draft and click "Verify" before it can be sent. This is a safety rule — **AI can never send an email by itself**, a human always approves first.

3. **Send the email**
   The approved draft (or a structured RFQ form with product, quantity, target price) is sent to the supplier's email, with attachments if needed. The system opens a **Conversation** to track this — so any future reply from the supplier can be automatically matched back to it.

4. **Supplier replies**
   When the supplier replies to the email, the system receives it automatically in the background (through a webhook) — no manual checking of inbox needed.

5. **Background worker picks it up**
   A worker keeps running in the background and checks every few seconds for new replies that haven't been processed yet. It always picks the oldest one first (first-in-first-out).

6. **AI extraction agent reads the reply**
   The AI agent reads the email text and any attachments (PDF, Excel, images, etc.), figures out **what type of reply it is** (quote, negotiation, decline, follow-up, order confirmation, etc.), and pulls out the important details — price, quantity, lead time, payment terms — and saves all of this as clean, structured data.

7. **Dashboard shows everything**
   The team can see every sent and received email, and see the AI's extracted details for each reply, in the **RFQ Monitoring** tab of the dashboard.

### Key points to highlight while explaining

- **Human approval gate**: AI drafts, but never sends, an email on its own — a person always verifies first.
- **Automatic tracking**: Every email is linked to a "Conversation", so replies are matched to the correct RFQ automatically.
- **AI reads attachments too**: not just the email text — PDFs, Excel sheets, images, and zip files are also read and understood.
- **Nothing is lost on failure**: if the AI extraction fails for some reply, it's marked as "failed" instead of crashing the app — the reply is still visible, just without extracted details.

---

## 3. Live Demo — What to Show on the UI

Suggested order to click through during the live demo:

1. **Start the app**
   - Docker: `make docker-up` then open `http://localhost:8000/dashboard`
   - Or local: `make run` (uses SQLite, no Docker needed)

2. **Email Drafting tab** — generate a sample email request, let AI draft the full email, edit it if needed, then click "Verify" to approve it.

3. **Send RFQ tab** — fill the structured RFQ form (product, quantity, target price), optionally attach a file, and send it to a supplier email.

4. **Email Dispatch History tab** — show the conversation thread: what was sent, and what was received as a reply.

5. **RFQ Monitoring tab** — open a received reply and show the AI-extracted structured details (price, terms, etc.) next to the original email content.

---

## 4. Code Walkthrough — What & How to Explain

Suggested order to open files, and what to say for each (simple words, focus on "why", not just "what"):

| Step | File | What to say |
|---|---|---|
| 1 | `src/api/main.py` | "This is where the app starts — it creates the FastAPI app, connects the database, and starts the background worker when the app boots up." |
| 2 | `src/modules/email_draft/service.py` | "This is the drafting logic. It takes the user's short request, builds a prompt using a 'skill' template, and asks Claude to write the email. A draft only becomes 'verified' through one specific method — never automatically." |
| 3 | `src/modules/email_delivery/service.py` | "This handles sending emails and receiving replies. `send_draft` / `send_rfq` send the email and open a Conversation. `handle_inbound` receives the supplier's reply and matches it to the right conversation." |
| 4 | `src/modules/worker/runner.py` and `service.py` | "This is the background worker — a simple loop that wakes up every few seconds, checks for the oldest unread reply, and hands it to the AI extraction agent. One reply is fully processed before moving to the next." |
| 5 | `src/modules/email_extraction/agent.py` | "This is the core AI agent — the 'brain' of the extraction feature. It reads the email and its attachments, asks Claude to classify the reply type and pull out structured details, then saves the result." |
| 6 | `src/modules/email_extraction/attachments_reader.py` | "This explains how attachments are read — text and Excel files are converted to readable text, while PDFs and images are sent directly to the AI as-is, since Claude can read those natively." |
| 7 | `src/integrations/llm.py` | "This is the single shared connection to Claude used everywhere in the app — it handles retries and errors in one place, so every feature doesn't repeat this logic." |
| 8 | `templates/dashboard.html` | "This is the one page that has all four dashboard tabs — Drafting, Send RFQ, Dispatch History, and RFQ Monitoring. It's plain HTML + JavaScript calling our JSON APIs, no separate frontend framework." |

### Points to explain about *how* the code is organized (not just what it does)

- **Each feature is its own folder** under `src/modules/` (auth, email_draft, email_delivery, email_extraction, worker) — each with its own `router.py` (API), `service.py` (logic), `repository.py` (database access), and `models.py` (database tables). This keeps things easy to find and change.
- **The AI agent and the background worker are kept separate** — the worker doesn't know anything about AI, it just calls whatever extractor is given to it. This means the extraction logic could be swapped out later without touching the worker.
- **Failures are handled locally** — if the AI extraction fails for one email, only that one is marked "failed"; it doesn't stop the worker or crash anything else.
- Mention the project's own rulebook, `AgenticAI_Rules_Diagram.md` — it lists the design rules the whole codebase follows (e.g., one agent = one responsibility, human-only approval for sending, idempotent processing). The code comments even reference these rules by number.

---

## Quick Reference — Useful Commands

```bash
make install        # install dependencies
make run            # run locally with SQLite
make docker-up       # run full stack with Docker + Postgres
make test            # run tests
make check           # lint + typecheck + test (everything)
```
