"""Request contract for starting a diagnosis run."""

from __future__ import annotations

from .common import DIAGNOSIS_SCHEMA_VERSION, ContractModel, NonEmptyStr, SchemaVersion


class DiagnosisRunRequest(ContractModel):
    """Minimal request used by the application layer to start diagnosis.

    Identifies the diagnosis run, learner, and evidence to examine.
    """

    diagnosis_run_id: NonEmptyStr
    learner_id: NonEmptyStr
    evidence_id: NonEmptyStr
    schema_version: SchemaVersion = DIAGNOSIS_SCHEMA_VERSION
