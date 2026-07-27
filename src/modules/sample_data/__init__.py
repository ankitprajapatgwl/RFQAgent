"""Sample-data module — hard-coded sample RFQ scenarios for the dashboard picker.

Everything needed to understand or change this feature lives in this one
folder, except the ``EmailType`` vocabulary itself — shared with the
``email_draft`` module — which lives in ``modules/email_patterns``.

    fixtures/rfq_samples.json  -- the 5 hand-authored sample RFQ scenarios
    schemas.py                 -- Pydantic response contracts
    service.py                 -- SampleDataService (reads the fixture file)
    deps.py                    -- FastAPI dependency wiring
    router.py                  -- JSON API (/api/v1/sample-queries)

``api_router`` is the piece the app factory mounts.
"""

from src.modules.sample_data.router import router as api_router

__all__ = ["api_router"]
