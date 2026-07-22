"""Unit tests for inbound reply quote-stripping."""

from src.modules.email_delivery.reply_extraction import extract_reply_html, extract_reply_text

_GMAIL_REPLY = """Click on Reply Button

On Wed, Jul 22, 2026 at 6:12 PM Ankit Prajapat
<ankitprajapat@mail.jobsetu.online> wrote:

> Dear Wei Chen,
>
> I am writing on behalf of Northbridge Industrial Supplies Ltd.
>
> Kind regards,
> Ankit Prajapat
> 7772058196
"""


def test_strips_gmail_wrapped_attribution_and_quote() -> None:
    assert extract_reply_text(_GMAIL_REPLY) == "Click on Reply Button"


def test_strips_outlook_original_message_block() -> None:
    body = (
        "Thanks, that works for us.\n\n"
        "-----Original Message-----\n"
        "From: buyer@x.com\nSubject: RFQ\n\n> quoted\n"
    )
    assert extract_reply_text(body) == "Thanks, that works for us."


def test_strips_leading_quote_lines() -> None:
    body = "Sounds good.\n> old line one\n> old line two"
    assert extract_reply_text(body) == "Sounds good."


def test_strips_our_reference_footer() -> None:
    body = "New price is $10.\n\nReference: CONV-3FA9C1B2 | USR-42 | THREAD-3FA9C1B2"
    assert extract_reply_text(body) == "New price is $10."


def test_no_quote_left_untouched() -> None:
    body = "Just a plain reply with no quoted history."
    assert extract_reply_text(body) == body


def test_all_quoted_falls_back_to_original() -> None:
    # A degenerate all-quoted body must never be reduced to nothing.
    body = "> everything is quoted\n> more quoted"
    assert extract_reply_text(body) == body


def test_empty_input() -> None:
    assert extract_reply_text("") == ""
    assert extract_reply_html("") == ""


def test_html_truncates_at_gmail_quote() -> None:
    html = (
        "<div>Sure, see below.</div>"
        '<div class="gmail_quote"><blockquote>old thread</blockquote></div>'
    )
    assert extract_reply_html(html) == "<div>Sure, see below.</div>"


def test_html_truncates_at_blockquote() -> None:
    html = "<p>Confirmed.</p><blockquote>previous message</blockquote>"
    assert extract_reply_html(html) == "<p>Confirmed.</p>"


def test_html_without_quote_left_untouched() -> None:
    html = "<p>Nothing quoted here.</p>"
    assert extract_reply_html(html) == html
