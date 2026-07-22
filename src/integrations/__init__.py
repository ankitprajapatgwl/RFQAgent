"""Integrations layer — infrastructure shared across every module.

Currently just the relational database (engine/session management and the
shared declarative :class:`Base`). Anything module-specific — like the
Anthropic LLM client used only by ``modules/sample_data`` — lives inside that
module instead, so the module stays self-contained.
"""

from src.integrations.database import Base, Database, get_database, get_db_session

__all__ = ["Base", "Database", "get_database", "get_db_session"]
