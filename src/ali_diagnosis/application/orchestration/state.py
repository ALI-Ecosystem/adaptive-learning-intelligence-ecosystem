"""One temporary run state, evolved from the SCRUM-11 graph state."""

from dataclasses import dataclass, field

from ali_diagnosis.domain import (
    DiagnosisRunRequest, DiagnosisRunResult, DiagnosticArtifact, DiagnosticFinding,
    RootCauseHypothesis, StructuredDiagnosis, SubjectReference,
)
from .contracts import Stage, ValidationDecision


@dataclass
class DiagnosisRuntimeState:
    """Current diagnostic picture shared by every goal, independent of LangGraph.

    Artifacts replace the proof's untyped information/capability payload stores.
    current_stage identifies the next goal to execute (validation on completion).
    iteration_count counts completed validation assessments; loop_count counts
    validation-requested refinements. stage_visits bounds all adaptive navigation,
    including loops that do not reach validation. No reasoning history is stored.
    """

    request: DiagnosisRunRequest
    subject_ref: SubjectReference | None = None
    what_findings: list[DiagnosticFinding] = field(default_factory=list)
    why_hypotheses: list[RootCauseHypothesis] = field(default_factory=list)
    artifacts: dict[str, DiagnosticArtifact] = field(default_factory=dict)
    synthesis_candidate: StructuredDiagnosis | None = None
    latest_validation_result: ValidationDecision | None = None
    final_result: DiagnosisRunResult | None = None
    current_stage: Stage = "what"
    # An empty investigation is valid; claim lists cannot prove stage completion.
    what_complete: bool = False
    why_complete: bool = False
    iteration_count: int = 0
    loop_count: int = 0
    stage_visits: int = 0
    tool_failures: set[str] = field(default_factory=set)
    decision_feedback: str | None = None
    finalization_reason: str | None = None
