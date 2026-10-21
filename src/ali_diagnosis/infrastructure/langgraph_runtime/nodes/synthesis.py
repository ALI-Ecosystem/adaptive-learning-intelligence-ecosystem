"""Mock synthesis stage behavior."""

from typing import Any

from ..state import DiagnosisRuntimeState


def synthesis(state: DiagnosisRuntimeState) -> dict[str, Any]:
    """Combine mock conclusions without adding reasoning or quality claims."""
    return {
        "current_stage": "synthesis",
        "synthesis_candidate": {
            "is_mock": True,
            "what": state.what_findings,
            "why": state.why_hypotheses,
        },
    }
