"""Unit tests for the hard-coded sample RFQ data.

No LLM and no database are involved here — :class:`SampleDataService` just
reads and validates the bundled fixture file, so these tests guard against
the fixtures drifting out of sync with :data:`RFQ_FIELD_CATALOG`.
"""

from src.modules.email_patterns import RFQ_FIELD_CATALOG
from src.modules.sample_data.service import SampleDataService

_PLACEHOLDER_VALUES = {"", "tbd", "n/a", "na", "todo", "unknown", "none"}


def test_list_samples_returns_five_scenarios() -> None:
    samples = SampleDataService().list_samples()

    assert len(samples) == 5


def test_list_samples_have_unique_ids_and_labels() -> None:
    samples = SampleDataService().list_samples()

    assert len({sample.id for sample in samples}) == len(samples)
    assert len({sample.label for sample in samples}) == len(samples)


def test_every_sample_has_the_full_rfq_field_catalog() -> None:
    catalog_keys = {field.name for field in RFQ_FIELD_CATALOG}

    for sample in SampleDataService().list_samples():
        assert set(sample.fields) == catalog_keys


def test_every_sample_has_concrete_values_for_required_fields() -> None:
    required_fields = [field for field in RFQ_FIELD_CATALOG if field.required]

    for sample in SampleDataService().list_samples():
        for field in required_fields:
            value = sample.fields[field.name].strip().lower()
            assert value not in _PLACEHOLDER_VALUES, (
                f"{sample.id}: required field {field.name!r} is missing/placeholder"
            )
