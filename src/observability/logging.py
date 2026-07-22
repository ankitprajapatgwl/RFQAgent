"""Structured logging configuration.

The coding standards forbid ``print()`` in library code (file ``04``, rule 2.4)
and require a single structured logger. This module configures a JSON-ish
line formatter and exposes :func:`get_logger` so every module logs the same way.
"""

import logging
import sys

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once for the whole process.

    Repeated calls are no-ops so importing modules cannot accidentally attach
    duplicate handlers.

    Args:
        level: Logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)

    # Align uvicorn's loggers with our handler to avoid duplicate lines.
    for uvicorn_logger in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(uvicorn_logger).handlers.clear()
        logging.getLogger(uvicorn_logger).propagate = True

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger.

    Args:
        name: Logger name, conventionally the caller's ``__name__``.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)
