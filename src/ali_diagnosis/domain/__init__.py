"""Public domain-contract surface for the ALI Diagnosis Engine."""

from .contracts import (
    DIAGNOSIS_SCHEMA_VERSION,
    DiagnosticArtifact,
    DiagnosticArtifactType,
    DiagnosticFinding,
    DiagnosticProducer,
    DiagnosticProducerType,
    DiagnosticSourceKind,
    DiagnosticSourceReference,
    DiagnosisRunRequest,
    DiagnosisRunResult,
    RootCauseHypothesis,
    StructuredDiagnosis,
    SubjectReference,
    UnresolvedDiagnosis,
    UnresolvedScope,
)

__all__ = [
    "DIAGNOSIS_SCHEMA_VERSION",
    "DiagnosticArtifact",
    "DiagnosticArtifactType",
    "DiagnosticFinding",
    "DiagnosticProducer",
    "DiagnosticProducerType",
    "DiagnosticSourceKind",
    "DiagnosticSourceReference",
    "DiagnosisRunRequest",
    "DiagnosisRunResult",
    "RootCauseHypothesis",
    "StructuredDiagnosis",
    "SubjectReference",
    "UnresolvedDiagnosis",
    "UnresolvedScope",
]
