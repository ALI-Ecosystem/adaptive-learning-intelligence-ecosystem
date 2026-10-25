"""Shared execution lifecycle for four separately named diagnostic graph nodes."""

from collections.abc import Callable
import asyncio
from copy import deepcopy
from typing import Any

from ali_diagnosis.application.orchestration.budget import RunBudget
from ali_diagnosis.application.orchestration.contracts import Stage, StageAgent
from ali_diagnosis.application.orchestration.errors import (
    FinalAssessmentRequired, InvalidDecisionError, ResourceLimitError,
)
from ali_diagnosis.application.orchestration.policy import apply_decision
from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application.orchestration.tools import DiagnosisTools


async def execute_stage(
    state: DiagnosisRuntimeState, *, stage: Stage, agent: StageAgent,
    make_tools: Callable[[DiagnosisRuntimeState], DiagnosisTools], budget: RunBudget,
) -> dict[str, Any]:
    """Use graph-owned input; publish a detached update only after validation.

    All goals share this lifecycle. Their prompts, output schemas and decision
    handling are stage-specific. No goal gets a hardcoded tool or next-stage choice.
    """
    if state.final_result is not None or state.current_stage != stage:
        raise InvalidDecisionError("Graph node does not match the active diagnostic goal")
    if state.stage_visits >= budget.limits.max_stage_visits:
        raise ResourceLimitError("Diagnostic stage iteration limit exceeded")
    budget.remaining_seconds()
    working = deepcopy(state)

    def handover(reason: str) -> dict[str, Any]:
        if working.subject_ref is None or not working.artifacts:
            raise ResourceLimitError(f"{reason}; cannot finalize without retrieved evidence")
        budget.check_final_assessment(working)
        working.current_stage = "validation"
        working.finalization_reason = reason
        working.decision_feedback = None
        return vars(working).copy()

    pressure = budget.finalization_pressure(working)
    if pressure and not working.finalization_reason and working.artifacts and working.subject_ref is not None:
        return handover(pressure)
    tools = make_tools(working)
    for attempt in range(budget.limits.max_decision_retries + 1):
        try:
            budget.check_progress(working)
            async with asyncio.timeout(budget.call_seconds(working)):
                decision = await agent.run_stage(working, tools, budget)
            budget.remaining_seconds()
        except FinalAssessmentRequired as exc:
            if working.finalization_reason:
                raise ResourceLimitError(str(exc)) from None
            return handover(str(exc))
        except TimeoutError:
            if working.finalization_reason:
                raise ResourceLimitError("Diagnosis execution deadline exceeded") from None
            return handover("investigation time reserved for a final assessment")

        # Successful tool state survives a rejected proposal. Policy mutations
        # are transactional even if a future guard fails after partial updates.
        proposed = deepcopy(working)
        try:
            apply_decision(proposed, decision)
        except InvalidDecisionError as exc:
            if attempt == budget.limits.max_decision_retries:
                raise InvalidDecisionError(f"Decision correction limit exceeded: {exc}") from None
            working.decision_feedback = (
                f"Decision rejected: {exc}. Revise the {working.current_stage} decision; "
                "retrieved evidence is retained. Follow the stage prerequisites and current claims."
            )
            continue
        proposed.decision_feedback = None
        # Keep domain models intact; dataclasses.asdict would convert them.
        return vars(proposed).copy()
    raise AssertionError("Unreachable correction loop")
