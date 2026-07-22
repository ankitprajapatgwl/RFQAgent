"""Shared attachment storage for the email-delivery module.

Both inbound parsing (a supplier reply's files) and outbound sending (files a
user attaches to a draft or RFQ) need to persist attachment bytes to local
storage and hand the UI/DB a small metadata record. That behaviour lives here,
in one place, so it is identical in both directions and free of any provider or
HTTP concept.

:class:`RawAttachment` is the in-memory representation; :func:`store_attachments`
writes each one under :attr:`~src.config.Settings.attachments_dir` and returns
the metadata rows the repository persists as ``email_attachments``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from src.config import Settings
from src.observability import get_logger

logger = get_logger(__name__)


@dataclass
class RawAttachment:
    """An attachment held in memory before it is written to disk.

    Attributes:
        filename: Original filename supplied by the sender/uploader.
        content_type: MIME type, e.g. ``"application/pdf"``.
        content: Raw file bytes, ready to be written to disk.
    """

    filename: str
    content_type: str
    content: bytes


def _safe_filename(filename: str) -> str:
    """Strip directory components and unsafe characters from a name.

    Prevents path traversal (``../``) and keeps only characters that are safe
    on common filesystems.

    Args:
        filename: The sender/uploader-supplied filename.

    Returns:
        A sanitised basename, never empty.
    """
    base = filename.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return cleaned or "attachment"


def store_attachments(
    settings: Settings, conv_id: str, attachments: list[RawAttachment]
) -> list[dict[str, Any]]:
    """Write attachment bytes to disk and return their metadata.

    Each file is saved under :attr:`Settings.attachments_dir` with a
    collision-resistant name (``{conv_id}_{batch}_{index}_{filename}``) and
    exposed at ``{attachments_url_path}/{name}``. The per-call ``batch`` token
    prevents a later attachment on the same conversation from overwriting an
    earlier one whose filename matches. A single unwritable file is logged and
    skipped rather than aborting the whole batch.

    Args:
        settings: Application settings (attachments dir + URL path).
        conv_id: The conversation the attachments belong to.
        attachments: In-memory attachments to persist.

    Returns:
        One metadata dict per saved file with keys ``filename``,
        ``content_type``, ``size`` and ``url``.
    """
    saved: list[dict[str, Any]] = []
    if not attachments:
        return saved

    directory = settings.attachments_dir
    directory.mkdir(parents=True, exist_ok=True)
    url_base = settings.attachments_url_path.rstrip("/")

    batch = uuid.uuid4().hex[:8]
    for index, att in enumerate(attachments, start=1):
        safe_base = _safe_filename(att.filename or f"file_{index}")
        safe_name = f"{conv_id}_{batch}_{index}_{safe_base}"
        path = directory / safe_name
        try:
            with open(path, "wb") as handle:
                handle.write(att.content)
        except OSError as exc:
            # A single bad attachment must not abort the whole reply/send.
            logger.error("Failed to save attachment %s: %s", safe_name, exc)
            continue
        saved.append(
            {
                "filename": att.filename,
                "content_type": att.content_type,
                "size": len(att.content),
                "url": f"{url_base}/{safe_name}",
            }
        )
        logger.debug("Saved attachment %s", safe_name)
    return saved
