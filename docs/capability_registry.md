# Capability registry and common descriptive contract

SCRUM-9 provides a shared, runtime-independent registry of diagnostic capabilities.
Application setup creates a `CapabilityRegistry` and explicitly registers
implementations. The future Diagnosis Orchestrator receives the registry as a
dependency, consults `list_metadata()`, and resolves capabilities by name.
The registry performs no selection, execution, diagnosis, or automatic discovery.
There are no concrete capabilities in this task.

## Static description

`CapabilityMetadata` contains `name`, `purpose`, `supported_evidence`,
`required_context`, `applicability`, `input_contract`, `output_contract`,
`limitations`, `confidence_uncertainty_semantics`, `research_basis`, and
`implementation_version`. All fields are required. Evidence and context entries
are descriptive strings, not new ALI source schemas or closed enumerations.
An empty `required_context` tuple expresses that no context is needed.

Input/output contracts describe each capability's own structured input and output.
Concrete capabilities will define their typed invocation contracts, validation,
applicability checks, and uncertainty representation when implemented.
Metadata must remain stable while the implementation is registered.

`DiagnosticCapability` is a protocol exposing only `metadata`. The capability's
identity is `metadata.name`. It imposes no common execution method or result
schema. Each concrete capability may later be exposed to the Orchestrator as an
independent tool through runtime integration. No adapters or runtime tools are
introduced here, and the contracts remain independent from OpenAI Agents SDK.

## Results and actual provenance

Capability results remain measurements, observations, predictions, or analysis
results, never final diagnoses. Their concrete schemas are deferred to capability
implementation; no generic result envelope is defined by SCRUM-9.

Actual provenance belongs to each invocation's result, using the existing
`DiagnosticSourceReference` type to identify the evidence/context actually used.
It is absent from static `CapabilityMetadata`. The existing `DiagnosticArtifact`
with `artifact_type=DiagnosticArtifactType.CAPABILITY_RESULT` remains the contract
for preserving supporting results used by the Engine. Result adaptation, artifact
creation, persistence, and version capture are outside the registry and deferred
to their implementation tasks.

## Registration and lookup

- `register(capability)` uses `capability.metadata.name` as its unique key.
  Duplicate names raise `ValueError` without replacing the original capability.
- `resolve(name)` returns the registered instance; missing names raise `KeyError`.
- `list_metadata()` returns descriptions in registration order as a tuple.

Resolution guarantees only the common descriptive interface. Invoking a concrete
capability through its typed interface or tool will be handled by future
integration code. The registry supplies no generic execution API or fallback.

`CapabilityMetadata` reuses the existing frozen Pydantic `ContractModel` and
rejects unknown top-level fields.
