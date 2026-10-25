"""Exercise the actual prebuilt loop and both provider adapters without network."""

import asyncio
import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from ali_diagnosis.application.orchestration.budget import RunLimits
from ali_diagnosis.application.orchestration.errors import ProviderError, ResourceLimitError
from ali_diagnosis.domain import DiagnosisRunRequest
from ali_diagnosis.infrastructure.langgraph_runtime.llm_agent import LangChainStageAgent
from ali_diagnosis.infrastructure.synthetic_scenarios import synthetic_runtime


class ToolCallingFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


def successful_script():
    ref = {"source_kind": "evidence", "source_id": "evidence"}
    subject = {"taxonomy_id": "synthetic:fraction-addition", "taxonomy_level": "concept"}
    finding = {"finding_id": "f", "subject_ref": subject, "problem_statement": "Synthetic pattern.",
               "confidence": 0.5, "supporting_sources": [ref], "contradicting_sources": []}
    hypothesis = {"hypothesis_id": "h", "hypothesis_statement": "Synthetic procedural hypothesis.",
                  "confidence": 0.5, "explains_finding_ids": ["f"], "supporting_sources": [ref],
                  "contradicting_sources": []}
    return [
        call("get_information", {"source": "trigger"}),
        call("discover_capabilities", {}),
        call("WhatDecision", {"findings": [finding], "next_stage": "why"}),
        call("WhyDecision", {"hypotheses": [hypothesis], "next_stage": "synthesis"}),
        call("SynthesisDecision", {"candidate": {
            "diagnosis_run_id": "run", "learner_id": "learner", "subject_ref": subject,
            "what": [finding], "why": [hypothesis],
        }, "next_stage": "validation"}),
        call("ValidationDecision", {"decision": "accept", "reason": "Fixture evidence supports candidate."}),
    ]


def run_model(model, **overrides):
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2,
                       max_input_tokens=100000, **overrides)
    request = DiagnosisRunRequest(diagnosis_run_id="run", learner_id="learner", evidence_id="evidence")
    return asyncio.run(synthetic_runtime(LangChainStageAgent(model), limits, "success").run(request))


def test_actual_prebuilt_agent_calls_tools_and_structured_stage_outputs():
    report = run_model(ToolCallingFake(messages=iter(successful_script())))
    assert report.outcome.status == "completed"
    assert report.model_calls == 6
    assert report.tool_calls == 2
    assert report.reserved_cost_usd > 0


class EvidenceReactiveModel(BaseChatModel):
    """Deterministic model double that reads actual context/tool messages.

    Unlike a response iterator, its choices and final content depend on the tool
    results it receives. It tests plumbing, not real LLM diagnostic intelligence.
    """

    goals: list[str] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    signals: list[float] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "evidence-reactive-test-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        context = json.loads(next(m.content for m in messages if m.type == "human"))
        goal = context["current_stage"]
        tool_results = [json.loads(m.content) for m in messages if m.type == "tool"]
        if not tool_results:
            self.goals.append(goal)
        artifacts = context["artifacts"] + [r["artifact"] for r in tool_results if "artifact" in r]
        measurements = [a for a in artifacts if a["artifact_type"] == "capability_result"]

        if goal == "what":
            if not artifacts:
                message = call("get_information", {"source": "trigger"})
            else:
                source = artifacts[0]
                statement, confidence, refs = "Initial observation", 0.4, source["source_references"]
                if measurements:
                    measurement = measurements[-1]
                    value = measurement["result"]["output"]["repeated_error_signal"]
                    statement = "Refined high synthetic signal" if value >= 0.5 else "Refined low synthetic signal"
                    confidence = value
                    refs = [{"source_kind": "capability_result", "source_id": measurement["artifact_id"]}]
                message = call("WhatDecision", {"findings": [{
                    "finding_id": "f", "subject_ref": source["subject_ref"],
                    "problem_statement": statement, "confidence": confidence,
                    "supporting_sources": refs,
                }], "next_stage": "why"})
        elif goal == "why":
            discovered = [r["capabilities"] for r in tool_results if "capabilities" in r]
            if not measurements and not discovered:
                message = call("discover_capabilities", {})
            elif not measurements:
                instrument = next(c for c in discovered[-1] if "Measure a controlled" in c["purpose"])
                self.selected.append(instrument["name"])
                message = call("invoke_capability", {
                    "name": instrument["name"], "inputs": {"artifact_id": artifacts[0]["artifact_id"]},
                    "source_references": artifacts[0]["source_references"],
                })
            elif context["current_findings"][0]["problem_statement"] == "Initial observation":
                self.signals.append(measurements[-1]["result"]["output"]["repeated_error_signal"])
                message = call("WhyDecision", {"hypotheses": [], "next_stage": "what"})
            else:
                measurement = measurements[-1]
                message = call("WhyDecision", {"hypotheses": [{
                    "hypothesis_id": "h", "hypothesis_statement": "Qualified synthetic explanation.",
                    "confidence": context["current_findings"][0]["confidence"],
                    "explains_finding_ids": ["f"], "supporting_sources": [
                        {"source_kind": "capability_result", "source_id": measurement["artifact_id"]}],
                }], "next_stage": "synthesis"})
        elif goal == "synthesis":
            message = call("SynthesisDecision", {"candidate": {
                "diagnosis_run_id": context["request"]["diagnosis_run_id"],
                "learner_id": context["request"]["learner_id"], "subject_ref": context["subject"],
                "what": context["current_findings"], "why": context["current_hypotheses"],
            }, "next_stage": "validation"})
        else:
            message = call("ValidationDecision", {"decision": "accept", "reason": "Synthetic case reviewed."})
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.parametrize("signal", [0.2, 0.8])
def test_tool_result_drives_refinement_through_real_prebuilt_loop_and_graph(signal):
    from dataclasses import replace
    from ali_diagnosis.infrastructure.synthetic_scenarios import MockTracingOutput

    model = EvidenceReactiveModel()
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2, max_input_tokens=100000)
    runtime = synthetic_runtime(LangChainStageAgent(model), limits, "success")
    # Rename the available capability. The agent must discover the actual name,
    # not rely on the original mock's constant identifier or prewritten tool calls.
    original_name = next(iter(runtime.capabilities))
    original = runtime.registry.resolve(original_name)
    metadata = original.metadata.model_copy(update={"name": "available-instrument"})
    from ali_diagnosis.application import CapabilityRegistry
    from types import SimpleNamespace
    registry = CapabilityRegistry()
    registry.register(SimpleNamespace(metadata=metadata))
    runtime.registry = registry

    async def measured_output(inputs, case):
        return MockTracingOutput(repeated_error_signal=signal)

    runtime.capabilities = {metadata.name: replace(runtime.capabilities[original_name], execute=measured_output)}
    report = asyncio.run(runtime.run(DiagnosisRunRequest(
        diagnosis_run_id="dynamic", learner_id="synthetic-learner", evidence_id="dynamic-evidence")))
    assert model.goals == ["what", "why", "what", "why", "synthesis", "validation"]
    assert model.selected == [metadata.name]
    assert model.signals == [signal]
    assert report.stage_visits == 6
    assert report.tool_calls == 3
    assert report.outcome.what[0].confidence == signal
    assert report.outcome.what[0].problem_statement == (
        "Refined high synthetic signal" if signal >= 0.5 else "Refined low synthetic signal")
    assert report.outcome.why[0].supporting_sources[0].source_id == report.artifacts[-1].artifact_id


def test_schema_repair_is_bounded_and_uses_prebuilt_loop():
    messages = successful_script()
    messages.insert(2, call("WhatDecision", {"wrong_field": True}))
    report = run_model(ToolCallingFake(messages=iter(messages)))
    assert report.model_calls == 7


def test_endless_model_tool_loop_hits_shared_budget():
    model = ToolCallingFake(messages=iter([call("discover_capabilities", {})] * 10))
    with pytest.raises(ResourceLimitError, match="Tool call limit"):
        run_model(model, max_tool_calls=2)


def test_malformed_tool_arguments_count_toward_budget():
    model = ToolCallingFake(messages=iter([call("get_information", {"wrong": True})] * 5))
    with pytest.raises(ResourceLimitError, match="Tool call limit"):
        run_model(model, max_tool_calls=2)


def test_provider_error_is_sanitized():
    # Exhausted fake provider raises StopIteration, wrapped by its async implementation.
    class FailingModel(ToolCallingFake):
        async def _agenerate(self, *args, **kwargs):
            raise RuntimeError("SECRET credential and raw learner payload")
    with pytest.raises(ProviderError) as error:
        run_model(FailingModel(messages=iter([])))
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("status,retry_count", [(429, 1), (401, 0)])
def test_provider_retries_only_transient_failures_and_counts_reservations(status, retry_count):
    class ProviderFailure(RuntimeError):
        status_code = status

    class RetryModel(ToolCallingFake):
        attempts: int = 0

        async def _agenerate(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderFailure("Do not expose provider details")
            return await super()._agenerate(*args, **kwargs)

    model = RetryModel(messages=iter(successful_script()))
    if retry_count:
        report = run_model(model)
        assert report.model_calls == 7
        assert model.attempts == 7
    else:
        with pytest.raises(ProviderError):
            run_model(model)
        assert model.attempts == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic", "deepseek", "google_genai", "groq"])
@pytest.mark.parametrize("fail", [False, True])
def test_provider_substitution_uses_identical_prompts_tools_and_policy(monkeypatch, provider, fail):
    """Real provider SDKs and serializers, controlled HTTP transports, no real model."""
    pytest.importorskip(f"langchain_{provider}")
    from ali_diagnosis.infrastructure.model_configuration import ModelConfiguration, create_stage_agent

    # Replace the HTTP send boundary before initializing the real configured model.
    # No request can reach the provider; real serialization/parsing still runs.
    if provider in ("openai", "deepseek", "anthropic"):
        import importlib
        sdk_client = importlib.import_module(
            "anthropic._base_client" if provider == "anthropic" else "openai._base_client")
        httpx = getattr(sdk_client, "httpx2", None) or sdk_client.httpx
    else:
        httpx = pytest.importorskip("httpx")
    if provider == "google_genai":
        import google.genai._api_client as google_client
        monkeypatch.setattr(google_client, "has_aiohttp", False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_ENTERPRISE", raising=False)
    script = iter(successful_script())
    requests = []

    async def respond(client, request, **kwargs):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.host == "provider.invalid"
        assert request.extensions["timeout"]["read"] == 60
        if fail:
            return httpx.Response(500, request=request, json={
                "error": {"code": 500, "status": "INTERNAL", "message": "Synthetic failure",
                          "type": "server_error"},
            })
        message = next(script)
        invocation = message.tool_calls[0]
        if provider in ("openai", "deepseek", "groq"):
            payload = {"id": "chatcmpl-test", "object": "chat.completion", "created": 0,
                       "model": "test-model", "choices": [{"index": 0, "finish_reason": "tool_calls",
                       "message": {"role": "assistant", "content": None, "tool_calls": [{
                           "id": invocation["id"], "type": "function", "function": {
                               "name": invocation["name"], "arguments": json.dumps(invocation["args"]),
                           }}]}}], "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}
        elif provider == "anthropic":
            payload = {"id": "msg-test", "type": "message", "role": "assistant", "model": "test-model",
                       "content": [{"type": "tool_use", "id": invocation["id"],
                                    "name": invocation["name"], "input": invocation["args"]}],
                       "stop_reason": "tool_use", "stop_sequence": None,
                       "usage": {"input_tokens": 100, "output_tokens": 100}}
        else:
            payload = {"candidates": [{"content": {"role": "model", "parts": [{
                "functionCall": {"name": invocation["name"], "args": invocation["args"]},
                "thoughtSignature": "c3ludGhldGlj",
            }]}, "finishReason": "STOP"}], "modelVersion": "test-model",
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 100, "totalTokenCount": 200}}
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", respond)
    monkeypatch.setenv("SYNTHETIC_KEY", "synthetic-key")
    limits = RunLimits(input_usd_per_million=1, output_usd_per_million=2,
                       max_input_tokens=100000, max_provider_retries=0)
    agent = create_stage_agent(ModelConfiguration(provider=provider, model="test-model",
                               api_key_env="SYNTHETIC_KEY", base_url="https://provider.invalid"), limits)
    runtime = synthetic_runtime(agent, limits, "success")
    request = DiagnosisRunRequest(diagnosis_run_id="run", learner_id="learner", evidence_id="evidence")
    if fail:
        with pytest.raises(ProviderError):
            asyncio.run(runtime.run(request))
        assert len(requests) == 1, "SDK must not retry outside the application budget"
        return
    report = asyncio.run(runtime.run(request))
    assert report.outcome.status == "completed"
    assert report.model_calls == 6
    assert len(requests) == 6
    assert all("tools" in body for body in requests)
    if provider == "google_genai":
        assert "c3ludGhldGlj" in json.dumps(requests[1]["contents"])
    for body in requests:
        if provider == "google_genai":
            assert body["generationConfig"]["maxOutputTokens"] == limits.max_output_tokens
            assert "responseJsonSchema" not in body["generationConfig"]
        else:
            assert body.get("max_completion_tokens", body.get("max_tokens")) == limits.max_output_tokens
            assert "response_format" not in body  # Stage outputs use ToolStrategy.
        if provider == "deepseek":
            assert body["thinking"] == {"type": "disabled"}


class BudgetObservingModel(ToolCallingFake):
    contexts: list[dict] = Field(default_factory=list)
    resources: list[dict] = Field(default_factory=list)

    async def _agenerate(self, messages, **kwargs):
        self.contexts.append(json.loads(next(m.content for m in messages if m.type == "human")))
        system = next(m.content for m in messages if m.type == "system")
        self.resources.append(json.loads(system.split("\nCurrent resource budget: ")[-1]))
        return await super()._agenerate(messages, **kwargs)


def test_policy_correction_reenters_actual_agent_with_feedback_and_shared_budget(monkeypatch):
    from ali_diagnosis.application.orchestration.budget import RunBudget
    reservations = []
    original = RunBudget.reserve_model

    def reserve(budget, tokens):
        original(budget, tokens)
        reservations.append(budget.model_cost(tokens))

    monkeypatch.setattr(RunBudget, "reserve_model", reserve)
    messages = successful_script()
    invalid = call("WhatDecision", {**messages[2].tool_calls[0]["args"], "next_stage": "synthesis"})
    messages.insert(2, invalid)
    model = BudgetObservingModel(messages=iter(messages))
    report = run_model(model)
    assert report.outcome.status == "completed"
    assert report.model_calls == 7 and report.tool_calls == 2
    assert report.reserved_cost_usd == pytest.approx(sum(reservations))
    correction = model.contexts[3]
    assert correction["current_stage"] == "what"
    assert "requires WHY" in correction["decision_feedback"]
    assert correction["artifacts"] and not correction["current_findings"]
    assert [r["remaining_model_calls"] for r in model.resources] == list(range(32, 25, -1))
    assert model.resources[1]["remaining_tool_calls"] == 23
    assert model.resources[-1]["remaining_estimated_cost_usd"] < model.resources[0]["remaining_estimated_cost_usd"]


def test_inner_tool_loop_preserves_one_call_for_validation_before_what_completes():
    model = BudgetObservingModel(messages=iter([
        call("get_information", {"source": "trigger"}),
        call("ValidationDecision", {"decision": "unresolved", "reason": "The investigation was interrupted."}),
    ]))
    report = run_model(model, max_model_calls=2)
    assert report.outcome.status == "unresolved"
    assert report.resource_limit_reason and "resource limits" in report.outcome.reason
    assert report.model_calls == 2 and report.tool_calls == 1
    assert report.stage_visits == 1  # Only Validation completed a decision.
    assert not report.partial_findings and not report.partial_hypotheses
    assert report.artifacts
    assert [c["current_stage"] for c in model.contexts] == ["what", "validation"]
    assert not model.contexts[-1]["what_complete"]
    assert model.contexts[-1]["finalization_reason"]


def test_repeated_policy_failures_count_every_real_correction_call(monkeypatch):
    from ali_diagnosis.application.orchestration.budget import RunBudget
    from ali_diagnosis.application.orchestration.errors import InvalidDecisionError
    captured = []
    original = RunBudget.reserve_model

    def reserve(budget, tokens):
        original(budget, tokens)
        captured.append((budget, budget.model_cost(tokens)))

    monkeypatch.setattr(RunBudget, "reserve_model", reserve)
    messages = successful_script()
    invalid = call("WhatDecision", {**messages[2].tool_calls[0]["args"], "next_stage": "synthesis"})
    model = BudgetObservingModel(messages=iter([messages[0], invalid, invalid, invalid]))
    with pytest.raises(InvalidDecisionError, match="correction limit exceeded"):
        run_model(model)
    budget = captured[-1][0]
    assert budget.model_calls == len(captured) == 4
    assert budget.tool_calls == 1
    assert budget.reserved_cost_usd == pytest.approx(sum(cost for _, cost in captured))
    assert model.contexts[-1]["decision_feedback"]


def test_inner_unknown_tool_attempts_are_counted_before_finalization():
    model = BudgetObservingModel(messages=iter([
        call("get_information", {"source": "trigger"}),
        call("unknown_tool", {"unexpected": True}),
        call("discover_capabilities", {}),
        call("ValidationDecision", {"decision": "unresolved", "reason": "Further investigation is unavailable."}),
    ]))
    report = run_model(model, max_tool_calls=2)
    assert report.outcome.status == "unresolved"
    # Two admitted attempts; the third is rejected before dispatch.
    assert report.tool_calls == 2 and report.model_calls == 4
    assert "Tool call limit" in report.resource_limit_reason
    assert model.resources[2]["remaining_tool_calls"] == 0


def test_provider_usage_violation_is_not_converted_to_resource_unresolved():
    messages = successful_script()
    messages[1].usage_metadata = {"input_tokens": 10000000, "output_tokens": 1, "total_tokens": 10000001}
    model = BudgetObservingModel(messages=iter(messages))
    with pytest.raises(ResourceLimitError, match="reserved token envelope"):
        run_model(model)
    assert len(model.contexts) == 2
