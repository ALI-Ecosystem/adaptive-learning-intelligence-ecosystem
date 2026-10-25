"""Controlled information and capability access; no provider/runtime imports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from ali_diagnosis.application import CapabilityRegistry, InformationGateway
from ali_diagnosis.domain.common import ContractModel, NonEmptyStr
from ali_diagnosis.domain import (
    DiagnosisRunRequest, DiagnosticArtifact, DiagnosticArtifactType,
    DiagnosticSourceReference, DiagnosticSourceKind,
)
from .budget import RunBudget
from .state import DiagnosisRuntimeState
from .errors import FinalAssessmentRequired, ResourceLimitError, ToolRejectedError


@dataclass(frozen=True)
class InformationBinding:
    """Source-specific mapping to the existing artifact contract, not a source schema."""

    description: str
    to_artifact: Callable[[DiagnosisRunRequest, dict[str, Any]], DiagnosticArtifact]


@dataclass(frozen=True)
class CapabilityBinding:
    """Explicit allowlist adapter around a concrete capability's own contracts."""

    input_type: type[BaseModel]
    output_type: type[BaseModel]
    applicable: Callable[[BaseModel, DiagnosisRuntimeState], bool]
    input_sources: Callable[[BaseModel, DiagnosisRuntimeState], list[DiagnosticSourceReference]]
    execute: Callable[[BaseModel, DiagnosisRuntimeState], Awaitable[BaseModel]]


class _CapabilityArguments(ContractModel):
    name: NonEmptyStr
    inputs: dict[str, Any]
    source_references: list[DiagnosticSourceReference]


def known_sources(case: DiagnosisRuntimeState) -> set[tuple[str, str]]:
    """Only fetched sources and generated artifact identities may support claims."""
    known: set[tuple[str, str]] = set()
    for artifact in case.artifacts.values():
        kind = (DiagnosticSourceKind.CAPABILITY_RESULT
                if artifact.artifact_type == DiagnosticArtifactType.CAPABILITY_RESULT
                else DiagnosticSourceKind.CONTEXT)
        known.add((kind, artifact.artifact_id))
        known.update((ref.source_kind, ref.source_id) for ref in artifact.source_references)
    return known


def check_sources(case: DiagnosisRuntimeState, references: list[DiagnosticSourceReference]) -> None:
    if not references or any(
        (ref.source_kind, ref.source_id) not in known_sources(case) for ref in references
    ):
        raise ToolRejectedError("Source references must identify retrieved evidence or artifacts")


class DiagnosisTools:
    """Stage-local tool access bound to shared run state and the shared run budget."""

    def __init__(
        self, case: DiagnosisRuntimeState, budget: RunBudget, gateway: InformationGateway,
        information: Mapping[str, InformationBinding], anchor_source: str,
        registry: CapabilityRegistry, capabilities: Mapping[str, CapabilityBinding],
    ) -> None:
        if set(information) - set(gateway.list_sources()) or anchor_source not in information:
            raise ValueError("Information bindings and anchor must name configured sources")
        for name in capabilities:
            registry.resolve(name)
        self.case, self.budget, self.gateway = case, budget, gateway
        self.information, self.anchor_source = dict(information), anchor_source
        self.registry, self.capabilities = registry, dict(capabilities)
        self._lock = asyncio.Lock()

    def describe_sources(self) -> list[dict[str, Any]]:
        return [{"name": name, "description": binding.description,
                 "resolves_subject": name == self.anchor_source}
                for name, binding in self.information.items()]

    async def call(self, name: str, arguments: dict[str, Any], *, count_attempt: bool = True) -> dict[str, Any]:
        """Serialize calls so parallel model tool requests cannot race run state."""
        async with self._lock:
            if count_attempt:
                self.budget.reserve_tool(self.case)
            self.budget.remaining_seconds()
            if self.case.finalization_reason:
                return {"error": "final_assessment_only", "message": "Assess existing evidence; no further tools."}
            try:
                # Re-evaluate after each serialized tool: the first result in a
                # batch may have established evidence and made a reserve useful.
                async with asyncio.timeout(self.budget.call_seconds(self.case)):
                    if name == "discover_capabilities":
                        if arguments:
                            raise ToolRejectedError("Discovery takes no arguments")
                        return {"capabilities": [
                            {**metadata.model_dump(mode="json"),
                             "input_schema": self.capabilities[metadata.name].input_type.model_json_schema(),
                             "output_schema": self.capabilities[metadata.name].output_type.model_json_schema()}
                            for metadata in self.registry.list_metadata()
                            if metadata.name in self.capabilities
                        ]}
                    if name == "get_information":
                        return await self._information(arguments)
                    if name == "invoke_capability":
                        return await self._capability(arguments)
                    raise ToolRejectedError("Unknown diagnostic tool")
            except TimeoutError:
                if self.case.artifacts and self.case.subject_ref is not None:
                    raise FinalAssessmentRequired("tool execution time reserved for a final assessment") from None
                raise ResourceLimitError("Tool execution deadline exceeded without retrieved evidence") from None
            except (ToolRejectedError, ValidationError, KeyError):
                return {"error": "invalid_tool_request",
                        "message": "Check tool arguments, configured names, schemas, applicability and source references."}

    async def _information(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"source"} or not isinstance(arguments["source"], str):
            raise ToolRejectedError("Provide one configured source")
        name = arguments["source"]
        binding = self.information[name]
        if self.case.subject_ref is None and name != self.anchor_source:
            raise ToolRejectedError("Retrieve triggering evidence first")
        failure_key = f"information:{name}"
        try:
            # Existing source contract is synchronous. Blocking source adapters must
            # impose their own I/O deadlines; cancellation cannot kill their threads.
            payload = await asyncio.to_thread(
                self.gateway.get_information, self.case.request, source_names=(name,),
            )
            artifact = DiagnosticArtifact.model_validate(
                binding.to_artifact(self.case.request, payload[name]).model_dump()
            )
            if artifact.artifact_type != DiagnosticArtifactType.INFORMATION_RESULT:
                raise ValueError("Expected information artifact")
            if artifact.diagnosis_run_id != self.case.request.diagnosis_run_id:
                raise ValueError("Cross-run artifact")
            if artifact.artifact_id in self.case.artifacts:
                raise ValueError("Duplicate artifact identity")
            if name == self.anchor_source:
                anchor = DiagnosticSourceReference(
                    source_kind=DiagnosticSourceKind.EVIDENCE,
                    source_id=self.case.request.evidence_id,
                )
                if anchor not in artifact.source_references:
                    raise ValueError("Anchor mapper must resolve the triggering evidence")
                if self.case.subject_ref is not None and self.case.subject_ref != artifact.subject_ref:
                    raise ValueError("Anchor subject changed during run")
                self.case.subject_ref = artifact.subject_ref
            self.case.artifacts[artifact.artifact_id] = artifact
            # New evidence invalidates a previously synthesized candidate.
            self.case.synthesis_candidate = None
            self.case.latest_validation_result = None
            self.case.tool_failures.discard(failure_key)
            return {"artifact": artifact.model_dump(mode="json")}
        except Exception:
            self.case.tool_failures.add(failure_key)
            return {"error": "information_unavailable", "source": name}

    async def _capability(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _CapabilityArguments.model_validate(arguments)
        name = args.name
        if self.case.subject_ref is None:
            raise ToolRejectedError("Resolve the case before invoking a capability")
        binding = self.capabilities[name]
        inputs = binding.input_type.model_validate(args.inputs)
        refs = args.source_references
        check_sources(self.case, refs)
        # Adapters see a detached case, so concrete instruments cannot mutate it.
        from copy import deepcopy
        case_view = deepcopy(self.case)
        failure_key = f"capability:{name}"
        try:
            applicable = binding.applicable(inputs, case_view)
            actual_refs = binding.input_sources(inputs, case_view) if applicable else []
        except Exception:
            self.case.tool_failures.add(failure_key)
            return {"error": "capability_failed", "name": name}
        if not applicable:
            return {"error": "capability_not_applicable", "name": name}
        check_sources(self.case, actual_refs)
        if any(ref not in actual_refs for ref in refs):
            raise ToolRejectedError("Declared sources do not match capability inputs")
        try:
            output = await binding.execute(inputs, case_view)
            result = binding.output_type.model_validate(output.model_dump())
            metadata = self.registry.resolve(name).metadata
            artifact = DiagnosticArtifact(
                artifact_id=str(uuid4()), diagnosis_run_id=self.case.request.diagnosis_run_id,
                subject_ref=self.case.subject_ref,
                artifact_type=DiagnosticArtifactType.CAPABILITY_RESULT, producer=name,
                request=inputs.model_dump(mode="json"),
                result={"output": result.model_dump(mode="json"),
                        "implementation_version": metadata.implementation_version},
                source_references=actual_refs, created_at=datetime.now(timezone.utc),
            )
            self.case.artifacts[artifact.artifact_id] = artifact
            self.case.synthesis_candidate = None
            self.case.latest_validation_result = None
            self.case.tool_failures.discard(failure_key)
            return {"artifact": artifact.model_dump(mode="json")}
        except Exception:
            self.case.tool_failures.add(failure_key)
            return {"error": "capability_failed", "name": name}
