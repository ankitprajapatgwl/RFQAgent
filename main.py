"""Convenience entry point for running the RFQ Agent auth service.

Run directly with ``python main.py`` (manual mode) or, in production/containers,
prefer the ASGI app path ``src.api.main:app`` behind uvicorn. This module
only wires uvicorn to the configured host/port.
"""

import uvicorn

from src.config import get_settings


def main() -> None:
    """Start the ASGI server using values from application settings."""
    settings = get_settings()
    uvicorn.run(
        "src.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
