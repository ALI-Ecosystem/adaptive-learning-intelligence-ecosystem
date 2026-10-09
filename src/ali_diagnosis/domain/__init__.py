"""Public domain-contract surface for the ALI Diagnosis Engine."""

from .artifacts import (
    DiagnosticArtifact,
    DiagnosticArtifactType,
)
from .capabilities import CapabilityMetadata
from .common import DIAGNOSIS_SCHEMA_VERSION
from .diagnosis import (
    DiagnosticFinding,
    DiagnosisRunResult,
    NoLearningProblemDiagnosis,
    RootCauseHypothesis,
    StructuredDiagnosis,
    UnresolvedDiagnosis,
    UnresolvedScope,
)
from .request import DiagnosisRunRequest
from .sources import (
    DiagnosticSourceKind,
    DiagnosticSourceReference,
    SubjectReference,
)

__all__ = [
    "CapabilityMetadata",
    "DIAGNOSIS_SCHEMA_VERSION",
    "DiagnosticArtifact",
    "DiagnosticArtifactType",
    "DiagnosticFinding",
    "DiagnosticSourceKind",
    "DiagnosticSourceReference",
    "DiagnosisRunRequest",
    "DiagnosisRunResult",
    "NoLearningProblemDiagnosis",
    "RootCauseHypothesis",
    "StructuredDiagnosis",
    "SubjectReference",
    "UnresolvedDiagnosis",
    "UnresolvedScope",
]
