"""Read stored email attachments back into text the extractor can analyse.

Attachments can be *anything* a supplier sends. Text-shaped files (plain text,
CSV, JSON, HTML, Markdown, XML, ...) are read from disk and their contents made
available to the agent; genuinely binary files (PDF, images, spreadsheets, zips)
cannot be decoded without extra parsing dependencies, so they are represented by
a short, honest placeholder noting the filename and type rather than being
silently dropped or pretending to have been read.

All limits are bounded (per-file and total) so a large attachment can never blow
the LLM token budget (coding standards: token/cost guardrails).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import Settings
from src.observability import get_logger

logger = get_logger(__name__)

# Bounds that keep attachment text from blowing the LLM token budget.
_MAX_CHARS_PER_FILE = 12_000
_MAX_TOTAL_CHARS = 40_000

# Content types (and filename suffixes) we treat as safely text-decodable.
_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "application/csv",
    "application/x-ndjson",
    "application/yaml",
    "application/x-yaml",
}
_TEXT_SUFFIXES = (
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".log",
    ".rtf",
)


@dataclass(frozen=True)
class AttachmentRef:
    """The minimum an attachment needs to be located on disk and labelled.

    Attributes:
        filename: Original filename (for labelling in the prompt).
        url: The served URL stored on the attachment row; its basename is the
            on-disk filename under :attr:`Settings.attachments_dir`.
        content_type: MIME type, when known.
        size_bytes: Stored size, when known.
    """

    filename: str
    url: str
    content_type: str | None = None
    size_bytes: int | None = None


def _looks_textual(ref: AttachmentRef) -> bool:
    """Return whether an attachment is likely safe to decode as UTF-8 text."""
    content_type = (ref.content_type or "").lower()
    if content_type.startswith("text/"):
        return True
    if content_type in _TEXT_CONTENT_TYPES:
        return True
    return ref.filename.lower().endswith(_TEXT_SUFFIXES)


def read_attachment_texts(settings: Settings, attachments: list[AttachmentRef]) -> str:
    """Build a single delimited block of attachment content for the prompt.

    Text-shaped attachments are read from disk (bounded per file and in total);
    binary ones are represented by a ``[binary attachment ...]`` placeholder. A
    file that cannot be read is logged and noted rather than aborting the batch.

    Args:
        settings: Application settings (locates the attachments directory).
        attachments: The attachments to read.

    Returns:
        A human-readable, clearly-delimited string describing every attachment
        (empty string when there are none).
    """
    if not attachments:
        return ""

    directory = settings.attachments_dir
    parts: list[str] = []
    total_chars = 0

    for index, ref in enumerate(attachments, start=1):
        header = f"--- Attachment {index}: {ref.filename} ({ref.content_type or 'unknown type'})"
        if not _looks_textual(ref):
            parts.append(f"{header} ---\n[binary attachment — not text-readable]")
            continue

        name = (ref.url or "").rsplit("/", 1)[-1]
        path = directory / name if name else None
        if path is None or not path.exists():
            parts.append(f"{header} ---\n[attachment file not found on disk]")
            continue

        if total_chars >= _MAX_TOTAL_CHARS:
            parts.append(f"{header} ---\n[skipped — attachment text budget reached]")
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read attachment %s: %s", name, exc)
            parts.append(f"{header} ---\n[could not read attachment]")
            continue

        remaining = _MAX_TOTAL_CHARS - total_chars
        clipped = text[: min(_MAX_CHARS_PER_FILE, remaining)]
        if len(clipped) < len(text):
            clipped += "\n[... truncated ...]"
        total_chars += len(clipped)
        parts.append(f"{header} ---\n{clipped}")

    return "\n\n".join(parts)
