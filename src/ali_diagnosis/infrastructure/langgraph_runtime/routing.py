"""Validation routing for the deterministic runtime proof."""

from langgraph.graph import END

from .state import DiagnosisRuntimeState


def route_validation(state: DiagnosisRuntimeState) -> str:
    """End on a final outcome; otherwise follow the mock refinement request."""
    if state.final_result is not None:
        return END
    return state.latest_validation_result["decision"]
