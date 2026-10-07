"""Source contract for diagnostic information without a fixed content schema."""

from __future__ import annotations

from typing import Any, Protocol

from ali_diagnosis.domain import DiagnosisRunRequest


class DiagnosticInformationSource(Protocol):
    """Supply diagnostic information behind the gateway boundary."""

    def get_information(
        self, request: DiagnosisRunRequest
    ) -> dict[str, Any]:
        """Return information for the diagnosis request without a fixed source schema."""
        ...
