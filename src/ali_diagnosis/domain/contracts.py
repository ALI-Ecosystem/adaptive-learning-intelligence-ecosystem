"""Runtime-independent domain contracts for the ALI Diagnosis Engine."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

DIAGNOSIS_SCHEMA_VERSION: Final = "0.1"

SchemaVersion: TypeAlias = Literal["0.1"]
NonEmptyStr: TypeAlias = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
Confidence: TypeAlias = Annotated[float, Field(ge=0.0, le=1.0)]


class ContractModel(BaseModel):
    """Base model for stable domain contracts.

    Contracts reject unknown fields and are immutable at the top level so that
    runtime-specific concerns cannot silently leak into persisted domain data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class DiagnosisRunRequest(ContractModel):
    """Minimal request used by the application layer to start diagnosis."""

    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    evidence_id: NonEmptyStr
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION


class SubjectReference(ContractModel):
    """Reference to the existing ALI content taxonomy."""

    taxonomy_id: NonEmptyStr
    taxonomy_level: NonEmptyStr | None = None


class DiagnosticSourceKind(StrEnum):
    """Source families that may support or contradict a diagnosis."""

    EVIDENCE = "evidence"
    CONTEXT = "context"
    CAPABILITY_RESULT = "capability_result"


class DiagnosticSourceReference(ContractModel):
    """Stable reference to evidence, retrieved context, or a capability result."""

    source_kind: DiagnosticSourceKind
    source_id: NonEmptyStr


class DiagnosticArtifactType(StrEnum):
    """Kinds of structured results created or captured during a diagnosis run."""

    INFORMATION_RESULT = "information_result"
    CAPABILITY_RESULT = "capability_result"


class DiagnosticProducerType(StrEnum):
    """Kinds of producers that can create a diagnostic artifact."""

    INFORMATION_SOURCE = "information_source"
    CAPABILITY = "capability"


class DiagnosticProducer(ContractModel):
    """Provenance for the tool, information source, or capability that produced a result."""

    type: DiagnosticProducerType
    name: NonEmptyStr
    version: NonEmptyStr | None = None


class DiagnosticArtifact(ContractModel):
    """Structured tool/information result preserved for diagnosis traceability."""

    artifact_id: NonEmptyStr
    diagnosis_run_id: NonEmptyStr
    subject_ref: SubjectReference
    artifact_type: DiagnosticArtifactType
    producer: DiagnosticProducer
    request: dict[str, Any]
    result: dict[str, Any]
    source_references: list[DiagnosticSourceReference] = Field(default_factory=list)
    created_at: datetime
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION


class DiagnosticFinding(ContractModel):
    """A WHAT finding: a learner problem identified by Diagnosis."""

    finding_id: NonEmptyStr
    subject_ref: SubjectReference
    problem_statement: NonEmptyStr
    confidence: Confidence
    supporting_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    contradicting_sources: list[DiagnosticSourceReference] = Field(default_factory=list)


class RootCauseHypothesis(ContractModel):
    """A WHY hypothesis that explains one or more WHAT findings."""

    hypothesis_id: NonEmptyStr
    hypothesis_statement: NonEmptyStr
    confidence: Confidence
    explains_finding_ids: list[NonEmptyStr] = Field(min_length=1)
    supporting_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    contradicting_sources: list[DiagnosticSourceReference] = Field(default_factory=list)


class StructuredDiagnosis(ContractModel):
    """Official completed diagnosis containing both WHAT and WHY."""

    status: Literal["completed"] = "completed"
    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    subject_ref: SubjectReference
    what: list[DiagnosticFinding] = Field(min_length=1)
    why: list[RootCauseHypothesis] = Field(min_length=1)
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION

    @model_validator(mode="after")
    def validate_what_why_relationships(self) -> StructuredDiagnosis:
        finding_ids = [finding.finding_id for finding in self.what]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("WHAT finding_id values must be unique")

        hypothesis_ids = [hypothesis.hypothesis_id for hypothesis in self.why]
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError("WHY hypothesis_id values must be unique")

        known_findings = set(finding_ids)
        explained_findings: set[str] = set()

        for hypothesis in self.why:
            unknown = set(hypothesis.explains_finding_ids) - known_findings
            if unknown:
                unknown_ids = ", ".join(sorted(unknown))
                raise ValueError(f"WHY references unknown WHAT finding(s): {unknown_ids}")
            explained_findings.update(hypothesis.explains_finding_ids)

        unexplained = known_findings - explained_findings
        if unexplained:
            unexplained_ids = ", ".join(sorted(unexplained))
            raise ValueError(f"Completed diagnosis has WHAT without WHY: {unexplained_ids}")

        return self


class UnresolvedScope(StrEnum):
    """Which part of the diagnosis could not be determined reliably."""

    WHAT = "what"
    WHY = "why"
    BOTH = "both"


class UnresolvedDiagnosis(ContractModel):
    """Valid diagnostic outcome when a reliable WHAT and/or WHY cannot be established."""

    status: Literal["unresolved"] = "unresolved"
    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    subject_ref: SubjectReference
    unresolved_scope: UnresolvedScope
    reason: NonEmptyStr
    relevant_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION


DiagnosisRunResult: TypeAlias = Annotated[
    StructuredDiagnosis | UnresolvedDiagnosis,
    Field(discriminator="status"),
]
