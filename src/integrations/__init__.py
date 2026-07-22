"""Integrations layer — everything that talks to the outside world.

For the authentication feature this is the relational database. Keeping it in
its own layer means the services above depend on an abstraction (the session
factory), not on a concrete database engine.
"""

from src.integrations.database import Database, get_database

__all__ = ["Database", "get_database"]
