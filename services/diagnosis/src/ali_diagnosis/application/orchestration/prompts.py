"""Versioned stage prompts assembled independently of provider and runtime."""

import json
from importlib.resources import files

from .state import DiagnosisRuntimeState
from .tools import DiagnosisTools

PROMPT_VERSION = "v1"


def stage_prompt(case: DiagnosisRuntimeState) -> str:
    root = files("ali_diagnosis.application.orchestration").joinpath("prompts", PROMPT_VERSION)
    return (root.joinpath("common.md").read_text(encoding="utf-8") + "\n\n"
            + root.joinpath(f"{case.current_stage}.md").read_text(encoding="utf-8"))


def stage_context(case: DiagnosisRuntimeState, tools: DiagnosisTools) -> str:
    """Pass current public case data, never previous agent conversations."""
    return json.dumps({
        "current_stage": case.current_stage,
        "what_complete": case.what_complete,
        "why_complete": case.why_complete,
        "decision_feedback": case.decision_feedback,
        "finalization_reason": case.finalization_reason,
        "request": case.request.model_dump(mode="json"),
        "subject": case.subject_ref.model_dump(mode="json") if case.subject_ref else None,
        "current_findings": [f.model_dump(mode="json") for f in case.what_findings],
        "current_hypotheses": [h.model_dump(mode="json") for h in case.why_hypotheses],
        "artifacts": [a.model_dump(mode="json") for a in case.artifacts.values()],
        "candidate": case.synthesis_candidate.model_dump(mode="json") if case.synthesis_candidate else None,
        "latest_validation": case.latest_validation_result.model_dump(mode="json") if case.latest_validation_result else None,
        "available_sources": tools.describe_sources(),
        "stage_visits": case.stage_visits,
        **tools.budget.remaining_resources(case.stage_visits),
        "minimum_completion_stages": tools.budget.completion_steps(case),
        "budget_pressure": tools.budget.finalization_pressure(case),
        "prioritize_existing_evidence": tools.budget.prioritize_existing_evidence(case),
        "technical_failures": sorted(tools.case.tool_failures),
    }, ensure_ascii=False)
