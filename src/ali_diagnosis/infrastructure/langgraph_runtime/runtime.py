"""Replaceable run adapter: compose dependencies, invoke the graph, return its result."""

import asyncio
from collections.abc import Mapping

from langsmith import tracing_context

from ali_diagnosis.application import CapabilityRegistry, InformationGateway
from ali_diagnosis.application.orchestration.budget import RunBudget, RunLimits
from ali_diagnosis.application.orchestration.contracts import RunReport, StageAgent
from ali_diagnosis.application.orchestration.errors import ResourceLimitError
from ali_diagnosis.application.orchestration.policy import supporting_artifacts
from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.tools import (
    CapabilityBinding, DiagnosisTools, InformationBinding,
)
from ali_diagnosis.domain import DiagnosisRunRequest, UnresolvedDiagnosis
from .graph import build_diagnosis_graph


class LangGraphDiagnosisRuntime:
    """Implements DiagnosisRuntime reuses one graph implementation for every run."""

    def __init__(
        self, *, agent: StageAgent, information_gateway: InformationGateway,
        information: Mapping[str, InformationBinding], anchor_source: str,
        capability_registry: CapabilityRegistry,
        capabilities: Mapping[str, CapabilityBinding], limits: RunLimits,
    ) -> None:
        self.agent = agent
        self.gateway = information_gateway
        self.information = dict(information)
        self.anchor_source = anchor_source
        self.registry = capability_registry
        self.capabilities = dict(capabilities)
        self.limits = limits

    async def run(self, request: DiagnosisRunRequest) -> RunReport:
        budget = RunBudget(self.limits)

        def make_tools(state: DiagnosisRuntimeState) -> DiagnosisTools:
            return DiagnosisTools(state, budget, self.gateway, self.information,
                                  self.anchor_source, self.registry, self.capabilities)

        graph = build_diagnosis_graph(agent=self.agent, make_tools=make_tools, budget=budget)
        try:
            with tracing_context(enabled=False):
                async with asyncio.timeout(budget.remaining_seconds()):
                    result = await graph.ainvoke(DiagnosisRuntimeState(request=request),
                                                config={"callbacks": []})
        except TimeoutError:
            raise ResourceLimitError("Diagnosis execution deadline exceeded") from None
        state = DiagnosisRuntimeState(**result)
        assert state.final_result is not None
        return RunReport(
            outcome=state.final_result, artifacts=supporting_artifacts(state),
            stage_visits=state.stage_visits, model_calls=budget.model_calls,
            tool_calls=budget.tool_calls, reserved_cost_usd=budget.reserved_cost_usd,
            resource_limit_reason=state.finalization_reason if isinstance(state.final_result, UnresolvedDiagnosis) else None,
            partial_findings=tuple(state.what_findings) if isinstance(state.final_result, UnresolvedDiagnosis) else (),
            partial_hypotheses=tuple(state.why_hypotheses) if isinstance(state.final_result, UnresolvedDiagnosis) else (),
        )
