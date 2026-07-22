"""Integrations layer — infrastructure shared across every module.

Holds the relational database (engine/session management and the shared
declarative :class:`Base`) and the Anthropic :class:`LLMClient`. The LLM
client lives here — rather than inside one feature module — because both
``sample_data`` and ``email_draft`` call the model, and shared infrastructure
belongs in one place so feature modules stay independent of each other.
"""

from src.integrations.database import Base, Database, get_database, get_db_session
from src.integrations.llm import LLMClient, LLMGenerationError, get_llm_client

__all__ = [
    "Base",
    "Database",
    "LLMClient",
    "LLMGenerationError",
    "get_database",
    "get_db_session",
    "get_llm_client",
]
