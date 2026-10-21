"""Mock WHAT stage behavior."""

from typing import Any

from ali_diagnosis.application import InformationGateway
from ali_diagnosis.domain import (
    DiagnosticFinding,
    DiagnosticSourceKind,
    DiagnosticSourceReference,
    SubjectReference,
)

from ..state import DiagnosisRuntimeState


def what(
    state: DiagnosisRuntimeState, *, information_gateway: InformationGateway
) -> dict[str, Any]:
    """Retrieve synthetic context and replace the current mock WHAT picture."""
    information = information_gateway.get_information(state.request)
    context = information["mock"]
    subject = SubjectReference.model_validate(context["subject_ref"])
    finding = DiagnosticFinding(
        finding_id="mock-finding",
        subject_ref=subject,
        problem_statement="Mock learning problem; orchestration proof only.",
        confidence=0.5,
        supporting_sources=[
            DiagnosticSourceReference(
                source_kind=DiagnosticSourceKind.EVIDENCE,
                source_id=state.request.evidence_id,
            ),
            DiagnosticSourceReference(
                source_kind=DiagnosticSourceKind.CONTEXT,
                source_id=context["source_id"],
            ),
        ],
    )
    return {
        "current_stage": "what",
        "subject_ref": subject,
        "retrieved_information": {**state.retrieved_information, **information},
        "what_findings": [finding],
    }
