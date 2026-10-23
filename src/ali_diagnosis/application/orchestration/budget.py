"""One budget shared across stages, inner agent loops, and tool attempts."""

from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from pydantic import Field

from ali_diagnosis.domain.common import ContractModel
from .errors import FinalAssessmentRequired, ResourceLimitError

if TYPE_CHECKING:
    from .state import DiagnosisRuntimeState


class RunLimits(ContractModel):
    max_stage_visits: int = Field(default=16, ge=1, le=100)
    max_model_calls: int = Field(default=32, ge=1, le=200)
    max_tool_calls: int = Field(default=24, ge=1, le=200)
    max_provider_retries: int = Field(default=1, ge=0, le=3)
    max_decision_retries: int = Field(default=2, ge=0, le=5)
    final_assessment_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    max_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    max_input_tokens: int = Field(default=32000, ge=100)
    max_output_tokens: int = Field(default=4096, ge=64)
    max_cost_usd: float = Field(default=1, gt=0, allow_inf_nan=False)
    # Explicit deployment prices, not a claim about any provider's current tariff.
    input_usd_per_million: float = Field(gt=0, allow_inf_nan=False)
    output_usd_per_million: float = Field(gt=0, allow_inf_nan=False)


@dataclass
class RunBudget:
    limits: RunLimits
    started: float = field(default_factory=monotonic)
    model_calls: int = 0
    tool_calls: int = 0
    reserved_cost_usd: float = 0

    def model_cost(self, input_tokens: int) -> float:
        return (input_tokens * self.limits.input_usd_per_million
                + self.limits.max_output_tokens * self.limits.output_usd_per_million) / 1_000_000

    def remaining_resources(self, stage_visits: int) -> dict[str, int | float]:
        return {
            "remaining_model_calls": max(0, self.limits.max_model_calls - self.model_calls),
            "remaining_tool_calls": max(0, self.limits.max_tool_calls - self.tool_calls),
            "remaining_stage_visits": max(0, self.limits.max_stage_visits - stage_visits),
            "remaining_execution_seconds": self.remaining_seconds(),
            "remaining_estimated_cost_usd": max(0, self.limits.max_cost_usd - self.reserved_cost_usd),
        }

    def completion_steps(self, case: "DiagnosisRuntimeState") -> int:
        """Lower bound for a fully validated diagnosis, not a required route."""
        if case.current_stage != "validation":
            return {"what": 4, "why": 3, "synthesis": 2}[case.current_stage]
        if case.synthesis_candidate is not None:
            return 1
        if case.why_complete and case.why_hypotheses:
            return 3  # validation refinement, synthesis, validation
        return 4 if case.what_complete and case.what_findings else 5

    def finalization_pressure(self, case: "DiagnosisRuntimeState") -> str | None:
        resources = self.remaining_resources(case.stage_visits)
        steps = self.completion_steps(case)
        if case.current_stage == "validation" and (
            resources["remaining_stage_visits"] == 1 or resources["remaining_model_calls"] == 1
        ):
            return "last assessment slot reserved for validation"
        if resources["remaining_stage_visits"] < steps:
            return "stage visit budget cannot cover the remaining diagnostic stages"
        if resources["remaining_model_calls"] < steps:
            return "model call budget cannot cover the remaining diagnostic stages"
        # Reserve a conservative full input/output envelope for each remaining
        # stage. Real costs may be lower; this is planning, not measured billing.
        if resources["remaining_estimated_cost_usd"] + 1e-12 < steps * self.model_cost(self.limits.max_input_tokens):
            return "estimated monetary budget cannot cover the remaining diagnostic stages"
        if resources["remaining_execution_seconds"] <= self.limits.final_assessment_seconds:
            return "execution time reserved for a final assessment"
        return None

    def prioritize_existing_evidence(self, case: "DiagnosisRuntimeState") -> bool:
        resources = self.remaining_resources(case.stage_visits)
        steps = self.completion_steps(case)
        return bool(case.finalization_reason or self.finalization_pressure(case)
                    or resources["remaining_model_calls"] <= steps + 1
                    or resources["remaining_stage_visits"] <= steps + 1
                    or resources["remaining_tool_calls"] <= 1
                    or resources["remaining_execution_seconds"] <= 2 * self.limits.final_assessment_seconds
                    or resources["remaining_estimated_cost_usd"] <= (steps + 1) * self.model_cost(self.limits.max_input_tokens))

    def check_final_assessment(self, case: "DiagnosisRuntimeState") -> None:
        """Never manufacture uncertainty without evidence or an assessment slot."""
        self.remaining_seconds()
        if case.subject_ref is None or not case.artifacts:
            raise ResourceLimitError("Resource-limited finalization requires retrieved evidence")
        if case.stage_visits >= self.limits.max_stage_visits:
            raise ResourceLimitError("Diagnostic stage iteration limit exceeded")
        if self.model_calls >= self.limits.max_model_calls:
            raise ResourceLimitError("Model call limit leaves no final assessment")
        if self.reserved_cost_usd >= self.limits.max_cost_usd:
            raise ResourceLimitError("Model cost reservation limit leaves no final assessment")

    def check_progress(self, case: "DiagnosisRuntimeState") -> None:
        """Called before every inner model attempt, including correction/retry calls."""
        pressure = self.finalization_pressure(case)
        if pressure and not case.finalization_reason and case.artifacts and case.subject_ref is not None:
            self.check_final_assessment(case)
            raise FinalAssessmentRequired(pressure)

    def call_seconds(self, case: "DiagnosisRuntimeState") -> float:
        remaining = self.remaining_seconds()
        if case.finalization_reason or (case.current_stage == "validation" and case.synthesis_candidate is not None):
            return remaining
        # Before evidence exists a timeout cannot yield a legitimate outcome.
        if case.artifacts and case.subject_ref is not None:
            available = remaining - self.limits.final_assessment_seconds
            if available <= 0:
                raise FinalAssessmentRequired("execution time reserved for a final assessment")
            return available
        return remaining

    def remaining_seconds(self) -> float:
        remaining = self.limits.max_seconds - (monotonic() - self.started)
        if remaining <= 0:
            raise ResourceLimitError("Diagnosis execution deadline exceeded")
        return remaining

    def reserve_model(self, input_tokens: int) -> None:
        self.remaining_seconds()
        if input_tokens > self.limits.max_input_tokens:
            raise ResourceLimitError("Model input limit exceeded")
        if self.model_calls >= self.limits.max_model_calls:
            raise ResourceLimitError("Model call limit exceeded")
        cost = self.model_cost(input_tokens)
        if self.reserved_cost_usd + cost > self.limits.max_cost_usd:
            raise ResourceLimitError("Model cost reservation limit exceeded")
        # Charge reservations even for failed requests: billing may be unknown.
        self.reserved_cost_usd += cost
        self.model_calls += 1

    def reserve_tool(self, case: "DiagnosisRuntimeState | None" = None) -> None:
        self.remaining_seconds()
        if self.tool_calls >= self.limits.max_tool_calls:
            if case is not None and case.artifacts and case.subject_ref is not None and not case.finalization_reason:
                raise FinalAssessmentRequired("Tool call limit requires assessment of existing evidence")
            raise ResourceLimitError("Tool call limit exceeded")
        self.tool_calls += 1
