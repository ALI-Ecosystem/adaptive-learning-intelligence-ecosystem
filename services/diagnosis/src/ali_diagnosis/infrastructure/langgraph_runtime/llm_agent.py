"""A mature prebuilt tool loop, adapted to the application StageAgent boundary."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langsmith import tracing_context

from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.budget import RunBudget
from ali_diagnosis.application.orchestration.contracts import OUTPUT_TYPES, StageDecision
from ali_diagnosis.application.orchestration.errors import (
    DiagnosisExecutionError, FinalAssessmentRequired, ProviderError, ResourceLimitError,
)
from ali_diagnosis.application.orchestration.prompts import stage_context, stage_prompt
from ali_diagnosis.application.orchestration.tools import DiagnosisTools


class _BudgetMiddleware(AgentMiddleware):
    def __init__(self, budget: RunBudget, schema: type, output_token_parameter: str,
                 case: DiagnosisRuntimeState) -> None:
        self.budget, self.schema = budget, schema
        self.output_token_parameter = output_token_parameter
        self.case = case

    async def awrap_model_call(self, request, handler):
        for attempt in range(self.budget.limits.max_provider_retries + 1):
            self.budget.check_progress(self.case)
            # Refresh inside the prebuilt loop and on provider retries. Include
            # the new context in the conservative UTF-8 input reservation.
            resources = self.budget.remaining_resources(self.case.stage_visits)
            resources["prioritize_existing_evidence"] = self.budget.prioritize_existing_evidence(self.case)
            system = SystemMessage(content=(str(request.system_message.content) if request.system_message else "")
                                   + "\nCurrent resource budget: " + json.dumps(resources))
            updated = request.override(system_message=system)
            envelope = {
                "messages": [m.model_dump(mode="json") for m in request.messages],
                "system": system.model_dump(mode="json"),
                "tools": [convert_to_openai_tool(t) for t in request.tools],
                "response": self.schema.model_json_schema(),
            }
            input_bound = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) + 2048
            timeout = self.budget.call_seconds(self.case)
            self.budget.reserve_model(input_bound)
            try:
                async with asyncio.timeout(timeout):
                    response = await handler(updated.override(model_settings={
                        **request.model_settings, self.output_token_parameter: self.budget.limits.max_output_tokens,
                    }))
                # Fail closed if the provider violates the configured usage envelope.
                for message in response.result:
                    usage = getattr(message, "usage_metadata", None)
                    if usage and (usage.get("input_tokens", 0) > input_bound or
                                  usage.get("output_tokens", 0) > self.budget.limits.max_output_tokens):
                        raise ResourceLimitError("Provider exceeded the reserved token envelope")
                    # Reserve the complete dispatch batch before entering ToolNode,
                    # whose recoverable-error handling must not swallow run limits.
                    # Structured output calls are model outputs, not capability calls.
                    for invocation in getattr(message, "tool_calls", []):
                        if invocation["name"] != self.schema.__name__:
                            self.budget.reserve_tool(self.case)
                return response
            except DiagnosisExecutionError:
                raise
            except TimeoutError:
                if self.case.artifacts and not self.case.finalization_reason:
                    raise FinalAssessmentRequired("model execution time reserved for a final assessment") from None
                raise ResourceLimitError("Model execution deadline exceeded") from None
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                retryable = status in (408, 429, 500, 502, 503, 504) or isinstance(exc, ConnectionError)
                if not retryable or attempt >= self.budget.limits.max_provider_retries:
                    raise ProviderError("Model provider failed or returned an invalid response") from None
                await asyncio.sleep(min(0.25 * 2**attempt, self.budget.remaining_seconds()))


class LangChainStageAgent:
    """Provider-compatible tool calling and Pydantic structured stage responses."""

    def __init__(self, model: BaseChatModel, *,
                 output_token_parameter: Literal["max_tokens", "max_output_tokens"] = "max_tokens") -> None:
        self.model = model
        self.output_token_parameter = output_token_parameter

    async def run_stage(self, case: DiagnosisRuntimeState, tools: DiagnosisTools, budget: RunBudget) -> StageDecision:
        @tool
        async def get_information(source: str) -> dict[str, Any]:
            """Retrieve a configured diagnostic source; retrieve subject-resolving source first."""
            return await tools.call("get_information", {"source": source}, count_attempt=False)

        @tool
        async def discover_capabilities() -> dict[str, Any]:
            """Discover available capability metadata, applicability, limitations, and schemas."""
            return await tools.call("discover_capabilities", {}, count_attempt=False)

        @tool
        async def invoke_capability(
            name: str, inputs: dict[str, Any], source_references: list[dict[str, str]],
        ) -> dict[str, Any]:
            """Invoke an allowlisted capability with schema-valid inputs and retrieved provenance."""
            return await tools.call("invoke_capability", {
                "name": name, "inputs": inputs, "source_references": source_references,
            }, count_attempt=False)

        schema = OUTPUT_TYPES[case.current_stage]
        agent = create_agent(
            self.model, tools=[] if case.finalization_reason else [get_information, discover_capabilities, invoke_capability],
            system_prompt=stage_prompt(case),
            response_format=ToolStrategy(schema, handle_errors="Return the requested schema with valid fields; no reasoning trace."),
            middleware=[_BudgetMiddleware(budget, schema, self.output_token_parameter, case)],
        )
        # Messages exist only inside this invocation. They never enter DiagnosisRuntimeState/RunReport.
        with tracing_context(enabled=False):
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": stage_context(case, tools)}]},
                config={"recursion_limit": budget.limits.max_model_calls * 4 + 4,
                        "callbacks": [], "max_concurrency": 1},
            )
        return schema.model_validate(result["structured_response"])
