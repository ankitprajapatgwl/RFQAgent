"""FastAPI dependency wiring for the sample-data module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.modules.sample_data.service import SampleDataService


def get_sample_data_service() -> SampleDataService:
    """Return a :class:`SampleDataService`."""
    return SampleDataService()


SampleDataServiceDep = Annotated[SampleDataService, Depends(get_sample_data_service)]
