"""Mock validation, iteration completion, snapshots, and final outcomes."""

from typing import Any, Literal

from ali_diagnosis.domain import StructuredDiagnosis, UnresolvedDiagnosis, UnresolvedScope

from ..state import DiagnosisRuntimeState, DiagnosticSnapshot

MockValidationDecision = Literal["accept", "what", "why"]


def validation(
    state: DiagnosisRuntimeState,
    *,
    decisions: tuple[MockValidationDecision, ...],
    max_refinement_loops: int,
) -> dict[str, Any]:
    """Complete one iteration, snapshot it, and accept, refine, or exhaust."""
    decision = decisions[min(state.iteration_count, len(decisions) - 1)]
    iteration_count = state.iteration_count + 1
    loop_count = state.loop_count
    final_result = None
    if decision == "accept":
        final_result = StructuredDiagnosis(
            diagnosis_run_id=state.request.diagnosis_run_id,
            learner_id=state.request.learner_id,
            subject_ref=state.subject_ref,
            what=state.synthesis_candidate["what"],
            why=state.synthesis_candidate["why"],
        )
    elif loop_count >= max_refinement_loops:
        final_result = UnresolvedDiagnosis(
            diagnosis_run_id=state.request.diagnosis_run_id,
            learner_id=state.request.learner_id,
            subject_ref=state.subject_ref,
            unresolved_scope=UnresolvedScope(decision),
            reason="Mock diagnosis remains unresolved at the refinement-loop limit.",
            relevant_sources=[
                source
                for finding in state.what_findings
                for source in finding.supporting_sources
            ],
        )
    else:
        loop_count += 1
    validation_result = {
        "is_mock": True,
        "decision": "exhausted" if isinstance(final_result, UnresolvedDiagnosis) else decision,
    }
    # Compare against previously snapshotted results, not per-node logs.
    previous_information = {
        name: result
        for snapshot in state.diagnostic_history
        for name, result in snapshot.new_information.items()
    }
    previous_capability_count = sum(
        len(snapshot.new_capability_results) for snapshot in state.diagnostic_history
    )
    snapshot = DiagnosticSnapshot(
        current_stage="validation",
        iteration_count=iteration_count,
        loop_count=loop_count,
        what_findings=state.what_findings,
        why_hypotheses=state.why_hypotheses,
        new_information={
            name: result
            for name, result in state.retrieved_information.items()
            if name not in previous_information or result != previous_information[name]
        },
        new_capability_results=state.capability_results[previous_capability_count:],
        synthesis_candidate=state.synthesis_candidate,
        validation_result=validation_result,
    )
    return {
        "current_stage": "validation",
        "iteration_count": iteration_count,
        "loop_count": loop_count,
        "latest_validation_result": validation_result,
        "diagnostic_history": [*state.diagnostic_history, snapshot],
        "final_result": final_result,
    }
