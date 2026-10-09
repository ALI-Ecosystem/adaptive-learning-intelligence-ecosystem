"""Common metadata boundary for registered diagnostic capabilities."""

from __future__ import annotations

from typing import Protocol

from ali_diagnosis.domain.capabilities import CapabilityMetadata


class DiagnosticCapability(Protocol):
    """Expose a capability's identity and description without prescribing execution."""

    @property
    def metadata(self) -> CapabilityMetadata:
        """Return the stable description of this registered implementation."""
        ...
