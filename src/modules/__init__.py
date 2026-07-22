"""Feature modules — each a self-contained folder covering one capability.

Every module owns its own models, schemas, exceptions, service logic,
FastAPI dependency wiring, and routes. Open one module's folder and
everything needed to understand or change that feature is right there,
rather than spread across shared ``domain``/``services``/``api`` layers.

Available modules:
    auth         -- user registration, login, session management
    sample_data  -- LLM-backed sample email-query generation and history
"""
