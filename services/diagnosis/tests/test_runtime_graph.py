"""SCRUM-11 invariants migrated to the single production agentic graph."""

import asyncio
from copy import deepcopy

import pytest
from langgraph.graph.state import CompiledStateGraph

from orchestration_fakes import ScriptedAgent
from ali_diagnosis.application.orchestration.budget import RunBudget, RunLimits
from ali_diagnosis.application.orchestration.contracts import ValidationDecision
from ali_diagnosis.application.orchestration.errors import (
    DiagnosisExecutionError, InvalidDecisionError, ResourceLimitError,
)
from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.tools import DiagnosisTools
from ali_diagnosis.domain import DiagnosisRunRequest, StructuredDiagnosis
from ali_diagnosis.infrastructure.langgraph_runtime.graph import build_diagnosis_graph
from ali_diagnosis.infrastructure.synthetic_scenarios import synthetic_runtime


@pytest.fixture
def state():
    return DiagnosisRuntimeState(DiagnosisRunRequest(
        diagnosis_run_id="run", learner_id="learner", evidence_id="evidence"))


def graph_for(agent, *, max_visits=16, scenario="success"):
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2,
                       max_stage_visits=max_visits)
    runtime = synthetic_runtime(agent, limits, scenario)
    budget = RunBudget(limits)

    def make_tools(state):
        return DiagnosisTools(state, budget, runtime.gateway, runtime.information,
                              runtime.anchor_source, runtime.registry, runtime.capabilities)

    return build_diagnosis_graph(agent=agent, make_tools=make_tools, budget=budget)


def test_builder_has_four_real_goals_and_no_persistence():
    graph = graph_for(ScriptedAgent())
    assert isinstance(graph, CompiledStateGraph)
    assert graph.checkpointer is None
    assert graph.store is None
    assert {"what", "why", "synthesis", "validation"} <= set(graph.nodes)


@pytest.mark.parametrize("input_shape", ["dataclass", "dictionary", "request_only"])
def test_successful_run_accepts_original_input_shapes_without_mutating_input(state, input_shape):
    graph_input = (state if input_shape == "dataclass" else
                   vars(state).copy() if input_shape == "dictionary" else {"request": state.request})
    before = deepcopy(graph_input)
    result = asyncio.run(graph_for(ScriptedAgent()).ainvoke(graph_input))
    assert graph_input == before
    final = result["final_result"]
    assert isinstance(final, StructuredDiagnosis)
    assert final.diagnosis_run_id == state.request.diagnosis_run_id
    assert final.subject_ref == result["subject_ref"]
    assert final.what == result["what_findings"]
    assert final.why == result["why_hypotheses"]
    assert result["iteration_count"] == 1
    assert result["loop_count"] == 0
    assert "diagnostic_history" not in result
    assert "case" not in result


@pytest.mark.parametrize("refinement", [None, "what", "why", "synthesis"])
def test_validation_can_revisit_goals_and_counts_completed_assessments(state, refinement):
    class RefiningAgent(ScriptedAgent):
        async def run_stage(self, case, tools, budget):
            if case.current_stage == "validation" and case.iteration_count == 0 and refinement:
                self.visits.append(case.current_stage)
                return ValidationDecision(decision="refine", next_stage=refinement,
                                          reason="Review the synthetic candidate.")
            return await super().run_stage(case, tools, budget)

    agent = RefiningAgent()
    result = asyncio.run(graph_for(agent).ainvoke(state))
    expected = ["what", "why", "synthesis", "validation"]
    if refinement:
        expected += expected[expected.index(refinement):]
    assert agent.visits == expected
    assert result["stage_visits"] == len(expected)
    assert result["iteration_count"] == (2 if refinement else 1)
    assert result["loop_count"] == (1 if refinement else 0)
    assert isinstance(result["final_result"], StructuredDiagnosis)


def test_stream_updates_keep_earlier_public_values_detached(state):
    async def run():
        saved = []
        async for update in graph_for(ScriptedAgent(refine=True)).astream(state, stream_mode="updates"):
            # Earlier graph updates must not be mutated by later goals or their tools.
            assert all(value == original for value, original in saved)
            saved.append((update, deepcopy(update)))
        result = saved[-1][0]["validation"]
        result["what_findings"][0].supporting_sources.clear()
        assert saved[0][0] == saved[0][1]
        assert state.what_findings == []
        assert [next(iter(item[0])) for item in saved] == [
            "what", "why", "what", "why", "synthesis", "validation"]
    asyncio.run(run())


@pytest.mark.parametrize("stage", ["what", "why", "synthesis", "validation"])
def test_every_goal_can_loop_but_is_bounded(state, stage):
    class LoopingAgent(ScriptedAgent):
        async def run_stage(self, case, tools, budget):
            decision = await super().run_stage(case, tools, budget)
            if case.finalization_reason:
                return decision
            if case.current_stage != stage:
                return decision
            if stage == "validation":
                return ValidationDecision(decision="refine", next_stage=stage, reason="Still unresolved.")
            return decision.model_copy(update={"next_stage": stage})

    agent = LoopingAgent()
    result = asyncio.run(graph_for(agent, max_visits=6).ainvoke(state))
    assert result["stage_visits"] <= 6
    assert agent.visits.count(stage) >= 2
    assert result["final_result"] is not None
    assert agent.visits[-1] == "validation"
    assert state.stage_visits == 0
    assert state.final_result is None


def test_acceptance_at_last_permitted_visit(state):
    result = asyncio.run(graph_for(ScriptedAgent(), max_visits=4).ainvoke(state))
    assert isinstance(result["final_result"], StructuredDiagnosis)
    assert result["stage_visits"] == 4


def test_failed_tools_remain_visible_after_stage_transition(state):
    with pytest.raises(DiagnosisExecutionError, match="Unrecovered tool failures"):
        asyncio.run(graph_for(ScriptedAgent(unresolved=True), scenario="tool_failure").ainvoke(state))
    assert state.tool_failures == set()
    assert state.artifacts == {}


def test_wrong_output_type_does_not_publish_partial_tool_state(state):
    class WrongAgent:
        async def run_stage(self, case, tools, budget):
            await tools.call("get_information", {"source": "trigger"})
            return ValidationDecision(decision="unresolved", reason="Wrong stage type.")

    with pytest.raises(InvalidDecisionError, match="Wrong stage"):
        asyncio.run(graph_for(WrongAgent()).ainvoke(state))
    assert state.artifacts == {}
    assert state.subject_ref is None


def test_runtime_reuses_configuration_without_sharing_concurrent_run_state(state):
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2)
    runtime = synthetic_runtime(ScriptedAgent(), limits, "success")
    other = state.request.model_copy(update={"diagnosis_run_id": "other", "learner_id": "other-learner"})

    async def run():
        return await asyncio.gather(runtime.run(state.request), runtime.run(other))

    first, second = asyncio.run(run())
    assert first.outcome.learner_id == "learner"
    assert second.outcome.learner_id == "other-learner"
    assert first.tool_calls == second.tool_calls == 1
    assert first.stage_visits == second.stage_visits == 4
    assert all(a.diagnosis_run_id == "other" for a in second.artifacts)
    assert all(a.diagnosis_run_id == "run" for a in first.artifacts)


def test_new_stage_tools_still_share_the_run_budget(state):
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2, max_tool_calls=1)
    runtime = synthetic_runtime(ScriptedAgent(capability=True), limits, "success")
    # WHAT spends the one allowed retrieval; WHY's discovery must not get a new budget.
    report = asyncio.run(runtime.run(state.request))
    assert report.outcome.status == "unresolved"
    assert "Tool call limit" in report.resource_limit_reason
    assert report.tool_calls == 1
