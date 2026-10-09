"""Explicit in-memory registration and resolution of diagnostic instruments."""

from __future__ import annotations

from ali_diagnosis.domain.capabilities import CapabilityMetadata

from .diagnostic_capability import DiagnosticCapability


class CapabilityRegistry:
    """Make registered capabilities available without selecting or invoking them."""

    def __init__(self) -> None:
        """Start with no registered capabilities."""
        self._capabilities: dict[str, DiagnosticCapability] = {}

    def register(self, capability: DiagnosticCapability) -> None:
        """Register a capability by its stable name, rejecting duplicate names."""
        name = capability.metadata.name
        if name in self._capabilities:
            raise ValueError(f"Capability already registered: {name}")
        self._capabilities[name] = capability

    def resolve(self, name: str) -> DiagnosticCapability:
        """Return the named capability or raise KeyError when it is unavailable."""
        return self._capabilities[name]

    def list_metadata(self) -> tuple[CapabilityMetadata, ...]:
        """Describe available capabilities in registration order without running them."""
        return tuple(capability.metadata for capability in self._capabilities.values())
