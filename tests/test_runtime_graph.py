"""Verify deterministic orchestration, refinement, snapshots, and failures."""

from copy import deepcopy

import pytest
from langgraph.graph.state import CompiledStateGraph

from ali_diagnosis.application import CapabilityRegistry, InformationGateway
from ali_diagnosis.domain import (
    DiagnosisRunRequest,
    DiagnosticSourceKind,
    StructuredDiagnosis,
    UnresolvedDiagnosis,
    UnresolvedScope,
)
from ali_diagnosis.infrastructure.langgraph_runtime.graph import (
    MAX_REFINEMENT_LOOPS,
    build_diagnosis_graph,
)
from ali_diagnosis.infrastructure.langgraph_runtime.mock_dependencies import (
    MockDiagnosisCapability,
    MockInformationSource,
)
from ali_diagnosis.infrastructure.langgraph_runtime.state import DiagnosisRuntimeState


@pytest.fixture
def state() -> DiagnosisRuntimeState:
    return DiagnosisRuntimeState(
        request=DiagnosisRunRequest(
            diagnosis_run_id="run-1", learner_id="learner-1", evidence_id="evidence-1"
        )
    )


def test_builder_returns_compiled_graph() -> None:
    graph = build_diagnosis_graph()
    assert isinstance(graph, CompiledStateGraph)
    assert graph.checkpointer is None
    assert graph.store is None


@pytest.mark.parametrize("input_shape", ["dataclass", "dictionary", "request_only"])
def test_successful_run_accepts_state_shapes(
    state: DiagnosisRuntimeState, input_shape: str
) -> None:
    if input_shape == "dataclass":
        graph_input = state
    elif input_shape == "dictionary":
        graph_input = vars(state).copy()
    else:
        graph_input = {"request": state.request}

    result = build_diagnosis_graph().invoke(graph_input)

    assert result["request"] is state.request
    assert result["current_stage"] == "validation"
    assert result["iteration_count"] == 1
    assert result["loop_count"] == 0
    assert result["latest_validation_result"] == {"is_mock": True, "decision": "accept"}
    final = result["final_result"]
    assert isinstance(final, StructuredDiagnosis)
    assert final.diagnosis_run_id == state.request.diagnosis_run_id
    assert final.learner_id == state.request.learner_id
    assert final.subject_ref == result["subject_ref"]
    assert final.what == result["what_findings"]
    assert final.why == result["why_hypotheses"]
    assert final.why[0].explains_finding_ids == [final.what[0].finding_id]
    assert result["retrieved_information"]["mock"]["is_mock"] is True
    capability = result["capability_results"][0]
    assert capability["is_mock"] is True
    assert capability["producer"] == MockDiagnosisCapability.metadata.name
    source = final.why[0].supporting_sources[0]
    assert source.source_kind == DiagnosticSourceKind.CAPABILITY_RESULT
    assert source.source_id == capability["source_id"]
    assert len(result["diagnostic_history"]) == 1
    snapshot = result["diagnostic_history"][0]
    assert snapshot.what_findings == final.what
    assert snapshot.why_hypotheses == final.why
    assert snapshot.new_information == result["retrieved_information"]
    assert snapshot.new_capability_results == result["capability_results"]
    assert snapshot.synthesis_candidate == result["synthesis_candidate"]
    assert snapshot.validation_result == result["latest_validation_result"]
    assert state.current_stage is None
    assert state.diagnostic_history == []


@pytest.mark.parametrize("refinement", [None, "what", "why"])
def test_stage_order_and_one_snapshot_per_completed_iteration(
    state: DiagnosisRuntimeState, refinement: str | None
) -> None:
    decisions = ("accept",) if refinement is None else (refinement, "accept")
    graph = build_diagnosis_graph(validation_decisions=decisions)
    updates = list(graph.stream(state, stream_mode="updates"))
    stages = [next(iter(update)) for update in updates]
    expected = ["what", "why", "synthesis", "validation"]
    if refinement == "what":
        expected += ["what", "why", "synthesis", "validation"]
    elif refinement == "why":
        expected += ["why", "synthesis", "validation"]
    assert stages == expected
    completed = 0
    for update in updates:
        stage, values = next(iter(update.items()))
        assert values["current_stage"] == stage
        if stage == "validation":
            completed += 1
            assert values["iteration_count"] == completed
            assert len(values["diagnostic_history"]) == completed
        else:
            assert "diagnostic_history" not in values
            assert "iteration_count" not in values
    final_update = updates[-1]["validation"]
    assert isinstance(final_update["final_result"], StructuredDiagnosis)
    assert final_update["loop_count"] == (0 if refinement is None else 1)


def test_information_and_capability_use_existing_boundaries(state: DiagnosisRuntimeState) -> None:
    requests = []
    invocations = []

    class RecordingSource(MockInformationSource):
        def get_information(self, request):
            requests.append(request)
            result = super().get_information(request)
            result["source_id"] += f":{len(requests)}"
            return result

    class RecordingCapability(MockDiagnosisCapability):
        def analyze(self, request, findings, *, iteration):
            invocations.append((request, findings, iteration))
            return super().analyze(request, findings, iteration=iteration)

    registry = CapabilityRegistry()
    capability = RecordingCapability()
    registry.register(capability)
    graph = build_diagnosis_graph(
        information_gateway=InformationGateway({"mock": RecordingSource()}),
        capability_registry=registry,
        validation_decisions=("what", "why", "accept"),
    )
    result = graph.invoke(state)

    assert requests == [state.request, state.request]
    assert [entry[2] for entry in invocations] == [1, 2, 3]
    assert all(entry[0] is state.request for entry in invocations)
    assert all(entry[1][0].finding_id == "mock-finding" for entry in invocations)
    assert registry.resolve(capability.metadata.name) is capability
    assert len(result["capability_results"]) == 3
    history = result["diagnostic_history"]
    assert [snapshot.iteration_count for snapshot in history] == [1, 2, 3]
    assert [snapshot.loop_count for snapshot in history] == [1, 2, 2]
    assert history[0].new_information["mock"]["source_id"].endswith(":1")
    assert history[1].new_information["mock"]["source_id"].endswith(":2")
    assert history[2].new_information == {}  # WHY-only refinement retrieves nothing.
    assert [len(snapshot.new_capability_results) for snapshot in history] == [1, 1, 1]
    assert [snapshot.new_capability_results[0]["source_id"] for snapshot in history] == [
        result["source_id"] for result in result["capability_results"]
    ]


def test_snapshot_deltas_and_detachment_across_later_mutations(state: DiagnosisRuntimeState) -> None:
    graph = build_diagnosis_graph(validation_decisions=("what", "accept"))
    result = graph.invoke(state)
    history = result["diagnostic_history"]
    assert len(history) == 2
    assert history[1].new_information == {}  # Identical context is already recorded.
    assert len(history[1].new_capability_results) == 1
    before = deepcopy(history)

    result["what_findings"][0].supporting_sources.clear()
    result["why_hypotheses"][0].explains_finding_ids.clear()
    result["retrieved_information"]["mock"]["subject_ref"]["taxonomy_id"] = "changed"
    result["capability_results"][0]["finding_ids"].clear()
    result["synthesis_candidate"]["what"].clear()
    result["latest_validation_result"]["decision"] = "changed"

    assert history == before


@pytest.mark.parametrize("refinement", ["what", "why"])
@pytest.mark.parametrize("limit", [0, MAX_REFINEMENT_LOOPS, 8])
def test_loop_limit_produces_unresolved_outcome(
    state: DiagnosisRuntimeState, refinement: str, limit: int
) -> None:
    graph = build_diagnosis_graph(
        validation_decisions=(refinement,), max_refinement_loops=limit
    )
    result = graph.invoke(state)

    assert result["loop_count"] == limit
    assert result["iteration_count"] == limit + 1
    assert len(result["diagnostic_history"]) == limit + 1
    assert result["latest_validation_result"] == {"is_mock": True, "decision": "exhausted"}
    final = result["final_result"]
    assert isinstance(final, UnresolvedDiagnosis)
    assert final.unresolved_scope == UnresolvedScope(refinement)
    assert final.diagnosis_run_id == state.request.diagnosis_run_id
    assert final.learner_id == state.request.learner_id
    assert final.subject_ref == result["subject_ref"]
    assert final.relevant_sources
    assert "refinement-loop limit" in final.reason
    assert result["diagnostic_history"][-1].validation_result["decision"] == "exhausted"


def test_acceptance_on_last_permitted_iteration(state: DiagnosisRuntimeState) -> None:
    graph = build_diagnosis_graph(
        validation_decisions=("what", "why", "accept"), max_refinement_loops=2
    )
    result = graph.invoke(state)
    assert result["loop_count"] == 2
    assert result["iteration_count"] == 3
    assert isinstance(result["final_result"], StructuredDiagnosis)


@pytest.mark.parametrize("dependency", ["information", "capability"])
def test_dependency_failure_propagates_without_unresolved_fallback(
    state: DiagnosisRuntimeState, dependency: str
) -> None:
    failure = RuntimeError(f"Mock {dependency} failed")

    class FailingSource(MockInformationSource):
        def get_information(self, request):
            raise failure

    class FailingCapability(MockDiagnosisCapability):
        def analyze(self, request, findings, *, iteration):
            raise failure

    if dependency == "information":
        graph = build_diagnosis_graph(
            information_gateway=InformationGateway({"mock": FailingSource()})
        )
    else:
        registry = CapabilityRegistry()
        registry.register(FailingCapability())
        graph = build_diagnosis_graph(capability_registry=registry)
    updates = []
    with pytest.raises(RuntimeError) as caught:
        for update in graph.stream(state, stream_mode="updates"):
            updates.append(update)
    assert caught.value is failure
    assert all("validation" not in update for update in updates)
    assert state.final_result is None
    assert state.diagnostic_history == []


def test_compiled_graph_reuses_no_state_between_runs(state: DiagnosisRuntimeState) -> None:
    graph = build_diagnosis_graph(validation_decisions=("why", "accept"))
    first = graph.invoke(state)
    second_state = DiagnosisRuntimeState(
        request=DiagnosisRunRequest(
            diagnosis_run_id="run-2", learner_id="learner-2", evidence_id="evidence-2"
        )
    )
    second = graph.invoke(second_state)
    assert first["iteration_count"] == second["iteration_count"] == 2
    assert first["loop_count"] == second["loop_count"] == 1
    assert second["final_result"].diagnosis_run_id == "run-2"
    assert len(second["diagnostic_history"]) == 2
    assert second["diagnostic_history"] is not first["diagnostic_history"]
    assert second["capability_results"][0]["source_id"].startswith("run-2:")


@pytest.mark.parametrize("decisions", [(), ("invalid",)])
def test_invalid_mock_decisions_fail_at_build_time(decisions: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="validation_decisions"):
        build_diagnosis_graph(validation_decisions=decisions)


def test_negative_loop_limit_fails_at_build_time() -> None:
    with pytest.raises(ValueError, match="max_refinement_loops"):
        build_diagnosis_graph(max_refinement_loops=-1)
