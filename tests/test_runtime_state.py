"""Current-state invariants retained from SCRUM-11 without persisted snapshots."""

from dataclasses import fields
from datetime import datetime, timezone

from ali_diagnosis.application.orchestration.contracts import ValidationDecision
from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.domain import (
    DiagnosisRunRequest, DiagnosticArtifact, DiagnosticFinding, DiagnosticSourceReference,
    RootCauseHypothesis, StructuredDiagnosis, SubjectReference,
    UnresolvedDiagnosis, NoLearningProblemDiagnosis,
)


def request(run_id="run"):
    return DiagnosisRunRequest(diagnosis_run_id=run_id, learner_id="learner", evidence_id="evidence")


def test_new_run_has_only_request_and_empty_working_context():
    run_request = request()
    state = DiagnosisRuntimeState(run_request)
    assert state.request is run_request
    assert state.subject_ref is None
    assert state.what_findings == state.why_hypotheses == []
    assert state.artifacts == {}
    assert state.synthesis_candidate is None
    assert state.latest_validation_result is None
    assert state.final_result is None
    assert state.current_stage == "what"
    assert not state.what_complete
    assert not state.why_complete
    assert state.iteration_count == state.loop_count == state.stage_visits == 0
    assert state.tool_failures == set()
    names = {f.name for f in fields(state)}
    assert not names & {"messages", "diagnostic_history", "reasoning", "snapshots",
                        "retrieved_information", "capability_results"}


def test_current_case_reuses_existing_domain_types_and_typed_stage_output():
    subject = SubjectReference(taxonomy_id="concept")
    source = DiagnosticSourceReference(source_kind="evidence", source_id="evidence")
    finding = DiagnosticFinding(finding_id="f", subject_ref=subject,
                                 problem_statement="Synthetic finding", confidence=0.5,
                                 supporting_sources=[source])
    hypothesis = RootCauseHypothesis(hypothesis_id="h", hypothesis_statement="Synthetic hypothesis",
                                      confidence=0.4, explains_finding_ids=["f"], supporting_sources=[source])
    candidate = StructuredDiagnosis(diagnosis_run_id="run", learner_id="learner", subject_ref=subject,
                                     what=[finding], why=[hypothesis])
    validation = ValidationDecision(decision="refine", next_stage="why", reason="Check alternatives.")
    state = DiagnosisRuntimeState(request(), subject_ref=subject, what_findings=[finding],
                                  why_hypotheses=[hypothesis], synthesis_candidate=candidate,
                                  latest_validation_result=validation)
    assert state.what_findings[0] is finding
    assert state.why_hypotheses[0] is hypothesis
    assert state.synthesis_candidate is candidate
    assert state.latest_validation_result is validation
    state.what_findings = [finding.model_copy(update={"confidence": 0.6})]
    state.why_hypotheses = []
    state.synthesis_candidate = None
    assert state.what_findings[0].confidence == 0.6
    assert state.why_hypotheses == []


def test_runs_do_not_share_artifacts_claims_or_failure_codes():
    first, second = DiagnosisRuntimeState(request()), DiagnosisRuntimeState(request("other"))
    artifact = DiagnosticArtifact(artifact_id="a", diagnosis_run_id="run",
                                   subject_ref=SubjectReference(taxonomy_id="concept"),
                                   artifact_type="information_result", producer="source", request={},
                                   result={"observation": 1}, created_at=datetime.now(timezone.utc))
    first.artifacts["a"] = artifact
    first.tool_failures.add("information:source")
    assert first.artifacts["a"] is artifact
    assert second.artifacts == {}
    assert second.tool_failures == set()
    assert first.what_findings is not second.what_findings
    assert first.why_hypotheses is not second.why_hypotheses


def test_existing_unresolved_and_no_learning_problem_contracts_remain_valid_state_values():
    state = DiagnosisRuntimeState(request())
    values = dict(diagnosis_run_id="run", learner_id="learner",
                  subject_ref=SubjectReference(taxonomy_id="concept"), reason="Synthetic conclusion",
                  relevant_sources=[DiagnosticSourceReference(source_kind="evidence", source_id="evidence")])
    unresolved = UnresolvedDiagnosis(**values, unresolved_scope="both")
    no_problem = NoLearningProblemDiagnosis(**values)
    state.final_result = unresolved
    assert state.final_result is unresolved
    state.final_result = no_problem
    assert state.final_result is no_problem
