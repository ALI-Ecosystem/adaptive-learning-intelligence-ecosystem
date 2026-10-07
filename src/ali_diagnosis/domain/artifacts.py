"""Diagnostic artifacts and producer provenance."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import DIAGNOSIS_SCHEMA_VERSION, ContractModel, NonEmptyStr, SchemaVersion
from .sources import DiagnosticSourceReference, SubjectReference


class DiagnosticArtifactType(StrEnum):
    """Classifies a diagnosis artifact as information or capability output."""

    INFORMATION_RESULT = "information_result"
    CAPABILITY_RESULT = "capability_result"


class DiagnosticArtifact(ContractModel):
    """Structured tool/information result preserved for diagnosis traceability.

    Stores request and result data with producer provenance, subject, source
    references, and creation time for a diagnosis run.
    """

    artifact_id: NonEmptyStr
    diagnosis_run_id: NonEmptyStr
    subject_ref: SubjectReference
    artifact_type: DiagnosticArtifactType
    producer: NonEmptyStr
    request: dict[str, Any]
    result: dict[str, Any]
    source_references: list[DiagnosticSourceReference] = Field(default_factory=list)
    created_at: datetime
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION
