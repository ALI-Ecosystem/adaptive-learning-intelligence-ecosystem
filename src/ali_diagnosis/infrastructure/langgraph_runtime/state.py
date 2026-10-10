"""Temporary case state for one Diagnosis Orchestrator run."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ali_diagnosis.domain import (
    DiagnosisRunRequest,
    DiagnosisRunResult,
    DiagnosticFinding,
    RootCauseHypothesis,
    SubjectReference,
)


@dataclass
class DiagnosticSnapshot:
    """Capture conclusions from one completed diagnostic iteration/refinement loop.

    Include WHAT findings, WHY hypotheses, newly used information/capability
    results, synthesis candidate, and validation result. Never include prompts,
    chain-of-thought, hidden reasoning, or raw agent traces. Copy payloads on
    creation to detach them from mutable working state.
    """

    current_stage: str | None
    iteration_count: int
    loop_count: int
    what_findings: list[DiagnosticFinding] = field(default_factory=list)
    why_hypotheses: list[RootCauseHypothesis] = field(default_factory=list)
    new_information: dict[str, Any] = field(default_factory=dict)
    new_capability_results: list[dict[str, Any]] = field(default_factory=list)
    synthesis_candidate: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Detach nested snapshot data from the supplied live case values."""
        self.what_findings = deepcopy(self.what_findings)
        self.why_hypotheses = deepcopy(self.why_hypotheses)
        self.new_information = deepcopy(self.new_information)
        self.new_capability_results = deepcopy(self.new_capability_results)
        self.synthesis_candidate = deepcopy(self.synthesis_candidate)
        self.validation_result = deepcopy(self.validation_result)


@dataclass
class DiagnosisRuntimeState:
    """Hold the current diagnostic picture in memory for a single run.

    Replace current findings, hypotheses, synthesis, and validation as the case
    evolves; do not retain reasoning attempts or hidden chain-of-thought.
    Findings and hypotheses carry their supporting and contradicting sources.
    History holds one structured snapshot per completed diagnostic iteration /
    refinement loop, not a log after every graph node. It excludes prompts,
    chain-of-thought, hidden reasoning, and raw agent traces.
    Result dictionaries remain provisional until their contracts are defined.
    This state is discarded after the run and is not a persistence contract.
    """

    request: DiagnosisRunRequest
    subject_ref: SubjectReference | None = None
    what_findings: list[DiagnosticFinding] = field(default_factory=list)
    why_hypotheses: list[RootCauseHypothesis] = field(default_factory=list)
    retrieved_information: dict[str, Any] = field(default_factory=dict)
    capability_results: list[dict[str, Any]] = field(default_factory=list)
    synthesis_candidate: dict[str, Any] | None = None
    latest_validation_result: dict[str, Any] | None = None
    final_result: DiagnosisRunResult | None = None
    diagnostic_history: list[DiagnosticSnapshot] = field(default_factory=list)
    current_stage: str | None = None
    iteration_count: int = 0
    loop_count: int = 0
