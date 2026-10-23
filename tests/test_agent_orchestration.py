"""Repeatable application and actual LangGraph routing/contract tests."""

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from orchestration_fakes import ScriptedAgent, finding, reference

from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.budget import RunBudget, RunLimits
from ali_diagnosis.application.orchestration.contracts import (
    WhatDecision, WhyDecision, SynthesisDecision, ValidationDecision,
)
from ali_diagnosis.application.orchestration.errors import (
    DiagnosisExecutionError, InvalidDecisionError, ResourceLimitError,
)
from ali_diagnosis.application.orchestration.policy import apply_decision
from ali_diagnosis.application.orchestration.tools import DiagnosisTools
from ali_diagnosis.domain import (
    DiagnosisRunRequest,
)
from ali_diagnosis.infrastructure.synthetic_scenarios import synthetic_runtime


@pytest.fixture
def limits():
    return RunLimits(input_usd_per_million=1, output_usd_per_million=2)


@pytest.fixture
def request_case():
    return DiagnosisRunRequest(diagnosis_run_id="run", learner_id="learner", evidence_id="evidence")


@pytest.mark.parametrize("capability,refine", [(False, False), (True, False), (False, True)])
def test_adaptive_graph_and_capability_provenance(limits, request_case, capability, refine):
    agent = ScriptedAgent(capability=capability, refine=refine)
    runtime = synthetic_runtime(agent, limits, "success")
    report = asyncio.run(runtime.run(request_case))
    assert report.outcome.status == "completed"
    assert report.stage_visits == (6 if refine else 4)
    assert agent.visits == (["what", "why", "what", "why", "synthesis", "validation"]
                            if refine else ["what", "why", "synthesis", "validation"])
    assert report.artifacts[0].source_references == [reference()]
    assert not hasattr(report, "messages")
    if capability:
        artifact = report.artifacts[-1]
        assert artifact.result["implementation_version"] == "synthetic-v1"
        assert artifact.source_references == [reference()]
        assert report.outcome.why[0].supporting_sources[0].source_id == artifact.artifact_id


@pytest.mark.parametrize("scenario", ["insufficient", "contradictory"])
def test_unresolved_is_a_valid_educational_outcome(limits, request_case, scenario):
    report = asyncio.run(synthetic_runtime(ScriptedAgent(unresolved=True), limits, scenario).run(request_case))
    assert report.outcome.status == "unresolved"
    assert reference() in report.outcome.relevant_sources
    assert reference("evidence:history") in report.outcome.relevant_sources


def test_technical_failure_is_not_unresolved(limits, request_case):
    with pytest.raises(DiagnosisExecutionError, match="Unrecovered tool"):
        asyncio.run(synthetic_runtime(ScriptedAgent(unresolved=True), limits, "tool_failure").run(request_case))


def test_stage_limit_is_technical_not_educational(limits, request_case):
    limits = limits.model_copy(update={"max_stage_visits": 1})
    with pytest.raises(ResourceLimitError, match="iteration limit"):
        asyncio.run(synthetic_runtime(ScriptedAgent(), limits, "success").run(request_case))


def make_tools(limits, request_case):
    runtime = synthetic_runtime(ScriptedAgent(), limits, "success")
    case = DiagnosisRuntimeState(request_case)
    return case, DiagnosisTools(case, RunBudget(limits), runtime.gateway, runtime.information,
                                runtime.anchor_source, runtime.registry, runtime.capabilities)


def test_tool_controls_unknown_selection_arguments_and_applicability(limits, request_case):
    async def run():
        case, tools = make_tools(limits, request_case)
        assert (await tools.call("get_information", {"source": "arbitrary"}))["error"] == "invalid_tool_request"
        assert (await tools.call("get_information", {"source": "history"}))["error"] == "invalid_tool_request"
        await tools.call("get_information", {"source": "trigger"})
        args = {"name": "synthetic-response-tracing", "inputs": {"artifact_id": "run:trigger"},
                "source_references": [reference("fabricated").model_dump(mode="json")]}
        assert (await tools.call("invoke_capability", args))["error"] == "invalid_tool_request"
        args["source_references"] = [reference().model_dump(mode="json")]
        args["inputs"] = {"artifact_id": "missing"}
        assert (await tools.call("invoke_capability", args))["error"] == "capability_not_applicable"
        args["inputs"] = {"artifact_id": "run:trigger", "unexpected": 1}
        assert (await tools.call("invoke_capability", args))["error"] == "invalid_tool_request"
        assert len(case.artifacts) == 1
    asyncio.run(run())


def test_fabricated_provenance_and_early_accept_are_rejected(limits, request_case):
    async def run():
        case, tools = make_tools(limits, request_case)
        await tools.call("get_information", {"source": "trigger"})
        false_finding = finding(case).model_copy(update={"supporting_sources": [reference("invented")]})
        with pytest.raises(InvalidDecisionError, match="Source references"):
            apply_decision(case, WhatDecision(findings=[false_finding], next_stage="why"))
        apply_decision(case, WhatDecision(findings=[finding(case)], next_stage="validation"))
        with pytest.raises(InvalidDecisionError, match="current synthesis"):
            apply_decision(case, ValidationDecision(decision="accept", reason="Accept"))
    asyncio.run(run())


@pytest.mark.parametrize("field,value,operation", [
    ("max_model_calls", 1, "model"), ("max_tool_calls", 1, "tool"),
    ("max_cost_usd", 0.000001, "model"), ("max_input_tokens", 100, "model"),
])
def test_shared_budget_fails_before_excess_calls(limits, field, value, operation):
    budget = RunBudget(limits.model_copy(update={field: value}))
    with pytest.raises(ResourceLimitError):
        for _ in range(2):
            budget.reserve_model(1000) if operation == "model" else budget.reserve_tool()
    assert budget.model_calls <= 1


def test_deadline_cancels_slow_stage(limits, request_case):
    class SlowAgent:
        async def run_stage(self, case, tools, budget):
            await asyncio.sleep(10)
    with pytest.raises(ResourceLimitError, match="deadline"):
        asyncio.run(synthetic_runtime(SlowAgent(), limits.model_copy(update={"max_seconds": 0.01}), "success").run(request_case))


def test_reusable_runtime_has_fresh_run_state(limits, request_case):
    runtime = synthetic_runtime(ScriptedAgent(), limits, "success")
    first = asyncio.run(runtime.run(request_case))
    second = asyncio.run(runtime.run(request_case.model_copy(update={"diagnosis_run_id": "other"})))
    assert first.outcome.diagnosis_run_id == "run"
    assert second.outcome.diagnosis_run_id == "other"
    assert all(a.diagnosis_run_id == "other" for a in second.artifacts)


@pytest.mark.parametrize("failure", ["applicability", "execution", "output"])
def test_capability_failures_are_safe_and_can_recover(limits, request_case, failure):
    async def run():
        case, tools = make_tools(limits, request_case)
        await tools.call("get_information", {"source": "trigger"})
        name = "synthetic-response-tracing"
        original = tools.capabilities[name]

        def broken_applicability(*args):
            raise RuntimeError("private payload")

        async def broken_execution(*args):
            raise RuntimeError("private payload")

        async def invalid_output(*args):
            return case.request

        updates = ({"applicable": broken_applicability} if failure == "applicability" else
                   {"execute": broken_execution if failure == "execution" else invalid_output})
        tools.capabilities[name] = replace(original, **updates)
        args = {"name": name, "inputs": {"artifact_id": "run:trigger"},
                "source_references": [reference().model_dump(mode="json")]}
        result = await tools.call("invoke_capability", args)
        assert result == {"error": "capability_failed", "name": name}
        assert tools.case.tool_failures
        assert len(case.artifacts) == 1
        tools.capabilities[name] = original
        assert "artifact" in await tools.call("invoke_capability", args)
        assert not tools.case.tool_failures
    asyncio.run(run())


def test_new_information_invalidates_candidate(limits, request_case):
    async def run():
        case, tools = make_tools(limits, request_case)
        agent = ScriptedAgent()
        for _ in range(3):
            apply_decision(case, await agent.run_stage(case, tools, tools.budget))
        assert case.synthesis_candidate is not None
        await tools.call("get_information", {"source": "history"})
        assert case.synthesis_candidate is None
        with pytest.raises(InvalidDecisionError):
            apply_decision(case, ValidationDecision(decision="accept", reason="Cannot reuse stale candidate."))
    asyncio.run(run())


def test_only_used_artifacts_are_returned(limits, request_case):
    report = asyncio.run(synthetic_runtime(ScriptedAgent(refine=True), limits, "success").run(request_case))
    # Script retrieves history but its final claims cite only the triggering evidence.
    assert [a.producer for a in report.artifacts] == ["synthetic:trigger"]


def test_gateway_rejects_entire_invalid_selection_before_source_calls(request_case):
    from ali_diagnosis.application import InformationGateway
    calls = []

    class Source:
        def get_information(self, request):
            calls.append(request)
            return {}

    gateway = InformationGateway({"source": Source()})
    with pytest.raises(KeyError):
        gateway.get_information(request_case, source_names=("source", "unknown"))
    assert calls == []


@pytest.mark.parametrize("next_stage", ["synthesis", "validation"])
def test_what_cannot_skip_why_and_accept(limits, request_case, next_stage):
    class SkippingAgent(ScriptedAgent):
        async def run_stage(self, case, tools, budget):
            decision = await super().run_stage(case, tools, budget)
            if case.current_stage == "what":
                return decision.model_copy(update={"next_stage": next_stage})
            return decision

    agent = SkippingAgent()
    expected = "requires WHY" if next_stage == "synthesis" else "current synthesis"
    with pytest.raises(InvalidDecisionError, match=expected):
        asyncio.run(synthetic_runtime(agent, limits, "success").run(request_case))
    # Bounded retries remain in the rejected stage; illegal transitions stay illegal.
    assert agent.visits == (["what"] * 3 if next_stage == "synthesis" else ["what"] + ["validation"] * 3)


def test_rejected_transition_leaves_current_case_unchanged(limits, request_case):
    async def run():
        case, tools = make_tools(limits, request_case)
        await tools.call("get_information", {"source": "trigger"})
        before = deepcopy(case)
        with pytest.raises(InvalidDecisionError, match="requires WHY"):
            apply_decision(case, WhatDecision(findings=[finding(case)], next_stage="synthesis"))
        assert case == before
    asyncio.run(run())


@pytest.fixture
def candidate_case(limits, request_case):
    async def prepare():
        case, tools = make_tools(limits, request_case)
        agent = ScriptedAgent()
        for _ in range(3):
            apply_decision(case, await agent.run_stage(case, tools, tools.budget))
        return case, tools
    return asyncio.run(prepare())


@pytest.mark.parametrize("revision", ["what", "why"])
def test_revised_claims_require_dependent_stages_again(candidate_case, revision):
    case, tools = candidate_case
    old_candidate = deepcopy(case.synthesis_candidate)
    apply_decision(case, ValidationDecision(decision="refine", next_stage=revision,
                                            reason="Reconsider current claims."))
    if revision == "what":
        updated = case.what_findings[0].model_copy(update={"problem_statement": "Revised problem."})
        decision = WhatDecision(findings=[updated], next_stage="validation")
    else:
        updated = case.why_hypotheses[0].model_copy(update={"hypothesis_statement": "Revised cause."})
        decision = WhyDecision(hypotheses=[updated], next_stage="validation")
    apply_decision(case, decision)
    assert case.what_complete
    assert case.why_complete == (revision == "why")
    assert case.synthesis_candidate is None
    assert case.latest_validation_result is None
    if revision == "what":
        assert case.why_hypotheses == []

    before = deepcopy(case)
    with pytest.raises(InvalidDecisionError, match="current synthesis"):
        apply_decision(case, ValidationDecision(decision="accept", reason="Try stale acceptance."))
    assert case == before  # Includes assessment counters and publication state.
    if revision == "what":
        with pytest.raises(InvalidDecisionError, match="requires WHY"):
            apply_decision(case, ValidationDecision(decision="refine", next_stage="synthesis",
                                                    reason="Try skipping renewed WHY."))
        assert case == before

    async def finish():
        apply_decision(case, ValidationDecision(decision="refine",
                                                next_stage="why" if revision == "what" else "synthesis",
                                                reason="Revisit invalidated conclusions."))
        agent = ScriptedAgent()
        if revision == "what":
            apply_decision(case, await agent.run_stage(case, tools, tools.budget))
        # Replaying the original synthesis cannot erase the revised claims.
        before_synthesis = deepcopy(case)
        with pytest.raises(InvalidDecisionError, match="Revise WHAT/WHY"):
            apply_decision(case, SynthesisDecision(candidate=old_candidate, next_stage="validation"))
        assert case == before_synthesis
        apply_decision(case, await agent.run_stage(case, tools, tools.budget))
        apply_decision(case, await agent.run_stage(case, tools, tools.budget))
        assert case.final_result.what == case.what_findings
        assert case.final_result.why == case.why_hypotheses
        assert case.final_result != old_candidate
    asyncio.run(finish())


@pytest.mark.parametrize("missing_stage", ["what", "why"])
def test_populated_claims_and_candidate_do_not_replace_stage_completion(candidate_case, missing_stage):
    case, _ = candidate_case
    setattr(case, f"{missing_stage}_complete", False)
    before = deepcopy(case)
    with pytest.raises(InvalidDecisionError, match="completed WHAT"):
        apply_decision(case, ValidationDecision(decision="accept", reason="Candidate alone is insufficient."))
    assert case == before


@pytest.mark.parametrize("field,value", [
    ("learner_id", "another-learner"), ("what", []),
])
def test_acceptance_rechecks_candidate_contract_and_identity(candidate_case, field, value):
    case, _ = candidate_case
    case.synthesis_candidate = case.synthesis_candidate.model_copy(update={field: value})
    before = deepcopy(case)
    with pytest.raises(InvalidDecisionError):
        apply_decision(case, ValidationDecision(decision="accept", reason="Recheck candidate."))
    assert case == before


def test_investigated_but_unsupported_why_returns_unresolved(limits, request_case):
    class UncertainCauseAgent(ScriptedAgent):
        async def run_stage(self, case, tools, budget):
            if case.current_stage == "why":
                self.visits.append("why")
                return WhyDecision(hypotheses=[], next_stage="validation")
            if case.current_stage == "validation":
                self.visits.append("validation")
                assert case.what_findings
                assert case.why_complete and not case.why_hypotheses
                assert case.synthesis_candidate is None
                return ValidationDecision(decision="unresolved", unresolved_scope="why",
                                          reason="Evidence supports a problem but cannot distinguish causes.")
            return await super().run_stage(case, tools, budget)

    agent = UncertainCauseAgent()
    report = asyncio.run(synthetic_runtime(agent, limits, "insufficient").run(request_case))
    assert report.outcome.status == "unresolved"
    assert report.outcome.unresolved_scope == "why"
    assert reference() in report.outcome.relevant_sources
    assert agent.visits == ["what", "why", "validation"]


@pytest.mark.parametrize("revisit", ["what", "why"])
def test_new_evidence_can_drive_revisits_before_acceptance(limits, request_case, revisit):
    class InvestigatingAgent(ScriptedAgent):
        async def run_stage(self, case, tools, budget):
            if case.current_stage == "validation" and case.iteration_count == 0:
                self.visits.append("validation")
                assert "artifact" in await tools.call("get_information", {"source": "history"})
                assert case.synthesis_candidate is None
                return ValidationDecision(decision="refine", next_stage=revisit,
                                          reason="New history requires revisiting the case.")
            decision = await super().run_stage(case, tools, budget)
            if case.iteration_count and case.current_stage == revisit:
                claims = decision.findings if revisit == "what" else decision.hypotheses
                field = "problem_statement" if revisit == "what" else "hypothesis_statement"
                claims[0] = claims[0].model_copy(update={
                    field: "Revised after retrieved history.",
                    "supporting_sources": [reference("evidence:history")],
                })
            return decision

    agent = InvestigatingAgent()
    report = asyncio.run(synthetic_runtime(agent, limits, "success").run(request_case))
    assert report.outcome.status == "completed"
    expected = ["what", "why", "synthesis", "validation"]
    assert agent.visits == expected + expected[expected.index(revisit):]
    claim = report.outcome.what[0] if revisit == "what" else report.outcome.why[0]
    assert claim.supporting_sources == [reference("evidence:history")]
    assert any(a.producer == "synthetic:history" for a in report.artifacts)


@pytest.mark.parametrize("tool_name,args", [
    ("get_information", {"source": "history"}),
    ("invoke_capability", {"name": "synthetic-response-tracing", "inputs": {"artifact_id": "run:trigger"},
                           "source_references": [{"source_kind": "evidence", "source_id": "evidence"}]}),
])
def test_new_tool_results_require_fresh_synthesis(candidate_case, tool_name, args):
    async def run():
        case, tools = candidate_case
        apply_decision(case, ValidationDecision(decision="refine", next_stage="validation",
                                                reason="Gather corroboration."))
        assert "artifact" in await tools.call(tool_name, args)
        assert case.synthesis_candidate is None
        assert case.latest_validation_result is None
        before = deepcopy(case)
        with pytest.raises(InvalidDecisionError, match="current synthesis"):
            apply_decision(case, ValidationDecision(decision="accept", reason="Cannot accept stale synthesis."))
        assert case == before
        apply_decision(case, ValidationDecision(decision="refine", next_stage="synthesis",
                                                reason="Review current evidence in synthesis."))
        agent = ScriptedAgent()
        for _ in range(2):
            apply_decision(case, await agent.run_stage(case, tools, tools.budget))
        assert case.final_result.status == "completed"
    asyncio.run(run())
