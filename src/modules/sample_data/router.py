"""JSON API routes for sample RFQ data.

Backs the dashboard's "Select Sample RFQ Data" picker: list the hard-coded
sample RFQ scenarios a user can load into their current draft.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.modules.auth.deps import RequiredCookieUserDep
from src.modules.sample_data.deps import SampleDataServiceDep
from src.modules.sample_data.schemas import SampleRfqRead

router = APIRouter(prefix="/api/v1", tags=["sample-data"])


@router.get(
    "/sample-queries",
    response_model=list[SampleRfqRead],
    summary="List the hard-coded sample RFQ scenarios",
)
def list_sample_rfqs(
    _current_user: RequiredCookieUserDep,
    sample_data_service: SampleDataServiceDep,
) -> list[SampleRfqRead]:
    """Return every bundled sample RFQ scenario.

    Args:
        _current_user: The authenticated user (auth-gated, not used to filter
            results — the sample list is the same for everyone).
        sample_data_service: Injected sample-data service.

    Returns:
        The bundled sample RFQs.
    """
    return sample_data_service.list_samples()
