"""Integrations layer — everything that talks to the outside world.

For the authentication feature this is the relational database; for sample
query generation it is the Anthropic LLM. Keeping these in their own layer
means the services above depend on an abstraction, not a concrete database
engine or LLM SDK.
"""

from src.integrations.database import Database, get_database
from src.integrations.llm_client import LLMClient, LLMGenerationError

__all__ = ["Database", "LLMClient", "LLMGenerationError", "get_database"]
