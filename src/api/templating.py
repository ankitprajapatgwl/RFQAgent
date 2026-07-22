"""Shared Jinja2 template environment for server-rendered HTML pages."""

from fastapi.templating import Jinja2Templates

from src.config.settings import PROJECT_ROOT

TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

# Single, shared templates instance used by every page route.
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
