"""Extract only the newly written portion of an inbound reply.

A supplier's reply almost always carries the entire prior conversation quoted
beneath the few new lines they actually typed — the Gmail "On … wrote:" block,
Outlook's ``-----Original Message-----`` / ``From:`` header, ``>``-prefixed
quoted lines, and our own ``Reference: CONV-…`` footer. Persisting all of that
bloats storage and makes the thread view unreadable.

These helpers trim a body down to just the new content:

* :func:`extract_reply_text` — for the plain-text body.
* :func:`extract_reply_html` — for the HTML body.

Both are conservative: if trimming would leave nothing, the original body is
returned unchanged, so a parsing misfire can never silently drop a real reply.
"""

from __future__ import annotations

import re

# A quoted-reply attribution line, allowing the common case where Gmail wraps
# it across two lines, e.g.::
#
#     On Wed, Jul 22, 2026 at 6:12 PM Ankit Prajapat
#     <ankit@example.com> wrote:
#
# The span between "On " and "wrote:" is length-bounded so a stray "On …" in
# real prose followed much later by "wrote:" cannot swallow the whole message.
_ON_WROTE = re.compile(r"(?ms)^On\s.{0,300}?\bwrote:\s*$")

# Single-line markers that begin a quoted/forwarded block. Everything from the
# first matching line onward is dropped.
_LINE_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^\s*_{5,}\s*$"),  # Outlook's horizontal divider
    re.compile(r"^\s*From:\s.+", re.IGNORECASE),  # Outlook quoted-header block
    re.compile(r"^\s*Reference:\s*CONV-[A-Fa-f0-9]", re.IGNORECASE),  # our own footer
    re.compile(r"^\s*click to unsubscribe", re.IGNORECASE),
)

# HTML containers that wrap the quoted history. Truncating at the earliest one
# removes the quoted thread; the visible new content always precedes it.
_HTML_QUOTE_MARKER = re.compile(
    r"""(
        <div[^>]*class="[^"]*gmail_quote[^"]*"      # Gmail quoted thread
      | <div[^>]*class="[^"]*gmail_attr[^"]*"        # Gmail "On ... wrote:" line
      | <blockquote                                   # generic quoted block
      | <div[^>]*id="divRplyFwdMsg"                  # Outlook reply/forward header
      | <div[^>]*id="appendonsend"                   # Outlook new-vs-quoted divider
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def extract_reply_text(text: str) -> str:
    """Return only the newly written lines of a plain-text reply.

    Trims everything from the first quoted/forwarded marker onward (a wrapped
    "On … wrote:" attribution, an Outlook header block, a ``>`` quoted line, or
    our ``Reference: CONV-…`` footer).

    Args:
        text: The raw plain-text body of the inbound email.

    Returns:
        The trimmed new content. If trimming leaves nothing (e.g. an all-quoted
        top-post), the original body (stripped) is returned unchanged.
    """
    if not text:
        return text or ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # 1) Cut at a (possibly wrapped) "On ... wrote:" attribution.
    match = _ON_WROTE.search(normalized)
    working = normalized[: match.start()] if match else normalized

    # 2) Cut at the first single-line marker or ``>`` quoted line.
    lines = working.split("\n")
    cut_at: int | None = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            cut_at = index
            break
        if any(pattern.match(line) for pattern in _LINE_MARKERS):
            cut_at = index
            break
    if cut_at is not None:
        lines = lines[:cut_at]

    result = "\n".join(lines).strip()
    # Never drop a real reply on an over-aggressive trim.
    return result or normalized.strip()


def extract_reply_html(html_body: str) -> str:
    """Return only the newly written portion of an HTML reply.

    Truncates at the first known quoted-history container (Gmail's
    ``gmail_quote`` / ``gmail_attr``, a ``<blockquote>``, or Outlook's
    reply/forward header block).

    Args:
        html_body: The raw HTML body of the inbound email.

    Returns:
        The HTML up to the quoted block. If no quoted block is found, or
        trimming leaves nothing, the original HTML (stripped) is returned.
    """
    if not html_body:
        return html_body or ""

    match = _HTML_QUOTE_MARKER.search(html_body)
    if match is None:
        return html_body
    trimmed = html_body[: match.start()].strip()
    return trimmed or html_body.strip()
