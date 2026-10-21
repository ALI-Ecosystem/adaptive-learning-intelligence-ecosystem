"""Mock WHY stage behavior."""

from typing import Any

from ali_diagnosis.application import CapabilityRegistry
from ali_diagnosis.domain import (
    DiagnosticSourceKind,
    DiagnosticSourceReference,
    RootCauseHypothesis,
)

from ..mock_dependencies import MockDiagnosisCapability
from ..state import DiagnosisRuntimeState


def why(
    state: DiagnosisRuntimeState, *, capability_registry: CapabilityRegistry
) -> dict[str, Any]:
    """Resolve and invoke the mock instrument, then replace the WHY picture."""
    capability = capability_registry.resolve(MockDiagnosisCapability.metadata.name)
    if not isinstance(capability, MockDiagnosisCapability):
        raise TypeError("Runtime proof requires MockDiagnosisCapability")
    result = capability.analyze(
        state.request, state.what_findings, iteration=state.iteration_count + 1
    )
    hypothesis = RootCauseHypothesis(
        hypothesis_id="mock-hypothesis",
        hypothesis_statement="Mock explanation; orchestration proof only.",
        confidence=0.5,
        explains_finding_ids=[finding.finding_id for finding in state.what_findings],
        supporting_sources=[
            DiagnosticSourceReference(
                source_kind=DiagnosticSourceKind.CAPABILITY_RESULT,
                source_id=result["source_id"],
            )
        ],
    )
    return {
        "current_stage": "why",
        "capability_results": [*state.capability_results, result],
        "why_hypotheses": [hypothesis],
    }
