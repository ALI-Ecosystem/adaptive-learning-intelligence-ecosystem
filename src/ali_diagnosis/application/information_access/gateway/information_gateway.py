"""Unified access to diagnostic information without source-specific dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ali_diagnosis.domain import DiagnosisRunRequest

from .diagnostic_information_source import DiagnosticInformationSource


class InformationGateway:
    """Retrieve and assemble information from configured diagnostic sources."""

    def __init__(self, sources: Mapping[str, DiagnosticInformationSource]) -> None:
        """Keep a copy of the named sources selected by application setup."""
        self._sources = dict(sources)

    def get_information(
        self, request: DiagnosisRunRequest
    ) -> dict[str, Any]:
        """Request information from each source and retain results under their names."""
        return {
            name: source.get_information(request)
            for name, source in self._sources.items()
        }
