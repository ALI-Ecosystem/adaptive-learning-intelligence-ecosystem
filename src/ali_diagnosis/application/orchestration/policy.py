"""Apply typed stage decisions and enforce domain/provenance quality gates."""

from pydantic import ValidationError

from ali_diagnosis.domain import (
    DiagnosticArtifact, DiagnosticArtifactType, DiagnosticFinding,
    DiagnosticSourceKind, DiagnosticSourceReference, RootCauseHypothesis,
    StructuredDiagnosis, UnresolvedDiagnosis,
)
from .contracts import (
    OUTPUT_TYPES, Stage, StageDecision, WhatDecision, WhyDecision,
    SynthesisDecision, ValidationDecision,
)
from .state import DiagnosisRuntimeState
from .errors import DiagnosisExecutionError, InvalidDecisionError, ToolRejectedError
from .tools import check_sources


def _check_claims(case: DiagnosisRuntimeState, findings: list[DiagnosticFinding], hypotheses: list[RootCauseHypothesis]) -> None:
    if any(finding.subject_ref not in [a.subject_ref for a in case.artifacts.values()] for finding in findings):
        raise ToolRejectedError("Finding subject must be resolved by a retrieved source")
    ids = {finding.finding_id for finding in findings}
    if len(ids) != len(findings) or len({h.hypothesis_id for h in hypotheses}) != len(hypotheses):
        raise ToolRejectedError("Duplicate claim identities")
    for claim in [*findings, *hypotheses]:
        check_sources(case, claim.supporting_sources)
        if claim.contradicting_sources:
            check_sources(case, claim.contradicting_sources)
    if any(set(h.explains_finding_ids) - ids for h in hypotheses):
        raise ToolRejectedError("Hypothesis references an unknown finding")


def _check_prerequisites(stage: Stage, *, what_complete: bool, why_complete: bool) -> None:
    if stage != "what" and not what_complete:
        raise ToolRejectedError(f"{stage} requires a completed WHAT assessment")
    if stage == "synthesis" and not why_complete:
        raise ToolRejectedError("Synthesis requires WHY investigation of the current WHAT")


def _validated_candidate(case: DiagnosisRuntimeState, candidate: StructuredDiagnosis) -> StructuredDiagnosis:
    if not case.what_complete or not case.why_complete:
        raise ToolRejectedError("Candidate requires completed WHAT and WHY assessments")
    candidate = StructuredDiagnosis.model_validate(candidate.model_dump())
    if (candidate.diagnosis_run_id != case.request.diagnosis_run_id
            or candidate.learner_id != case.request.learner_id
            or candidate.subject_ref != case.subject_ref):
        raise ToolRejectedError("Candidate identity differs from the retrieved case")
    _check_claims(case, candidate.what, candidate.why)
    if candidate.what != case.what_findings or candidate.why != case.why_hypotheses:
        raise ToolRejectedError("Revise WHAT/WHY before changing their synthesis")
    return candidate


def apply_decision(case: DiagnosisRuntimeState, decision: StageDecision) -> None:
    """Only validation may publish; new information or claims invalidate synthesis."""
    try:
        if case.final_result is not None:
            raise ToolRejectedError("Diagnosis already published")
        if not isinstance(decision, OUTPUT_TYPES[case.current_stage]):
            raise ToolRejectedError("Wrong stage response type")
        # Resource interruption may reach validation before WHAT completes.
        # Only its unresolved outcome gets this exception; acceptance stays strict.
        resource_unresolved = (case.finalization_reason is not None
                               and isinstance(decision, ValidationDecision)
                               and decision.decision == "unresolved")
        if not resource_unresolved:
            _check_prerequisites(case.current_stage, what_complete=case.what_complete,
                                 why_complete=case.why_complete)
        if case.finalization_reason and isinstance(decision, ValidationDecision) and decision.decision == "refine":
            raise ToolRejectedError("Final assessment must accept a valid current candidate or report unresolved")
        what_complete = case.what_complete or isinstance(decision, WhatDecision)
        why_complete = (isinstance(decision, WhyDecision)
                        or (case.why_complete and not isinstance(decision, WhatDecision)))
        # Check the proposed destination against the post-decision prerequisites
        # before changing state. Terminal validation does not navigate anywhere.
        if not isinstance(decision, ValidationDecision) or decision.decision == "refine":
            _check_prerequisites(decision.next_stage, what_complete=what_complete,
                                 why_complete=why_complete)
        if isinstance(decision, WhatDecision):
            _check_claims(case, decision.findings, [])
            case.what_findings = decision.findings
            # WHY may no longer explain the revised WHAT; revisit it explicitly.
            case.why_hypotheses = []
            case.synthesis_candidate = None
            case.latest_validation_result = None
        elif isinstance(decision, WhyDecision):
            _check_claims(case, case.what_findings, decision.hypotheses)
            case.why_hypotheses = decision.hypotheses
            case.synthesis_candidate = None
            case.latest_validation_result = None
        elif isinstance(decision, SynthesisDecision):
            candidate = decision.candidate
            if candidate is not None:
                candidate = _validated_candidate(case, candidate)
            case.synthesis_candidate = candidate
            case.latest_validation_result = None
        elif isinstance(decision, ValidationDecision):
            if decision.decision == "accept":
                if case.synthesis_candidate is None:
                    raise ToolRejectedError("Validation requires a current synthesis candidate")
                case.final_result = _validated_candidate(case, case.synthesis_candidate)
            elif decision.decision == "unresolved":
                if case.tool_failures:
                    raise DiagnosisExecutionError("Unrecovered tool failures prevented diagnosis")
                if case.subject_ref is None or not case.artifacts:
                    raise ToolRejectedError("Cannot diagnose uncertainty without retrieved evidence")
                refs = []
                for artifact in case.artifacts.values():
                    refs.extend(ref for ref in artifact.source_references if ref not in refs)
                    refs.append(DiagnosticSourceReference(
                        source_kind=(DiagnosticSourceKind.CAPABILITY_RESULT
                                     if artifact.artifact_type == DiagnosticArtifactType.CAPABILITY_RESULT
                                     else DiagnosticSourceKind.CONTEXT),
                        source_id=artifact.artifact_id,
                    ))
                case.final_result = UnresolvedDiagnosis(
                    diagnosis_run_id=case.request.diagnosis_run_id,
                    learner_id=case.request.learner_id, subject_ref=case.subject_ref,
                    unresolved_scope=decision.unresolved_scope,
                    reason=(f"Investigation interrupted by resource limits: {case.finalization_reason}. "
                            f"This is not evidence of a learner deficit. Final assessment: {decision.reason}"
                            if resource_unresolved else decision.reason),
                    relevant_sources=refs,
                )
            case.iteration_count += 1
            if decision.decision == "refine":
                case.loop_count += 1
            case.latest_validation_result = decision
        case.what_complete = what_complete
        case.why_complete = why_complete
        case.stage_visits += 1
        if case.final_result is None:
            case.current_stage = decision.next_stage
    except ValidationError:
        raise InvalidDecisionError("Stage output violates the diagnosis contract") from None
    except ToolRejectedError as exc:
        raise InvalidDecisionError(str(exc)) from None


def supporting_artifacts(case: DiagnosisRuntimeState) -> tuple[DiagnosticArtifact, ...]:
    """Return cited results and their provenance dependencies, not discarded candidates."""
    if isinstance(case.final_result, StructuredDiagnosis):
        references = [ref for claim in [*case.final_result.what, *case.final_result.why]
                      for ref in [*claim.supporting_sources, *claim.contradicting_sources]]
    else:
        assert isinstance(case.final_result, UnresolvedDiagnosis)
        references = list(case.final_result.relevant_sources)
    selected: dict[str, DiagnosticArtifact] = {}
    while references:
        reference = references.pop()
        for artifact in case.artifacts.values():
            if artifact.artifact_id in selected:
                continue
            expected_kind = (DiagnosticSourceKind.CAPABILITY_RESULT
                             if artifact.artifact_type == DiagnosticArtifactType.CAPABILITY_RESULT
                             else DiagnosticSourceKind.CONTEXT)
            direct = reference.source_id == artifact.artifact_id and reference.source_kind == expected_kind
            information_snapshot = (artifact.artifact_type == DiagnosticArtifactType.INFORMATION_RESULT
                                    and reference in artifact.source_references)
            if direct or information_snapshot:
                selected[artifact.artifact_id] = artifact
                references.extend(artifact.source_references)
    return tuple(a for key, a in case.artifacts.items() if key in selected)
