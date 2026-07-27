"""Static sample RFQ data.

:class:`SampleDataService` reads a fixed set of hand-authored RFQ scenarios
from ``fixtures/rfq_samples.json`` (bundled with this module) so a user can
pick a ready-made example instead of typing one out. No LLM call and no
database persistence are involved — the list is the same for every user.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.modules.sample_data.schemas import SampleRfqRead

_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "rfq_samples.json"


@lru_cache(maxsize=1)
def _load_samples() -> tuple[SampleRfqRead, ...]:
    """Parse and validate the bundled RFQ sample fixtures, once per process."""
    raw = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    return tuple(SampleRfqRead.model_validate(item) for item in raw)


class SampleDataService:
    """Serves the hard-coded list of sample RFQ scenarios."""

    def list_samples(self) -> list[SampleRfqRead]:
        """Return every available sample RFQ scenario.

        Returns:
            The bundled sample RFQs, in fixture-file order.
        """
        return list(_load_samples())
