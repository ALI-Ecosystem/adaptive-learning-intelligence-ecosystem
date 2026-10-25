"""Temporary example information with no external source connections."""

from __future__ import annotations

from typing import Any

from ali_diagnosis.domain import DiagnosisRunRequest


class ExampleInformationProvider:
    """Return a temporary diagnostic example without reading any real source."""

    def get_information(
        self, request: DiagnosisRunRequest
    ) -> dict[str, Any]:
        """Return a fresh example response labeled as temporary and unconnected."""
        return {
            "message": "Temporary example diagnostic information.",
            "provenance": {
                "source_name": "temporary_example_information",
                "is_temporary_example": True,
                "real_source_connected": False,
                "notice": (
                    "Temporary example information only. No real information source "
                    "is connected. The content is synthetic and is not "
                    "diagnostic evidence."
                ),
            },
        }
