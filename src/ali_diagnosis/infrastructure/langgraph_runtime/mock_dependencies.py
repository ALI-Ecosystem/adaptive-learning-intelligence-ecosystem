"""Deterministic dependencies for the SCRUM-11 orchestration proof only."""

from typing import Any

from ali_diagnosis.domain import (
    CapabilityMetadata,
    DiagnosisRunRequest,
    DiagnosticFinding,
    DiagnosticSourceKind,
    DiagnosticSourceReference,
)


class MockInformationSource:
    """Supply synthetic context through the existing information-source boundary."""

    def get_information(self, request: DiagnosisRunRequest) -> dict[str, Any]:
        """Return explicitly synthetic subject/context data for this run."""
        return {
            "is_mock": True,
            "source_id": f"{request.diagnosis_run_id}:mock-context",
            "subject_ref": {"taxonomy_id": "mock-concept"},
            "source_references": [
                DiagnosticSourceReference(
                    source_kind=DiagnosticSourceKind.EVIDENCE,
                    source_id=request.evidence_id,
                )
            ],
        }


class MockDiagnosisCapability:
    """Metadata-bearing test instrument with its own concrete invocation API."""

    metadata = CapabilityMetadata(
        name="mock-diagnosis-instrument",
        purpose="Prove runtime capability invocation only.",
        supported_evidence=("Synthetic test findings",),
        required_context=(),
        applicability="SCRUM-11 deterministic runtime proof only.",
        input_contract="DiagnosisRunRequest, current DiagnosticFinding list, iteration.",
        output_contract="Temporary dictionary containing synthetic result and provenance.",
        limitations="Not a real measurement or educational diagnosis.",
        confidence_uncertainty_semantics="Fixed synthetic value; no reliability claim.",
        research_basis="Mock only; no research-backed capability is implemented.",
        implementation_version="mock-v1",
    )

    def analyze(
        self,
        request: DiagnosisRunRequest,
        findings: list[DiagnosticFinding],
        *,
        iteration: int,
    ) -> dict[str, Any]:
        """Return an identifiable synthetic result without diagnostic computation."""
        return {
            "is_mock": True,
            "source_id": f"{request.diagnosis_run_id}:mock-capability:{iteration}",
            "producer": self.metadata.name,
            "implementation_version": self.metadata.implementation_version,
            "finding_ids": [finding.finding_id for finding in findings],
            "measurement": 0.5,
            "source_references": [
                DiagnosticSourceReference(
                    source_kind=DiagnosticSourceKind.EVIDENCE,
                    source_id=request.evidence_id,
                )
            ],
        }
