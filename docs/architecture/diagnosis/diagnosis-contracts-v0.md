SCRUM-6 — Diagnosis Contracts v0 — Design Decisions


Purpose
This document is the working decision log for SCRUM-6. We will design the Diagnosis Engine contracts one decision at a time. Nothing is treated as final unless explicitly approved.


Status
Architecture direction: approved.
Implementation contract design: complete / accepted for SCRUM-6.
Contract version: v0 / provisional and expected to evolve.


Agreed foundations
1. The contracts are provisional/evolving domain contracts, not the final ALI schema.
2. The existing Big Data model and the final presentation are our strongest current baseline.
3. We will reuse stable concepts from that model, but we will not copy Iceberg/Silver/Gold tables 1:1 into the Diagnosis domain.
4. Diagnosis contracts must remain independent from OpenAI Agents SDK and other runtime-specific types.
5. The contracts should make future schema evolution explicit rather than pretending the surrounding ALI system is already complete.
6. Decisions will be made one by one: proposal → explanation → review → explicit approval → document update.


Existing model we will use as evidence
- learning_events: common event identity, learner/session, type, time and source.
- practice_attempts: learner response, correctness, score, hints, duration and attempt number.
- silver_content_taxonomy: normalized domain/topic/subtopic/concept hierarchy.
- silver_learner_concept_evidence: evidence ledger connecting learner activity to concepts.
- fact_learner_concept_state: calculated learner state such as mastery, difficulty, confidence and repeated mistakes.


Important boundary inherited from the presentation
Silver learner-concept evidence stores observations/evidence. Gold learner-concept state stores calculated evolving learner state. Diagnosis should consume these concepts through its own domain contracts rather than becoming coupled to warehouse rows.


Decision Log
Decision 1 — ACCEPTED — Diagnosis Run Input


Decision
The Diagnosis Engine is treated as a black box. An external ALI component starts a diagnostic run with a minimal DiagnosisRunRequest. The request identifies the learner and the single evidence record that caused this diagnostic run.


Provisional v0 shape
DiagnosisRunRequest
- diagnosis_run_id — required
- learner_id — required
- evidence_id — required


- schema_version


Internal flow
1. Diagnosis Engine receives the minimal request.
2. The Diagnosis Orchestrator Agent starts from learner_id and evidence_id.
3. The Agent retrieves the full triggering evidence and any additional information it needs through Unified Diagnostic Information Access.
4. The Agent may continue retrieving more information or calling specialized capabilities during the diagnosis.


Important boundary
The Diagnosis Engine does not receive all learner evidence and context by default. It retrieves what it needs adaptively from inside the black box.


Scope note
Capture, normalization, persistence, and generation of evidence_id happen before the Diagnosis Engine is called. That upstream flow is assumed to exist but is outside the current Diagnosis Engine implementation scope.


Reason for this decision
This keeps the Diagnosis boundary small and stable. The request identifies exactly which learner and which persisted evidence item initiated the run, while detailed event/question/chat/IDE/context information is retrieved internally when needed.


Decision 2 — ACCEPTED — One Trigger Evidence per Diagnosis Run


Decision
A single DiagnosisRunRequest contains exactly one evidence_id. There is no trigger_evidence array and no separate TriggerEvidenceReference object in v0.


Rationale
The persisted evidence record is already the normalized anchor for the run. If the Orchestrator needs related evidence from the same session, concept, learner history, previous attempts, or other sources, it retrieves those additional records through Unified Diagnostic Information Access. They are supporting evidence for the diagnosis, not additional trigger inputs.


Presentation alignment
The presentation defines silver_learner_concept_evidence at one learner + taxonomy item + evidence event grain. This supports using one normalized evidence record as the trigger anchor while allowing the diagnosis to retrieve broader evidence afterward.
Decision 3 — ACCEPTED — Remove reason_for_run from v0


Decision
reason_for_run is removed from DiagnosisRunRequest v0.


Final v0 request shape
DiagnosisRunRequest
- diagnosis_run_id — required
- learner_id — required
- evidence_id — required
- schema_version


Rationale
The evidence_id already identifies the persisted observation that initiated the diagnosis. The Orchestrator can retrieve the evidence details internally through Unified Diagnostic Information Access, so an additional reason_for_run field would duplicate information and does not currently change diagnosis behavior.


Scope
If ALI later supports diagnosis runs that are not triggered by a new evidence item, such as scheduled or manual re-diagnosis, the input contract can be versioned and extended then. That case is not part of v0.


Decision 4 — ACCEPTED — Contract Schema Version


Decision
DiagnosisRunRequest includes a required schema_version field.


v0 value
schema_version = "0.1"


Meaning
schema_version identifies only the version of the DiagnosisRunRequest contract structure. It does not represent the Diagnosis Agent version, model version, learner-state version, evidence version, or capability version.


Versioning direction
The provisional contract can evolve through versions such as 0.1, 0.2, and later 1.0 when the boundary is considered stable.


Decision 5 — ACCEPTED — Diagnostic Sources and Provenance


Decision
A diagnosis may use three broad source families:
- Evidence — persisted learner observations/events.
- Context / Information — information retrieved from ALI sources such as Learner State, Domain Knowledge Graph, task/material context, history, previous diagnoses, goals, or profile.
- Capability Results — structured measurements produced by specialized diagnostic capabilities such as Knowledge Tracing or Behavioral / Process Analytics.


The final diagnosis must be able to reference the specific sources that supported or contradicted its findings and hypotheses.


Design direction
Use stable source/result references plus provenance rather than copying every complete tool payload directly into the final Structured Diagnosis.


Conceptual form
DiagnosticSourceReference
- source_kind: evidence | context | capability_result
- source_id: stable identifier for the referenced source/result


For information and capability results, provenance should identify the source/tool/capability that produced the result, its relevant version where applicable, and the source inputs/references used to produce it.


Decision 6 — ACCEPTED — Persist Diagnostic Tool Results as Artifacts


Decision
Information results and capability results that are used by the Diagnosis Engine must be preserved as structured Diagnostic Artifacts so the final diagnosis can later show what concrete results it relied on.


Storage rule
- Existing persisted Evidence is not duplicated. Diagnosis references it by evidence_id.
- Information results retrieved during the diagnostic run may be persisted as Diagnostic Artifacts.
- Capability results produced during the diagnostic run may be persisted as Diagnostic Artifacts.


Conceptual artifact role
Each Diagnostic Artifact receives a stable artifact_id and is associated with the diagnostic run that produced or retrieved it. The artifact preserves the structured result and provenance needed to understand where it came from.


Conceptual fields
DiagnosticArtifact
- artifact_id
- diagnosis_run_id
- artifact_type
- producer
- result
- source_references
- created_at
- version when relevant


Important boundary
SCRUM-6 defines the domain concept and contract direction only. The physical persistence technology or table/collection design is deferred to the dedicated persistence task.


Rationale
A live source such as Learner State or a capability output may change over time. Preserving the result actually seen during the original diagnostic run makes the diagnosis traceable and reproducible without duplicating evidence that already has a stable persisted identity.


Decision 7 — ACCEPTED — Diagnostic Artifact Structure and Subject Reference


Decision
Each meaningful information or capability result used by the Diagnosis Engine is represented as a DiagnosticArtifact. The artifact preserves what was requested, who/what produced the result, the structured result itself, relevant source references, and the learning subject the artifact is about.


Accepted conceptual fields
DiagnosticArtifact
- artifact_id
- diagnosis_run_id
- subject_ref
- artifact_type
- producer
- request
- result
- source_references
- created_at
- schema_version


subject_ref
subject_ref identifies the relevant learning subject through the existing ALI content taxonomy rather than a free-text label. The reference should use the taxonomy identity already defined by ALI, such as taxonomy_id, and may include the taxonomy level when useful.


Purpose
The subject reference allows later retrieval of only the diagnostic history relevant to a learner and a specific subject or concept, optionally combined with a time window, instead of loading the learner's entire diagnostic history.


Example retrieval direction
learner + subject + time window -> relevant previous diagnoses / diagnostic artifacts


Presentation alignment
The existing content taxonomy already models domain, topic, subtopic, and concept with stable taxonomy identifiers and hierarchy. Diagnostic artifacts should reference that 


Decision 8 — ACCEPTED — Run ID Ownership and Subject Resolution


Decision
diagnosis_run_id is created by the ALI application/orchestration layer before the Diagnosis Engine is called. It is passed into the Diagnosis Engine as part of DiagnosisRunRequest. The Diagnosis Engine does not own run-ID generation.


Updated v0 request shape
DiagnosisRunRequest
- diagnosis_run_id — required
- learner_id — required
- evidence_id — required
- schema_version


Run ownership rule
The application/orchestration layer is responsible for creating and registering a unique diagnosis_run_id. Diagnosis uses that supplied ID to associate all DiagnosticArtifacts and the final diagnosis with the same run.


subject_ref resolution
subject_ref is not part of DiagnosisRunRequest. The triggering evidence already links to the ALI content taxonomy through taxonomy_id. Diagnosis retrieves the evidence, obtains taxonomy_id, and resolves the related domain/topic/subtopic/concept through the existing content taxonomy.


Conceptual flow
evidence_id -> learner-concept evidence -> taxonomy_id -> content taxonomy -> subject_ref


Purpose
This keeps external request ownership at the application level while avoiding duplication of subject metadata that already exists in the persisted evidence/taxonomy model.






Decision 9 — ACCEPTED — Completed Diagnosis Output


A completed StructuredDiagnosis must contain both WHAT and WHY. WHAT represents the learner problem identified by the engine. WHY represents the explanation or root-cause hypothesis for that problem. Multiple findings and explanations are allowed, and their relationships must be preserved. If the engine cannot support a reliable conclusion, it returns an unresolved diagnostic outcome rather than forcing one.


Decision 10 — ACCEPTED — Structured Diagnosis Is the Official Stored Conclusion


WHAT and WHY are stored in StructuredDiagnosis, which is the official result of the Diagnosis Engine. DiagnosticArtifact records are supporting inputs and tool/information results; they are not the final conclusion. The StructuredDiagnosis references the evidence and artifacts that support or contradict its conclusions and is persisted as the diagnosis result associated with the diagnosis run.


Decision 11 — ACCEPTED — Unresolved Diagnosis Contract


Decision
When Diagnosis cannot support a sufficiently reliable WHAT and/or WHY, it returns an UnresolvedDiagnosis instead of forcing a conclusion.


Conceptual fields
UnresolvedDiagnosis
- unresolved_scope: what | why | both
- reason
- relevant_sources
- schema_version


The result should state what could not be determined and why the available information was insufficient or conflicting. Technical execution failures are not UnresolvedDiagnosis outcomes.


Decision 12 — ACCEPTED — Module Boundaries


ALI Application / Orchestration
- starts the diagnosis run
- creates and registers diagnosis_run_id


Learner State
- owns persisted learner evidence and learner-state information
- Diagnosis reads from it through the information-access boundary


Domain / Knowledge Graph
- owns taxonomy, concepts, prerequisites, and related domain knowledge
- Diagnosis reads from it as context


Diagnosis Engine
- investigates the learner problem
- retrieves relevant information
- invokes specialized diagnostic capabilities when useful
- creates DiagnosticArtifacts
- returns WHAT and WHY, or an unresolved diagnostic outcome


Adaptive Learning Engine
- receives the diagnosis afterward
- chooses the intervention / next learning action
- does not perform the diagnosis itself


Runtime independence
Diagnosis domain contracts must remain independent from the OpenAI Agents SDK or any other agent runtime.


Decision 13 — ACCEPTED — Validation and Unit-Test Invariants


DiagnosisRunRequest
- diagnosis_run_id is required
- learner_id is required
- evidence_id is required
- schema_version must be valid


Completed StructuredDiagnosis
- contains WHAT
- contains WHY
- is associated with diagnosis_run_id
- source references are valid


UnresolvedDiagnosis
- states what could not be determined
- states why it could not be determined
- is distinct from a completed diagnosis and from a technical execution error


DiagnosticArtifact
- artifact_id is required
- diagnosis_run_id is required
- subject_ref is required
- artifact_type is required
- producer is required
- result is required
- schema_version is required


Architecture invariant
No agent-runtime / Agents SDK types may leak into Diagnosis domain contracts.


SCRUM-6 design status
The core contract design decisions are accepted. Implementation, compilation, documentation in code, and unit tests are still required before SCRUM-6 can be considered complete.


Implementation Decision — ACCEPTED — Python Contract Layer


The SCRUM-6 Diagnosis domain contracts are implemented in Python using Pydantic v2. This keeps the contract layer aligned with the planned Diagnosis/ML ecosystem while remaining independent from the OpenAI Agents SDK. The application/backend may still use another language as long as it exchanges the agreed runtime-independent contract payloads.


Design rule
When a future component is still unknown, prefer a stable semantic contract plus versioning/extensibility over a detailed speculative schema.


Source basis
Adaptive Learning Intelligence — final presentation v3
Existing ALI Big Data implementation
Diagnosis Engine — Full Detailed Architecture