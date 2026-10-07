"""Findings, root causes, and diagnosis outcomes."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from .common import (
    DIAGNOSIS_SCHEMA_VERSION,
    Confidence,
    ContractModel,
    NonEmptyStr,
    SchemaVersion,
)
from .sources import DiagnosticSourceReference, SubjectReference


class DiagnosticFinding(ContractModel):
    """A WHAT finding: a learner problem identified by Diagnosis.

    Records the subject, problem statement, confidence, and supporting or
    contradicting sources.
    """

    finding_id: NonEmptyStr
    subject_ref: SubjectReference
    problem_statement: NonEmptyStr
    confidence: Confidence
    supporting_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    contradicting_sources: list[DiagnosticSourceReference] = Field(default_factory=list)


class RootCauseHypothesis(ContractModel):
    """A WHY hypothesis that explains one or more WHAT findings.

    Links a proposed cause to finding IDs, with confidence and supporting or
    contradicting sources.
    """

    hypothesis_id: NonEmptyStr
    hypothesis_statement: NonEmptyStr
    confidence: Confidence
    explains_finding_ids: list[NonEmptyStr] = Field(min_length=1)
    supporting_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    contradicting_sources: list[DiagnosticSourceReference] = Field(default_factory=list)


class StructuredDiagnosis(ContractModel):
    """Official completed diagnosis containing both WHAT and WHY.

    Associates a learner and subject with findings and root-cause hypotheses;
    every finding must be explained by at least one hypothesis.
    """

    status: Literal["completed"] = "completed"
    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    subject_ref: SubjectReference
    what: list[DiagnosticFinding] = Field(min_length=1)
    why: list[RootCauseHypothesis] = Field(min_length=1)
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION

    @model_validator(mode="after")
    def validate_what_why_relationships(self) -> StructuredDiagnosis:
        """Return this diagnosis after checking unique IDs and complete WHY links."""
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
    """Valid diagnostic outcome when a reliable WHAT and/or WHY cannot be established.

    Records the learner, subject, unresolved scope, reason, and relevant sources
    so the engine can report uncertainty explicitly.
    """

    status: Literal["unresolved"] = "unresolved"
    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    subject_ref: SubjectReference
    unresolved_scope: UnresolvedScope
    reason: NonEmptyStr
    relevant_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION


class NoLearningProblemDiagnosis(ContractModel):
    """Completed analysis that found no meaningful learning problem.

    Records the learner, subject, conclusion reason, and relevant sources for
    cases such as an isolated mistake or temporary confusion.
    """

    status: Literal["no_learning_problem"] = "no_learning_problem"
    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    subject_ref: SubjectReference
    reason: NonEmptyStr
    relevant_sources: list[DiagnosticSourceReference] = Field(min_length=1)
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION


DiagnosisRunResult: TypeAlias = Annotated[
    StructuredDiagnosis | UnresolvedDiagnosis | NoLearningProblemDiagnosis,
    Field(discriminator="status"),
]
"""Completed, unresolved, or no-learning-problem outcome selected by its status."""
