"""API layer — the FastAPI HTTP surface.

This layer is intentionally thin: it validates requests, delegates to the
feature modules under ``src.modules``, and shapes responses (JSON or HTML).
It contains no business logic of its own.

Deliberately does not re-export :func:`~src.api.main.create_app` here —
importing any ``src.api.*`` submodule (e.g. ``src.api.templating``, used by
every module's page routes) would otherwise eagerly import and build the
whole app, creating a circular import back into the modules that are still
being initialized. Import it directly: ``from src.api.main import create_app``.
"""
