"""Shared rendering engine for the project's BEGIN-IF/{{token}} email templates.

Every HTML template under ``templates/email_templates/`` (RFQ, follow-up,
negotiation) encodes the same two authoring conventions:

* ``<!-- BEGIN-IF: key --> ... <!-- END-IF: key -->`` — the enclosed block
  is kept only when ``key`` resolves to a true condition.
* ``{{token}}`` — replaced with the matching value, HTML-escaped.

Factored out of ``rfq_template.py`` so the follow-up/negotiation renderers
share one implementation instead of re-deriving the same regex engine.
"""

from __future__ import annotations

import html
import re

_CONDITIONAL_RE = re.compile(r"<!-- BEGIN-IF: (\w+) -->(.*?)<!-- END-IF: \1 -->", re.DOTALL)
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")

# Values that count as "no real answer" so a field left blank/placeholder
# doesn't render an empty section.
_PLACEHOLDER_VALUES = {"", "tbd", "n/a", "na", "todo", "unknown", "none"}


def has_value(value: str | None) -> bool:
    """Return whether ``value`` is a real, concrete answer (not blank/placeholder)."""
    return bool(value) and value.strip().lower() not in _PLACEHOLDER_VALUES


def combine(*parts: str) -> str:
    """Join the given parts that have a real value with an em dash separator."""
    return " — ".join(part.strip() for part in parts if has_value(part))


def render_template(template_text: str, values: dict[str, str], conditions: dict[str, bool]) -> str:
    """Fill a BEGIN-IF/{{token}} template with the given values and conditions.

    Args:
        template_text: The raw template HTML.
        values: Token name -> value to substitute (HTML-escaped).
        conditions: Conditional-block key -> whether to keep that block.

    Returns:
        The rendered HTML.
    """

    def _resolve_conditional(match: re.Match[str]) -> str:
        key, body = match.group(1), match.group(2)
        return body if conditions.get(key, False) else ""

    rendered = _CONDITIONAL_RE.sub(_resolve_conditional, template_text)
    return _TOKEN_RE.sub(lambda m: html.escape(values.get(m.group(1), "")), rendered)
