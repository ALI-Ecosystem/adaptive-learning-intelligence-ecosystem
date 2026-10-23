"""Controlled synthetic fixtures for runtime integration, not educational validation."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from ali_diagnosis.application.orchestration.state import DiagnosisRuntimeState
from ali_diagnosis.application import CapabilityRegistry, InformationGateway
from ali_diagnosis.application.orchestration.budget import RunLimits
from ali_diagnosis.application.orchestration.contracts import StageAgent
from ali_diagnosis.application.orchestration.tools import CapabilityBinding, InformationBinding
from ali_diagnosis.domain import (
    CapabilityMetadata, DiagnosisRunRequest, DiagnosticArtifact, DiagnosticArtifactType,
    DiagnosticSourceKind, DiagnosticSourceReference, SubjectReference,
)
from ali_diagnosis.domain.common import ContractModel, NonEmptyStr, Confidence
from ali_diagnosis.infrastructure.langgraph_runtime.runtime import LangGraphDiagnosisRuntime

SCENARIOS = ("success", "insufficient", "contradictory", "additional_information",
             "capability_selection", "refinement", "tool_failure", "iteration_limit")


class SyntheticSource:
    """Implements the existing source contract with arbitrary fixture dictionaries."""

    def __init__(self, payload: dict, *, fail: bool = False) -> None:
        self.payload, self.fail = payload, fail

    def get_information(self, request: DiagnosisRunRequest) -> dict:
        if self.fail:
            raise RuntimeError("Synthetic source failure")
        return deepcopy(self.payload)


class MockTracingInput(ContractModel):
    artifact_id: NonEmptyStr


class MockTracingOutput(ContractModel):
    is_synthetic: Literal[True] = True
    repeated_error_signal: Confidence
    limitation: str = "Controlled fixture, not a trained model or validated diagnosis."


class SyntheticTracingCapability:
    metadata = CapabilityMetadata(
        name="synthetic-response-tracing", purpose="Measure a controlled repeated-response fixture signal.",
        supported_evidence=("synthetic structured attempts",), required_context=(),
        applicability="Only retrieved synthetic evidence with at least three structured attempts.",
        input_contract="MockTracingInput: retrieved artifact_id; reads observations from that artifact.",
        output_contract="MockTracingOutput: synthetic signal and limitation.",
        limitations="Not proof of mastery or a root cause; not a real trained tracing model.",
        confidence_uncertainty_semantics="Predetermined fixture value, not calibrated confidence.",
        research_basis="Test double for Knowledge / Response Tracing; no scientific claim.",
        implementation_version="synthetic-v1",
    )

    @staticmethod
    def applicable(inputs: MockTracingInput, case: DiagnosisRuntimeState) -> bool:
        artifact = case.artifacts.get(inputs.artifact_id)
        return bool(artifact and artifact.result.get("is_synthetic") is True
                    and len(artifact.result.get("attempts", [])) >= 3)

    @staticmethod
    async def execute(inputs: MockTracingInput, case: DiagnosisRuntimeState) -> MockTracingOutput:
        return MockTracingOutput(repeated_error_signal=0.8)


def synthetic_runtime(agent: StageAgent, limits: RunLimits, scenario: str) -> LangGraphDiagnosisRuntime:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown synthetic scenario")
    subject = SubjectReference(taxonomy_id="synthetic:fraction-addition", taxonomy_level="concept")
    evidence = {
        "is_synthetic": True,
        "subject": subject.model_dump(mode="json"),
        "attempts": [
            {"question": "1/2 + 1/3", "response": "2/5", "correct": False},
            {"question": "1/4 + 1/3", "response": "2/7", "correct": False},
            {"question": "2/3 + 1/5", "response": "3/8", "correct": False},
        ],
        "learner_explanation": "I add the numerators and add the denominators separately.",
        "rubric": "Equivalent fractions need a common denominator before adding numerators.",
    }
    history = {"is_synthetic": True, "observation":
               "Independent earlier answers and learner explanation repeat separate addition of denominators."}
    if scenario == "insufficient":
        evidence.update(attempts=[], learner_explanation="No response or prior attempts recorded.")
        history["observation"] = "No further evidence is available."
    if scenario == "contradictory":
        evidence["learner_explanation"] = "No explanation captured; the assessment importer may have mismatched answers."
        history["observation"] = (
            "Independent verified same-day test: all fraction additions correct, with correct common-denominator "
            "explanations. Whether imported wrong answers belong to this learner is unknown."
        )
    if scenario in ("additional_information", "refinement"):
        evidence["learner_explanation"] = "No explanation captured. Historical context is required to distinguish causes."
    if scenario == "tool_failure":
        evidence.update(attempts=[], learner_explanation="DiagnosisRuntimeState details are unavailable; retrieve history for diagnostic evidence.")

    sources = {"trigger": SyntheticSource(evidence),
               "history": SyntheticSource(history, fail=scenario == "tool_failure")}

    def binding(name: str) -> InformationBinding:
        def to_artifact(request: DiagnosisRunRequest, payload: dict) -> DiagnosticArtifact:
            return DiagnosticArtifact(
                artifact_id=f"{request.diagnosis_run_id}:{name}",
                diagnosis_run_id=request.diagnosis_run_id, subject_ref=subject,
                artifact_type=DiagnosticArtifactType.INFORMATION_RESULT,
                producer=f"synthetic:{name}", request={"evidence_id": request.evidence_id},
                result=payload,
                source_references=[DiagnosticSourceReference(
                    source_kind=DiagnosticSourceKind.EVIDENCE,
                    source_id=request.evidence_id if name == "trigger" else f"{request.evidence_id}:history",
                )], created_at=datetime.now(timezone.utc),
            )
        return InformationBinding(
            description=("Triggering evidence and subject taxonomy." if name == "trigger"
                         else "Independent historical evidence to corroborate or contradict the triggering case."),
            to_artifact=to_artifact,
        )

    capability = SyntheticTracingCapability()
    registry = CapabilityRegistry()
    registry.register(capability)
    return LangGraphDiagnosisRuntime(
        agent=agent, limits=limits, information_gateway=InformationGateway(sources),
        information={name: binding(name) for name in sources}, anchor_source="trigger",
        capability_registry=registry, capabilities={capability.metadata.name: CapabilityBinding(
            input_type=MockTracingInput, output_type=MockTracingOutput,
            applicable=capability.applicable,
            input_sources=lambda inputs, case: case.artifacts[inputs.artifact_id].source_references,
            execute=capability.execute,
        )},
    )
