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
        self, request: DiagnosisRunRequest, *, source_names: tuple[str, ...] | None = None
    ) -> dict[str, Any]:
        """Request information from each source and retain results under their names."""
        names = tuple(self._sources) if source_names is None else source_names
        # Validate the entire selection before performing any source calls.
        if len(names) != len(set(names)):
            raise ValueError("Duplicate information source selection")
        for name in names:
            if name not in self._sources:
                raise KeyError(name)
        return {name: self._sources[name].get_information(request) for name in names}

    def list_sources(self) -> tuple[str, ...]:
        """Expose configured source identities without retrieving their contents."""
        return tuple(self._sources)
