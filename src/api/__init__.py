"""API layer — the FastAPI HTTP surface.

This layer is intentionally thin: it validates requests, delegates to the
services layer, and shapes responses (JSON or HTML). It contains no business
logic of its own.
"""

from src.api.main import create_app

__all__ = ["create_app"]
