# Removing the Reply-To conv-id scheme in favor of Message-ID matching

**Question investigated:** can the per-conversation dynamic Reply-To address
(`JamesWhitfield.3fa9c1b2@domain`) be removed, and conversations matched
instead by storing the provider's outbound message id against the
conversation, then reading the inbound message id and looking it up in the
DB?

**Verdict: yes, this is a standard, well-supported pattern (it's literally
how Gmail/Outlook/Front/Help Scout thread email) — but it cannot be the
*only* matching mechanism.** It should replace the dynamic-address scheme as
the *primary* signal while the two fallbacks this codebase already has
(body-footer reference, sending-email heuristic) stay in place. Treating it
as a 100%-reliable sole mechanism will silently lose replies whenever a
supplier's mail client, gateway, or forwarding step drops the threading
headers — which happens often enough in the wild that every major helpdesk
product (Front, Help Scout, Intercom, Zendesk) ships a fallback path too.

---

## 1. How the current scheme works

| Step | Code |
|---|---|
| Mint conversation id | [`EmailMaster.generate_conversation_id`](src/modules/email_delivery/providers/base.py#L77) — 8 hex chars |
| Encode into Reply-To | [`EmailMaster.build_dynamic_email`](src/modules/email_delivery/providers/base.py#L81) — `JamesWhitfield.3fa9c1b2@outbound_domain` |
| Send with that Reply-To | [`EmailDeliveryService.send_draft`](src/modules/email_delivery/service.py#L249) / [`send_rfq`](src/modules/email_delivery/service.py#L337) |
| Decode on inbound | [`EmailMaster.parse_dynamic_email`](src/modules/email_delivery/providers/base.py#L110) regexes the `To` address |
| Fallback 1 | [`parse_conv_id_from_body`](src/modules/email_delivery/providers/base.py#L143) — `CONV-{id}` footer every outbound email carries |
| Fallback 2 | [`_match_new_thread`](src/modules/email_delivery/service.py#L582) — binds a headerless supplier email to the user's permanent `sending_email`, filed under their *most recent* conversation with that supplier |

Matching order today ([`_record_inbound`](src/modules/email_delivery/service.py#L505)): dynamic address → body footer → new-thread-by-sending-email.

The weak point the user is trying to fix: fallback 2 guesses "most recent
conversation with this supplier." If a user runs two concurrent RFQs with
the same supplier (two different products), a reply that loses its
conv-id-bearing address gets filed under the wrong one. Precise Message-ID
matching fixes exactly this.

Note also: `provider_message_id` is **already** a column on `email_messages`
([models.py:141](src/modules/email_delivery/models.py#L141)) and is already
populated on every sent email (service.py:261, service.py:349) — the DB side
of "save the message id against the conversation" is already done. What's
missing is (a) capturing the *right* id, and (b) reading a matching id back
out of the inbound payload.

## 2. How email threading actually works (the mechanism being proposed)

Every email has a `Message-ID` header — a globally unique token the
*sending* MTA stamps on, e.g. `<abc123@mail.example.com>`. When a client
replies, it (not the server) adds:

- `In-Reply-To`: the `Message-ID` of the message being replied to directly.
- `References`: the full chain of `Message-ID`s from thread root to most
  recent — so even if a reply is to message #3 of a thread, message #1's id
  is still present.

This is exactly what Gmail/Outlook use for their own thread view, and what
Intercom/Front/Help Scout use for conversation matching — see sources below.
Because it's a *header*, it survives independently of whatever `To`/`Reply-To`
address the supplier's client fills in — which is the whole appeal here: the
Reply-To can go back to being one boring, stable, per-user address (this
project already builds one: [`build_sending_email`](src/modules/email_delivery/providers/base.py#L99)), and the *precise*
conversation is recovered from the header chain instead of the address.

## 3. Provider capability check (this is the part that actually gates feasibility)

### SendGrid

| Question | Answer | Confidence |
|---|---|---|
| Does Inbound Parse expose raw headers? | **Yes.** The default (non-raw) POST includes a `headers` field described as *"The raw headers of the email"* — a text blob containing `In-Reply-To`, `References`, `Message-ID`, etc. | Confirmed via docs |
| Is this field currently parsed? | **No.** [`SendGridWebhookParser.parse`](src/modules/email_delivery/webhooks/sendgrid.py#L62) only reads `from`/`to`/`subject`/`text`/`html`/`envelope`/`dkim`/`SPF`/`spam_score`/`attachments*` — `headers` is dropped on the floor today. | Confirmed by reading the code |
| Does the `X-Message-Id` returned by `/v3/mail/send` equal the `Message-ID` SMTP header on the outgoing mail? | **No — they are different values.** `X-Message-Id` is SendGrid's own event-tracking id, generated per-request, distinct from the RFC 5322 `Message-ID` header. **This is the critical gotcha**: [`SendGridEmailProvider.send_email`](src/modules/email_delivery/providers/sendgrid.py#L182) currently stores `X-Message-Id` as `provider_message_id` — that value will **never** show up in a supplier's `In-Reply-To`/`References`, so a DB lookup keyed on it would never match anything. | Confirmed via docs/support articles |
| Can you set your own `Message-ID`? | Yes — SendGrid explicitly documents passing a custom SMTP-ID via the `personalizations[].headers` object, e.g. `{"Message-ID": "<123@example.com>"}`. | Confirmed via docs |

### EngageLab (= "SendCloud" — same product, older brand name)

The forbidden custom-header list returned by their send API (`DKIM-Signature,
Received, Sender, Date, From, To, Reply-To, Cc, Bcc, Subject, Content-Type,
Content-Transfer-Encoding, X-SENDCLOUD-UUID, X-SENDCLOUD-LOG, ...`) still
carries the `X-SENDCLOUD-*` prefix — confirming EngageLab and "SendCloud" are
the same underlying email platform. There's only one provider to evaluate
here, not two.

| Question | Answer | Confidence |
|---|---|---|
| Does the inbound route payload expose `In-Reply-To`/`References`? | **Unconfirmed either way.** The documented example under `response.response_data.headers` only shows `Cc/To/Content-Type/From/MIME-Version/Date/Subject` — but that may just be the sample email used in the doc, not an exhaustive allowlist. | Needs a live test (see §6) |
| Is there a guaranteed fallback? | **Yes.** `response.response_data.raw_message` (full raw MIME, already parsed today for attachments in [`_extract_attachments`](src/modules/email_delivery/webhooks/engagelab.py#L208) via `email.message_from_string`) — headers can be read off that `email.message.Message` object with total reliability, since it's the actual MIME source. | Confirmed by existing code path |
| Can you set your own `Message-ID`? | `Message-ID` is **not** on the forbidden custom-header list, so the `body.headers` field (documented, up to 1KB) probably allows it — but the docs stop short of confirming the server won't silently overwrite it. | Needs a live test |
| Side finding (not in scope, worth a ticket) | EngageLab's webhook docs describe real HMAC verification (`X-WebHook-Timestamp` / `X-WebHook-AppKey` / `X-WebHook-Signature`), but [`WebhookParserMaster.verify_signature`](src/modules/email_delivery/webhooks/base.py#L112) currently just returns `True` unconditionally for both providers. Unrelated to this task, but flagged since it surfaced during this research. | — |

## 4. Why this can't be the *only* mechanism

Header-based threading is the industry standard, but it is not universal:

- **Forwards, not replies.** A supplier who forwards your RFQ to a colleague,
  who then replies, generates a *new* `Message-ID` chain with no relation to
  yours. (This is precisely why `parse_conv_id_from_body`'s `CONV-` footer
  exists today — it's forward-proof because the footer text travels with the
  quoted body.)
- **Brand-new compose.** A supplier who starts a fresh email instead of
  hitting "Reply" carries no `In-Reply-To`/`References` at all. This is
  exactly the case `_match_new_thread` exists for.
- **Corporate security gateways** (Mimecast, Proofpoint, some O365 tenants)
  are known to rewrite or strip `Message-ID`/`References` during
  sanitization.
- **Provider-side stripping.** Whether EngageLab's structured `headers`
  object passes these through is, per §3, unverified — if it doesn't, the raw
  MIME fallback must be used unconditionally for that provider.

None of this is a reason not to do it — it's the reason to do it *as the new
primary match*, ahead of the existing fallbacks, not as a replacement for
them.

## 5. Recommended design

**Matching order (new):** References/In-Reply-To chain → body `CONV-`
footer → sending-email + most-recent-conversation heuristic.

1. **Stop encoding the conv id in the address.** Replace the per-conversation
   `reply_to = provider.build_dynamic_email(user_name, token)` call in
   [`create_conversation`](src/modules/email_delivery/service.py#L157) with
   the already-existing stable address, `provider.build_sending_email(user_name)`.
   `build_dynamic_email` / `parse_dynamic_email` and the two legacy regex
   patterns in `parse_dynamic_email` can then be deleted outright.

2. **Mint and set an explicit outbound `Message-ID`**, independent of
   whatever id the provider's API response hands back (needed because
   SendGrid's `X-Message-Id` is proven not to be the wire header — §3).
   Something like `f"<{conversation.token}.{uuid4().hex}@{outbound_domain}>"`
   passed via each provider's custom-headers field
   (`personalizations[].headers["Message-ID"]` for SendGrid; `body.headers`
   for EngageLab, pending the live test in §6). Embedding the token in the
   *Message-ID itself* means matching never needs a DB round trip at all — a
   regex identical in spirit to `parse_conv_id_from_body` extracts the token
   straight out of `In-Reply-To`/`References`. Still persist the value into
   `provider_message_id` for audit/analytics, but treat the DB row as a
   record, not the lookup path.

3. **Extract `In-Reply-To`/`References` on inbound:**
   - SendGrid: parse the `headers` form field (currently unread) with a
     small regex/`email.message_from_string(f"{headers}\n\n")` trick, same
     idea already used for EngageLab's raw MIME.
   - EngageLab: try `response_data.headers` first; if `In-Reply-To`/
     `References` aren't present there, fall back to parsing them out of the
     already-fetched `raw_message`/`raw_message_url` MIME object (no new
     network call — that object is already produced by
     `_extract_attachments`, just not read for headers today).

4. **New matching function**, call it `parse_conv_id_from_headers`, mirroring
   `parse_conv_id_from_body`'s signature/behaviour (`base.py:143`): search
   `References` then `In-Reply-To` for the `<{token}.{hex}@...>` pattern.
   Wire it into `_record_inbound` (`service.py:505`) as the first matching
   attempt, ahead of the existing `parse_dynamic_email`/body-footer calls.

5. **New `MatchedVia` member** — `HEADER_REFERENCE = "header_reference"` —
   alongside the existing `DYNAMIC_ADDRESS`/`BODY_REFERENCE`/`NEW_THREAD` in
   [`enums.py`](src/modules/email_delivery/enums.py#L62), so the thread view
   / analytics can distinguish how each reply was actually matched (useful
   for measuring, post-rollout, what fraction of real supplier replies
   preserve threading headers — that number is the real answer to "is this
   safe to lean on," and it's provider- and even supplier-mail-client
   dependent).

6. **Keep both fallbacks exactly as they are.** `parse_conv_id_from_body` and
   `_match_new_thread` don't need to change at all — they're already the
   correct safety net for the cases in §4.

## 6. Before flipping this in production

- **Send yourself a real test RFQ through each provider**, reply from a few
  real clients (Gmail web, Outlook desktop, a phone mail app) and inspect
  the inbound webhook payload for each: confirm whether `Message-ID` set via
  step 2 actually (a) survives on the outbound wire and (b) reappears in
  `In-Reply-To`/`References` on the reply. This single test resolves every
  "needs a live test" line in the §3 table.
- **If EngageLab's structured `headers` object drops the threading headers**,
  hard-code the raw-MIME fallback as the only path for that provider — no
  code-breaking risk, since the raw MIME parse is already implemented for
  attachments.
- **Roll out gated by the new `MatchedVia.HEADER_REFERENCE`** — ship it
  alongside the existing fallbacks (already the plan in §5) rather than
  removing the old dynamic-address path in the same change, so nothing
  regresses if headers turn out to be less reliable than expected for either
  provider.

## Sources

- [SendGrid — Setting up the Inbound Parse Webhook](https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook) — confirms the `headers` field in the default payload.
- [SendGrid — X-Message-ID glossary entry](https://www.twilio.com/docs/sendgrid/glossary/x-message-id) — confirms `X-Message-Id` ≠ the SMTP `Message-ID` header.
- [SendGrid — Google Threads Caused By Same X-Message-IDs](https://support.sendgrid.com/hc/en-us/articles/4416182514587-Google-Threads-Caused-By-Same-X-Message-IDs) — background on SendGrid's SMTP-ID/Message-ID relationship.
- [EngageLab — Email Webhook docs](https://www.engagelab.com/docs/email/webhook/webhook) — inbound route payload shape, `raw_message`/`raw_message_url`, HMAC signature scheme.
- [EngageLab — Trigger Email send API](https://www.engagelab.com/docs/email/rest-api/deliverlies) — custom `headers` field and forbidden-header list (source of the `X-SENDCLOUD-*` naming confirming EngageLab = SendCloud).
- [MailerSend — Email Threads guide](https://developers.mailersend.com/guides/creating-email-threads) — general `In-Reply-To`/`References` mechanics.
- [Intercom — Email threading](https://www.intercom.com/help/en/articles/7996715-email-threading) — real-world helpdesk product confirming unique `Message-ID` + header-based matching as their approach, and its edge cases.
