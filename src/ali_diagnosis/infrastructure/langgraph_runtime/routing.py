"""Route any goal using the validated decision reflected in graph state."""

from langgraph.graph import END

from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState


def route_stage(state: DiagnosisRuntimeState) -> str:
    """End on a published outcome; otherwise follow the agent-selected goal."""
    if state.final_result is not None:
        return END
    return state.current_stage
