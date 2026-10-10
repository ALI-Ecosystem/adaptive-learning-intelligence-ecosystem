"""Verify per-run state isolation and the evolving current case representation."""

from ali_diagnosis.domain import (
    DiagnosisRunRequest,
    DiagnosticFinding,
    DiagnosticSourceKind,
    DiagnosticSourceReference,
    NoLearningProblemDiagnosis,
    RootCauseHypothesis,
    SubjectReference,
    StructuredDiagnosis,
    UnresolvedDiagnosis,
    UnresolvedScope,
)
from ali_diagnosis.infrastructure.langgraph_runtime.state import (
    DiagnosisRuntimeState,
    DiagnosticSnapshot,
)


def request(run_id: str = "run-1") -> DiagnosisRunRequest:
    return DiagnosisRunRequest(
        diagnosis_run_id=run_id,
        learner_id="learner-1",
        evidence_id="evidence-1",
    )


def test_new_run_has_only_request_and_empty_working_context() -> None:
    run_request = request()
    state = DiagnosisRuntimeState(request=run_request)

    assert state.request is run_request
    assert state.subject_ref is None
    assert state.what_findings == []
    assert state.why_hypotheses == []
    assert state.retrieved_information == {}
    assert state.capability_results == []
    assert state.synthesis_candidate is None
    assert state.latest_validation_result is None
    assert state.final_result is None
    assert state.diagnostic_history == []
    assert state.current_stage is None
    assert state.iteration_count == 0
    assert state.loop_count == 0


def test_current_case_reuses_domain_types_and_can_be_replaced_or_cleared() -> None:
    subject = SubjectReference(taxonomy_id="concept-1")
    supporting = DiagnosticSourceReference(
        source_kind=DiagnosticSourceKind.EVIDENCE, source_id="evidence-1"
    )
    contradicting = DiagnosticSourceReference(
        source_kind=DiagnosticSourceKind.CONTEXT, source_id="context-1"
    )
    finding = DiagnosticFinding(
        finding_id="finding-1",
        subject_ref=subject,
        problem_statement="Synthetic test finding.",
        confidence=0.5,
        supporting_sources=[supporting],
        contradicting_sources=[contradicting],
    )
    hypothesis = RootCauseHypothesis(
        hypothesis_id="hypothesis-1",
        hypothesis_statement="Synthetic test hypothesis.",
        confidence=0.4,
        explains_finding_ids=[finding.finding_id],
        supporting_sources=[supporting],
        contradicting_sources=[contradicting],
    )
    state = DiagnosisRuntimeState(
        request=request(),
        subject_ref=subject,
        what_findings=[finding],
        why_hypotheses=[hypothesis],
        synthesis_candidate={"what": [finding], "why": [hypothesis]},
        latest_validation_result={"test_result": "needs_review"},
        current_stage="validation",
        iteration_count=1,
    )

    assert state.subject_ref is subject
    assert state.what_findings[0] is finding
    assert state.why_hypotheses[0] is hypothesis
    assert state.what_findings[0].supporting_sources == [supporting]
    assert state.why_hypotheses[0].contradicting_sources == [contradicting]

    state.retrieved_information = {"test_source": {"observations": [1]}}
    state.capability_results = [{"measurement": [0.5]}]
    snapshot = DiagnosticSnapshot(
        current_stage=state.current_stage,
        iteration_count=state.iteration_count,
        loop_count=state.loop_count,
        what_findings=state.what_findings,
        why_hypotheses=state.why_hypotheses,
        new_information=state.retrieved_information,
        new_capability_results=state.capability_results,
        synthesis_candidate=state.synthesis_candidate,
        validation_result=state.latest_validation_result,
    )
    state.diagnostic_history.append(snapshot)
    completed = StructuredDiagnosis(
        diagnosis_run_id=state.request.diagnosis_run_id,
        learner_id=state.request.learner_id,
        subject_ref=subject,
        what=[finding],
        why=[hypothesis],
    )
    state.final_result = completed
    assert state.final_result is completed

    # Mutating nested live values must not rewrite an earlier snapshot.
    finding.supporting_sources.append(contradicting)
    hypothesis.explains_finding_ids.append("finding-2")
    state.retrieved_information["test_source"]["observations"].append(2)
    state.capability_results[0]["measurement"].append(0.6)
    state.synthesis_candidate["what"].clear()
    state.latest_validation_result["test_result"] = "changed"

    refined_finding = finding.model_copy(update={"confidence": 0.6})
    state.what_findings = [refined_finding]
    state.why_hypotheses = []
    state.synthesis_candidate = None
    state.latest_validation_result = {"test_result": "revisit"}
    state.current_stage = "what"
    state.iteration_count += 1
    assert state.loop_count == 0
    state.loop_count += 1

    assert state.what_findings == [refined_finding]
    assert state.why_hypotheses == []
    assert state.synthesis_candidate is None
    assert state.latest_validation_result == {"test_result": "revisit"}
    assert state.current_stage == "what"
    assert state.iteration_count == 2
    assert state.loop_count == 1
    assert state.diagnostic_history == [snapshot]
    assert snapshot.current_stage == "validation"
    assert snapshot.iteration_count == 1
    assert snapshot.loop_count == 0
    assert snapshot.what_findings[0].confidence == 0.5
    assert snapshot.what_findings[0].supporting_sources == [supporting]
    assert snapshot.why_hypotheses[0].explains_finding_ids == ["finding-1"]
    assert snapshot.new_information == {"test_source": {"observations": [1]}}
    assert snapshot.new_capability_results == [{"measurement": [0.5]}]
    assert snapshot.synthesis_candidate["what"][0].confidence == 0.5
    assert snapshot.synthesis_candidate["what"][0].supporting_sources == [supporting]
    assert snapshot.synthesis_candidate["why"][0].explains_finding_ids == ["finding-1"]
    assert snapshot.validation_result == {"test_result": "needs_review"}


def test_runs_do_not_share_mutable_collections_and_keep_undefined_results() -> None:
    first = DiagnosisRuntimeState(request=request("run-1"))
    second = DiagnosisRuntimeState(request=request("run-2"))
    information = {"test_observations": [1, 2]}
    capability_result = {"test_measurement": 0.5}

    first.retrieved_information["test_source"] = information
    first.capability_results.append(capability_result)

    assert first.retrieved_information["test_source"] is information
    assert first.capability_results[0] is capability_result
    assert second.retrieved_information == {}
    assert second.capability_results == []
    assert first.what_findings is not second.what_findings
    assert first.why_hypotheses is not second.why_hypotheses
    first.diagnostic_history.append(DiagnosticSnapshot("what", 1, 0))
    assert second.diagnostic_history == []


def test_final_result_reuses_unresolved_and_no_learning_problem_contracts() -> None:
    state = DiagnosisRuntimeState(request=request())
    subject = SubjectReference(taxonomy_id="concept-1")
    source = DiagnosticSourceReference(
        source_kind=DiagnosticSourceKind.EVIDENCE, source_id="evidence-1"
    )
    unresolved = UnresolvedDiagnosis(
        diagnosis_run_id=state.request.diagnosis_run_id,
        learner_id=state.request.learner_id,
        subject_ref=subject,
        unresolved_scope=UnresolvedScope.BOTH,
        reason="Synthetic insufficient evidence.",
        relevant_sources=[source],
    )
    no_problem = NoLearningProblemDiagnosis(
        diagnosis_run_id=state.request.diagnosis_run_id,
        learner_id=state.request.learner_id,
        subject_ref=subject,
        reason="Synthetic no-problem result.",
        relevant_sources=[source],
    )

    state.final_result = unresolved
    assert state.final_result is unresolved
    state.final_result = no_problem
    assert state.final_result is no_problem


def test_snapshots_have_independent_empty_payloads() -> None:
    first = DiagnosticSnapshot("what", 1, 0)
    second = DiagnosticSnapshot("why", 2, 1)

    first.new_information["test_source"] = {"observations": [1]}
    first.new_capability_results.append({"measurement": 0.5})

    assert second.new_information == {}
    assert second.new_capability_results == []
    assert first.what_findings is not second.what_findings
    assert first.why_hypotheses is not second.why_hypotheses
    assert first.synthesis_candidate is None
    assert second.synthesis_candidate is None
    assert second.validation_result is None
