"""Verify capability metadata, registration, and resolution without an execution API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ali_diagnosis.application.capabilities.capability_registry import CapabilityRegistry
from ali_diagnosis.application.capabilities.diagnostic_capability import DiagnosticCapability
from ali_diagnosis.domain import CapabilityMetadata


def metadata(name: str = "test-instrument") -> CapabilityMetadata:
    return CapabilityMetadata(
        name=name,
        purpose="Exercise the common boundary in tests only.",
        supported_evidence=("Test observations",),
        required_context=(),
        applicability="Synthetic test inputs only.",
        input_contract="Defined by the concrete capability.",
        output_contract="Typed observations defined by the concrete capability.",
        limitations="Provides no educational or diagnostic conclusions.",
        confidence_uncertainty_semantics="No confidence estimate is produced.",
        research_basis="Test double only; not a research-backed capability.",
        implementation_version="test-v1",
    )


class StubCapability:
    """Metadata-only test double with no execution operation."""

    def __init__(self, name: str = "test-instrument") -> None:
        self.metadata = metadata(name)


@pytest.mark.parametrize("field", tuple(CapabilityMetadata.model_fields))
def test_every_descriptive_metadata_field_is_required(field: str) -> None:
    payload = metadata().model_dump()
    del payload[field]
    with pytest.raises(ValidationError):
        CapabilityMetadata.model_validate(payload)


def test_metadata_rejects_static_provenance_and_is_immutable() -> None:
    description = metadata()
    with pytest.raises(ValidationError):
        CapabilityMetadata.model_validate({**description.model_dump(), "provenance": []})
    with pytest.raises(ValidationError):
        description.name = "changed"
    with pytest.raises(ValidationError):
        CapabilityMetadata.model_validate({**description.model_dump(), "name": "   "})


def test_registry_accepts_metadata_only_capabilities_and_preserves_registration_order() -> None:
    registry = CapabilityRegistry()
    assert registry.list_metadata() == ()
    first: DiagnosticCapability = StubCapability("first")
    second: DiagnosticCapability = StubCapability("second")
    registry.register(first)
    registry.register(second)

    assert registry.list_metadata() == (first.metadata, second.metadata)
    assert registry.resolve("first") is first
    assert registry.resolve("second") is second


def test_duplicate_registration_preserves_original_and_unknown_name_fails() -> None:
    registry = CapabilityRegistry()
    original = StubCapability()
    registry.register(original)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubCapability())
    assert registry.resolve(original.metadata.name) is original
    with pytest.raises(KeyError):
        registry.resolve("unavailable")
