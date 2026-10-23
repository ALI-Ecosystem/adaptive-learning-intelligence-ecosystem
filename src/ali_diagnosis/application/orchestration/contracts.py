"""Application-only stage decisions and replaceable execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TYPE_CHECKING

from ali_diagnosis.domain import (
    DiagnosisRunRequest, DiagnosisRunResult, DiagnosticArtifact, DiagnosticFinding,
    RootCauseHypothesis, StructuredDiagnosis, UnresolvedScope,
)
from ali_diagnosis.domain.common import ContractModel, NonEmptyStr

if TYPE_CHECKING:
    from .budget import RunBudget
    from .tools import DiagnosisTools
    from .state import DiagnosisRuntimeState

Stage = Literal["what", "why", "synthesis", "validation"]


class WhatDecision(ContractModel):
    """Replace the current WHAT picture and choose the next goal."""

    findings: list[DiagnosticFinding]
    next_stage: Stage


class WhyDecision(ContractModel):
    """Replace the current WHY picture and choose the next goal."""

    hypotheses: list[RootCauseHypothesis]
    next_stage: Stage


class SynthesisDecision(ContractModel):
    """Propose a coherent candidate, or return to investigation."""

    candidate: StructuredDiagnosis | None
    next_stage: Stage


class ValidationDecision(ContractModel):
    """Public quality assessment, never private reasoning."""

    decision: Literal["accept", "unresolved", "refine"]
    next_stage: Stage = "what"
    unresolved_scope: UnresolvedScope = UnresolvedScope.BOTH
    reason: NonEmptyStr


StageDecision = WhatDecision | WhyDecision | SynthesisDecision | ValidationDecision
OUTPUT_TYPES: dict[Stage, type[ContractModel]] = {
    "what": WhatDecision, "why": WhyDecision,
    "synthesis": SynthesisDecision, "validation": ValidationDecision,
}


@dataclass(frozen=True)
class RunReport:
    """Outcome and supporting artifacts handed to the caller for persistence."""

    outcome: DiagnosisRunResult
    artifacts: tuple[DiagnosticArtifact, ...]
    stage_visits: int
    model_calls: int
    tool_calls: int
    reserved_cost_usd: float
    resource_limit_reason: str | None = None
    partial_findings: tuple[DiagnosticFinding, ...] = ()
    partial_hypotheses: tuple[RootCauseHypothesis, ...] = ()


class StageAgent(Protocol):
    """Replace model execution; reserve every actual model attempt in RunBudget.

    Corrections reuse this entry point with current decision_feedback and evidence.
    A stage invocation may contain multiple model calls; the executor must not
    charge it again. Deterministic agents without model calls need no reservation.
    """

    async def run_stage(
        self, case: DiagnosisRuntimeState, tools: DiagnosisTools, budget: RunBudget,
    ) -> StageDecision: ...


class DiagnosisRuntime(Protocol):
    """Application entry point independent of LangGraph."""

    async def run(self, request: DiagnosisRunRequest) -> RunReport: ...
