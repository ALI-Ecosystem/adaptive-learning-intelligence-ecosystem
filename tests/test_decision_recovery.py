"""Bounded recovery and resource finalization through the production graph."""

import asyncio
import json

import pytest

from orchestration_fakes import ScriptedAgent
from ali_diagnosis.application.orchestration.budget import RunBudget, RunLimits
from ali_diagnosis.application.orchestration.contracts import WhatDecision, ValidationDecision
from ali_diagnosis.application.orchestration.errors import DiagnosisExecutionError, InvalidDecisionError, ResourceLimitError
from ali_diagnosis.application.orchestration.policy import apply_decision
from ali_diagnosis.application.orchestration.prompts import stage_context
from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.tools import DiagnosisTools
from ali_diagnosis.domain import DiagnosisRunRequest
from ali_diagnosis.infrastructure.langgraph_runtime.graph import build_diagnosis_graph
from ali_diagnosis.infrastructure.langgraph_runtime.nodes import execute_stage
from ali_diagnosis.infrastructure.synthetic_scenarios import synthetic_runtime


@pytest.fixture
def run_request():
    return DiagnosisRunRequest(diagnosis_run_id="run", learner_id="learner", evidence_id="evidence")


def limits(**overrides):
    return RunLimits(input_usd_per_million=1, output_usd_per_million=2, **overrides)


def setup(agent, run_limits, run_request):
    runtime = synthetic_runtime(agent, run_limits, "success")
    budget = RunBudget(run_limits)

    def make_tools(case):
        return DiagnosisTools(case, budget, runtime.gateway, runtime.information,
                              runtime.anchor_source, runtime.registry, runtime.capabilities)

    graph = build_diagnosis_graph(agent=agent, make_tools=make_tools, budget=budget)
    return graph, budget, make_tools, DiagnosisRuntimeState(run_request)


class CountedAgent(ScriptedAgent):
    """One synthetic provider attempt per decision, charged at the full envelope."""

    async def run_stage(self, case, tools, budget):
        budget.reserve_model(budget.limits.max_input_tokens)
        return await super().run_stage(case, tools, budget)


def test_invalid_what_is_corrected_without_retrieval_or_partial_claims(run_request):
    class CorrectingAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            if case.decision_feedback:
                assert case.current_stage == "what"
                assert "requires WHY" in case.decision_feedback
                assert not case.what_findings and not case.what_complete
                assert not case.why_hypotheses and case.synthesis_candidate is None
                assert "run:trigger" in case.artifacts
            decision = await super().run_stage(case, tools, budget)
            if len(self.visits) == 1:
                return decision.model_copy(update={"next_stage": "synthesis"})
            return decision

    agent = CorrectingAgent()
    graph, budget, _, state = setup(agent, limits(), run_request)
    result = asyncio.run(graph.ainvoke(state))
    assert agent.visits == ["what", "what", "why", "synthesis", "validation"]
    assert result["final_result"].status == "completed"
    assert result["stage_visits"] == 4
    assert result["decision_feedback"] is None
    assert budget.model_calls == 5
    assert budget.tool_calls == 1
    assert budget.reserved_cost_usd == pytest.approx(5 * budget.model_cost(budget.limits.max_input_tokens))
    assert state == DiagnosisRuntimeState(run_request)


def test_revised_what_cannot_reuse_old_why_even_during_correction(run_request):
    class RevisingAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            if case.current_stage == "validation" and not case.iteration_count:
                budget.reserve_model(budget.limits.max_input_tokens)
                self.visits.append("validation")
                return ValidationDecision(decision="refine", next_stage="what", reason="Review findings.")
            decision = await super().run_stage(case, tools, budget)
            if case.current_stage == "what" and case.iteration_count:
                decision.findings[0] = decision.findings[0].model_copy(update={"problem_statement": "Updated problem"})
                if not case.decision_feedback:
                    return decision.model_copy(update={"next_stage": "synthesis"})
                assert case.what_findings[0].problem_statement != "Updated problem"
                assert case.why_hypotheses  # Retained until revised WHAT is validly applied.
            if case.current_stage == "why" and case.iteration_count:
                assert not case.why_hypotheses and not case.why_complete
                assert case.synthesis_candidate is None
            return decision

    agent = RevisingAgent()
    report = asyncio.run(synthetic_runtime(agent, limits(), "success").run(run_request))
    assert agent.visits == ["what", "why", "synthesis", "validation", "what", "what", "why", "synthesis", "validation"]
    assert report.outcome.what[0].problem_statement == "Updated problem"
    assert report.model_calls == 9


def test_repeated_invalid_decisions_have_a_fixed_bound(run_request):
    class InvalidAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            decision = await super().run_stage(case, tools, budget)
            assert not case.what_complete
            return decision.model_copy(update={"next_stage": "synthesis"})

    agent = InvalidAgent()
    graph, budget, _, state = setup(agent, limits(), run_request)
    with pytest.raises(InvalidDecisionError, match="correction limit exceeded"):
        asyncio.run(graph.ainvoke(state))
    assert agent.visits == ["what"] * 3
    assert budget.model_calls == 3
    assert budget.tool_calls == 1
    assert state == DiagnosisRuntimeState(run_request)


def test_executor_discards_partial_policy_mutation_but_preserves_tools(run_request, monkeypatch):
    import ali_diagnosis.infrastructure.langgraph_runtime.nodes as nodes
    original = nodes.apply_decision
    attempts = 0

    def late_rejection(case, decision):
        nonlocal attempts
        original(case, decision)
        attempts += 1
        if attempts == 1:
            raise InvalidDecisionError("Synthetic late policy failure")

    monkeypatch.setattr(nodes, "apply_decision", late_rejection)

    class CheckingAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            if case.decision_feedback:
                assert case.current_stage == "what" and case.stage_visits == 0
                assert case.artifacts and not case.what_findings
                assert not case.what_complete and not case.why_complete
            return await super().run_stage(case, tools, budget)

    report = asyncio.run(synthetic_runtime(CheckingAgent(), limits(), "success").run(run_request))
    assert report.outcome.status == "completed"
    assert report.model_calls == 5 and report.tool_calls == 1


def test_tight_budget_can_still_complete_all_required_stages(run_request):
    config = limits(max_model_calls=4, max_stage_visits=4, max_tool_calls=1)
    config = config.model_copy(update={"max_cost_usd": 4 * RunBudget(config).model_cost(config.max_input_tokens)})
    agent = CountedAgent()
    report = asyncio.run(synthetic_runtime(agent, config, "success").run(run_request))
    assert report.outcome.status == "completed"
    assert report.stage_visits == report.model_calls == 4
    assert report.reserved_cost_usd == pytest.approx(config.max_cost_usd)
    assert agent.visits == ["what", "why", "synthesis", "validation"]
    assert report.resource_limit_reason is None


@pytest.mark.parametrize("constraint", ["calls", "stages", "cost"])
def test_insufficient_progression_budget_returns_resource_labeled_outcome(run_request, constraint):
    config = limits()
    if constraint == "calls":
        config = config.model_copy(update={"max_model_calls": 3})
    elif constraint == "stages":
        config = config.model_copy(update={"max_stage_visits": 3})
    else:
        config = config.model_copy(update={"max_cost_usd": 3 * RunBudget(config).model_cost(config.max_input_tokens)})
    agent = CountedAgent()
    report = asyncio.run(synthetic_runtime(agent, config, "success").run(run_request))
    assert agent.visits == ["what", "validation"]
    assert report.outcome.status == "unresolved"
    assert "Investigation interrupted by resource limits" in report.outcome.reason
    assert "not evidence of a learner deficit" in report.outcome.reason
    assert report.resource_limit_reason
    assert len(report.partial_findings) == 1
    assert not report.partial_hypotheses
    assert report.partial_findings[0].supporting_sources[0] in report.outcome.relevant_sources
    assert report.artifacts


def test_resource_finalization_does_not_relax_acceptance(run_request):
    class UnsafeAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            decision = await super().run_stage(case, tools, budget)
            if case.finalization_reason:
                return ValidationDecision(decision="accept", reason="No candidate")
            return decision

    with pytest.raises(InvalidDecisionError, match="current synthesis"):
        asyncio.run(synthetic_runtime(UnsafeAgent(), limits(max_stage_visits=3), "success").run(run_request))


def test_no_evidence_cannot_be_recast_as_resource_unresolved(run_request):
    class EmptyAgent:
        async def run_stage(self, case, tools, budget):
            budget.reserve_model(100)
            return WhatDecision(findings=[], next_stage="what")

    graph, budget, _, state = setup(EmptyAgent(), limits(max_model_calls=2), run_request)
    with pytest.raises(ResourceLimitError, match="Model call limit"):
        asyncio.run(graph.ainvoke(state))
    assert budget.model_calls == 2 and budget.tool_calls == 0
    assert state.final_result is None


@pytest.mark.parametrize("constraint", ["calls", "time", "cost"])
def test_no_assessment_budget_retains_a_resource_error(run_request, monkeypatch, constraint):
    clock = [0.0]
    monkeypatch.setattr("ali_diagnosis.application.orchestration.budget.monotonic", lambda: clock[0])

    async def run():
        agent = CountedAgent()
        _, budget, make_tools, state = setup(agent, limits(), run_request)
        budget.started = 0
        tools = make_tools(state)
        await tools.call("get_information", {"source": "trigger"})
        if constraint == "calls":
            budget.model_calls = budget.limits.max_model_calls
        elif constraint == "time":
            clock[0] = budget.limits.max_seconds + 1
        else:
            budget.reserved_cost_usd = budget.limits.max_cost_usd
        with pytest.raises(ResourceLimitError):
            await execute_stage(state, stage="what", agent=agent, make_tools=make_tools, budget=budget)
        assert not agent.visits and state.final_result is None
    asyncio.run(run())


def test_time_pressure_is_explicit_and_final_assessment_keeps_partial_claims(run_request, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("ali_diagnosis.application.orchestration.budget.monotonic", lambda: clock[0])

    class SlowProgressAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            budget.started = 0
            decision = await super().run_stage(case, tools, budget)
            if case.current_stage == "what":
                clock[0] = 175.0
            else:
                assert case.current_stage == "validation"
                assert "execution time" in case.finalization_reason
            return decision

    report = asyncio.run(synthetic_runtime(SlowProgressAgent(), limits(), "success").run(run_request))
    assert report.outcome.status == "unresolved" and report.model_calls == 2
    assert report.partial_findings


def test_context_exposes_all_resources_and_correction_feedback(run_request):
    _, budget, make_tools, state = setup(CountedAgent(), limits(), run_request)
    budget.reserve_model(123)
    budget.reserve_tool()
    state.decision_feedback = "Synthesis requires WHY"
    context = json.loads(stage_context(state, make_tools(state)))
    assert context["remaining_model_calls"] == 31
    assert context["remaining_tool_calls"] == 23
    assert context["remaining_stage_visits"] == 16
    assert 0 < context["remaining_execution_seconds"] <= 180
    assert context["remaining_estimated_cost_usd"] == pytest.approx(1 - budget.model_cost(123))
    assert context["decision_feedback"] == state.decision_feedback


def test_resource_unresolved_before_what_does_not_mark_what_complete(run_request):
    async def run():
        _, _, make_tools, state = setup(CountedAgent(), limits(), run_request)
        await make_tools(state).call("get_information", {"source": "trigger"})
        state.current_stage = "validation"
        state.finalization_reason = "model budget"
        with pytest.raises(InvalidDecisionError):
            apply_decision(state, ValidationDecision(decision="accept", reason="Cannot bypass WHAT"))
        apply_decision(state, ValidationDecision(decision="unresolved", reason="Investigation incomplete"))
        assert state.final_result.status == "unresolved"
        assert not state.what_complete and not state.why_complete
    asyncio.run(run())


def test_resource_finalization_does_not_hide_tool_failure(run_request):
    with pytest.raises(DiagnosisExecutionError, match="Unrecovered tool failures"):
        asyncio.run(synthetic_runtime(CountedAgent(unresolved=True), limits(max_stage_visits=2), "tool_failure").run(run_request))


def test_reserved_time_interrupts_investigation_then_allows_validation(run_request, monkeypatch):
    class SlowAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            if case.current_stage == "what":
                budget.reserve_model(100)
                self.visits.append("what")
                await asyncio.sleep(10)
            return await super().run_stage(case, tools, budget)

    async def run():
        agent = SlowAgent()
        graph, budget, make_tools, state = setup(agent, limits(), run_request)
        await make_tools(state).call("get_information", {"source": "trigger"})
        original = budget.call_seconds
        # Exercise actual asyncio cancellation deterministically, without waiting
        # for the production time window or changing the shared absolute deadline.
        monkeypatch.setattr(budget, "call_seconds", lambda case: original(case) if case.finalization_reason else 0.001)
        result = await graph.ainvoke(state)
        assert result["final_result"].status == "unresolved"
        assert "time reserved" in result["finalization_reason"]
        assert agent.visits == ["what", "validation"]
        assert budget.model_calls == 2 and budget.tool_calls == 1
    asyncio.run(run())


def test_early_finalization_blocks_new_tools_but_retains_existing_sources(run_request):
    async def run():
        _, budget, make_tools, state = setup(CountedAgent(), limits(), run_request)
        tools = make_tools(state)
        await tools.call("get_information", {"source": "trigger"})
        state.finalization_reason = "time budget"
        response = await tools.call("get_information", {"source": "history"})
        assert response["error"] == "final_assessment_only"
        assert budget.tool_calls == 2
        assert list(state.artifacts) == ["run:trigger"]
    asyncio.run(run())


def test_tool_after_initial_retrieval_cannot_consume_reserved_assessment_time(run_request, monkeypatch):
    original = DiagnosisTools._information

    async def slow_history(tools, arguments):
        if arguments["source"] == "history":
            await asyncio.sleep(10)
        return await original(tools, arguments)

    monkeypatch.setattr(DiagnosisTools, "_information", slow_history)

    class ToolTimeoutAgent(CountedAgent):
        async def run_stage(self, case, tools, budget):
            if case.current_stage == "what":
                self.visits.append("what")
                budget.reserve_model(100)
                await tools.call("get_information", {"source": "trigger"})
                original_seconds = budget.call_seconds
                monkeypatch.setattr(budget, "call_seconds",
                                    lambda case: original_seconds(case) if case.finalization_reason else 0.001)
                await tools.call("get_information", {"source": "history"})
                pytest.fail("The tool should have yielded the reserved time")
            assert not case.tool_failures  # Cancellation is not a fabricated source outage.
            return await super().run_stage(case, tools, budget)

    report = asyncio.run(synthetic_runtime(ToolTimeoutAgent(), limits(), "success").run(run_request))
    assert report.outcome.status == "unresolved"
    assert "tool execution time" in report.resource_limit_reason
    assert report.tool_calls == 2 and report.model_calls == 2
    assert [a.artifact_id for a in report.artifacts] == ["run:trigger"]
