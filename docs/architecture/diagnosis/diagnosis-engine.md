Diagnosis Engine — Full Detailed Architecture
Purpose
The Diagnosis Engine determines what learning problem or problems the learner currently has, why those problems are occurring, how the findings and causes relate to one another, and how strongly the available evidence supports each diagnosis.
Accepted Architecture Foundation
System Boundary
The Diagnosis Engine begins after an external workflow, queue, schedule, session-completion event, or explicit request invokes it. Deciding when to run diagnosis belongs to ALI orchestration, not to the Diagnosis Engine. Once invoked, the engine is responsible for diagnosing the supplied case rather than deciding whether that case is worth diagnosing.
Persistent Diagnosis Orchestrator
A single Diagnosis Orchestrator Agent remains active across the full diagnostic run. It is not one box in a rigid pipeline. It navigates the diagnostic process, decides what information is still needed, chooses which available diagnostic capabilities to use, revisits earlier questions when new evidence changes the picture, and carries the case toward a structured diagnosis.
The Orchestrator provides adaptive reasoning and navigation, but it is not the source of educational truth. It must reason over evidence, context, and research-grounded diagnostic capabilities rather than relying only on unconstrained model judgment.
Three Architectural Dimensions
Evidence — what actually happened in the learner's activity.
Context — information that helps interpret what happened for this learner, domain, task, and point in the learning process.
Diagnostic Capabilities — reusable research-grounded models, algorithms, analyses, and tools that can measure or analyze specific aspects of the case.
The Orchestrator connects all three dimensions. It can use the same capability in different reasoning stages and can call capabilities repeatedly as the diagnostic case develops.
Accepted Evidence Families
1. Structured assessment evidence — multiple-choice questions, correct/incorrect outcomes, short or numeric answers, selected distractors, and other structured assessment results.
2. Open learner responses — explanations, summaries, free-text answers, derivations, and other learner-authored responses.
3. Conversation evidence — learner statements, questions, explanations, expressions of confusion, requests for hints, and other learning signals captured from AI/MCP-supported conversations.
4. Problem-solving and coding evidence — code, IDE activity, errors, attempts, debugging paths, solution processes, and related problem-solving traces.
5. Behavioral and process evidence — retries, hints, response time, action sequence, abandoning or revisiting tasks, and other process-level signals.
6. Metacognitive evidence — learner confidence, self-assessment, expressed certainty, and the relationship between perceived understanding and demonstrated performance.
7. External or validated evidence — instructor feedback, evaluation results, later independent tests, or other validated observations.
Accepted Context Sources
1. Learner-State / Personal Graph — the evolving representation of what the system currently believes about the learner's knowledge, uncertainty, history, weaknesses, misconceptions, and related learning state.
2. Domain Knowledge Graph — concepts, prerequisites, relationships, dependencies, hierarchy, and other domain structure describing what should be known and how knowledge is connected.
3. Task / Assessment Context — metadata about the task, question, difficulty, concept mapping, cognitive level, scoring rules, distractors, and related assessment structure.
4. Learning Material Context — the material, source, chapter, explanation, or content from which the learner is studying.
5. Historical Learning Evidence — prior evidence beyond the immediate case that may be relevant to interpretation.
6. Previous Diagnoses — earlier diagnostic conclusions, their status, confidence, evidence, and evolution.
7. AI-Derived Context — structured interpretations received from connected AI systems, such as suspected difficulty, extracted concepts, or an interpretation of a conversation. These are treated as informed context to investigate, not as ground truth. The learner's actual words remain evidence.
8. Learning / Intervention History — what the learner has already studied, practiced, received hints or explanations for, and which interventions have already been attempted.
9. Educational Goal / Expected Knowledge — what the learner is expected to know at the current point, so lack of knowledge is interpreted relative to curriculum, goals, and learning stage.
10. Learner Profile / Personal Context — pedagogically relevant background such as education level, prior knowledge, language proficiency, experience level, learning goals, and relevant accommodations. Personal attributes may influence diagnosis only when there is a defensible educational relationship to the evidence; they must not be used as unsupported stereotypes.
Cross-Cutting Diagnostic Capability Layer
Diagnostic capabilities are not owned by one reasoning stage. They form a shared capability layer available to the Orchestrator throughout the complete run. A capability may be used while identifying what is wrong, while investigating why it is happening, during synthesis, or while checking the resulting diagnosis.
Capabilities may include trained models, statistical methods, graph algorithms, semantic analyses, temporal analyses, deterministic rules, or other research-backed methods. The exact registry is intentionally not frozen yet; it will be researched and designed capability by capability.
Main Reasoning Stages
WHAT — Problem Identification: determine which meaningful learning problem or problems are observable in the available case.
WHY — Root Cause Analysis: investigate plausible explanations for the identified problems and the relationships among those explanations.
Diagnostic Synthesis: combine findings, hypotheses, evidence, context, capability outputs, supporting evidence, and contradicting evidence into one coherent diagnostic picture. Multiple diagnoses may coexist.
Diagnosis Quality Validation: before publishing a diagnosis, verify that it is supported, internally consistent, structurally valid, and does not claim more than the evidence and capabilities justify. This is an internal quality gate and is distinct from ALI's separate high-level Evaluation / Validation System.
Research-Grounded Reasoning Rule
The architecture must not reduce diagnosis to "ask a large model to diagnose." The Orchestrator contributes adaptive reasoning, but specialized measurements and analytic signals should come from research-grounded models and methods whenever an applicable capability exists. Examples may include knowledge-tracing models, option-level analysis, graph-based analysis, semantic analysis, behavioral analysis, or other methods that we will validate during capability design.
A capability result is not automatically a diagnosis. It is a structured observation, measurement, prediction, or analysis result that the Orchestrator can combine with other evidence and context.
If no specialized capability fits a case, the Orchestrator may still reason from the available evidence and context, but the system must preserve the uncertainty and the absence of specialized support rather than pretending that a research-backed measurement was performed.
Implementation Rule
Every diagnostic capability accepted during architecture design becomes real implementation scope. Depending on the capability, this may require a model or algorithm, input/output contracts, inference or analysis logic, integration adapters, versioning, validation, tests, observability, and agent-tool exposure. The implementation plan must therefore include both the Orchestrator and the diagnostic capabilities it depends on.
Diagnostic Capability Registry
The Diagnosis Engine maintains a shared registry of diagnostic capabilities that the Diagnosis Orchestrator may consult and invoke at any reasoning stage. The registry does not decide which capability to run and does not perform diagnosis by itself; it describes the available diagnostic instruments and the conditions under which they can be used responsibly.
Common Capability Contract
Every registered capability must expose a common descriptive contract so the Orchestrator can understand what the capability is for, when it applies, what it needs, what it returns, and what its result does not prove.
Name — stable capability identifier.
Purpose — the diagnostic question or measurement the capability can help address.
Supported Evidence — which evidence modalities the capability can analyze.
Required Context — which contextual sources, if any, are required or useful.
Preconditions / Applicability — the conditions under which using the capability is valid and meaningful.
Input Contract — the structured data accepted by the capability.
Output Contract — the structured observations, measurements, predictions, or analysis results returned to the Orchestrator.
Limitations — conclusions that must not be inferred from the capability result.
Confidence / Uncertainty Semantics — how uncertainty, reliability, or model confidence is represented and interpreted.
Research Basis — the model, algorithm, theory, or research evidence that justifies the capability.
Implementation Version — the concrete model, algorithm, rule set, prompt, or implementation version used for reproducibility and comparison.
Provenance — the evidence and context used to produce each capability result so the result can be traced back to its sources.
A capability result is an instrument reading, not a final diagnosis. The Orchestrator remains responsible for deciding which capability can reduce uncertainty in the current case and for combining its output with other evidence, context, and capability results.
Accepted High-Level Architecture and Workflow
Architecture at a Glance
External ALI orchestration decides when a diagnosis run starts. Once invoked, one persistent Diagnosis Orchestrator Agent owns the diagnostic run. It reasons over Evidence, retrieves relevant Context, and can invoke any capability from the shared Diagnostic Capability Registry.
The Orchestrator does not expose every external ALI subsystem as a separate low-level tool. It uses a unified diagnostic-context access interface to request the information it needs from external sources such as the Learner-State / Personal Graph, Domain Knowledge Graph, history, prior diagnoses, task context, learning materials, AI-derived context, and learner profile. This context-access layer retrieves and assembles information; it does not diagnose.
Accepted Workflow
The diagnostic workflow is iterative, not a one-way pipeline. WHAT, WHY, Diagnostic Synthesis, and Diagnosis Quality Validation are revisitable reasoning goals inside the same ongoing diagnostic run.
WHAT — identify and refine the learning problem or problems currently supported by the evidence.
WHY — investigate plausible causes and relationships that may explain those problems.
Diagnostic Synthesis — combine current findings, hypotheses, evidence, context, and capability results into a coherent diagnostic picture.
Diagnosis Quality Validation — check whether the current diagnosis is sufficiently supported, internally consistent, appropriately uncertain, and within the limits of the evidence and capabilities.
New evidence, retrieved context, or a capability result may cause the Orchestrator to move backward or sideways: WHY can refine WHAT; Synthesis can reveal a missing investigation; Quality Validation can send the run back to WHAT or WHY; and any stage may request more information or invoke another capability.
Conceptual workflow: WHAT ↔ WHY ↔ DIAGNOSTIC SYNTHESIS ↔ DIAGNOSIS QUALITY VALIDATION. The Orchestrator may loop among these goals until the diagnosis is sufficiently supported, or until the correct outcome is that the available evidence is insufficient or unresolved.
Temporary In-Run Diagnostic State
During a diagnostic run, the Orchestrator maintains temporary in-memory state for the current case. This is runtime working context only: it is not a persisted Diagnosis domain object, is not a durable source of truth, and must not contain hidden chain-of-thought or a chronological history of internal reasoning attempts.

The temporary state may contain the DiagnosisRunRequest, resolved subject_ref, the current set of WHAT findings, current WHY hypotheses, information retrieved during the run, capability results produced during the run, supporting and contradicting source references, the current synthesis candidate, the latest quality-validation result, and minimal runtime-control data such as the active stage and iteration/loop count.

WHAT and WHY are evolving current case representations rather than single immutable strings. For example, the current WHAT collection may preserve still-supported findings, refine existing findings, remove findings that are no longer supported, and add newly discovered findings. The state should preserve the current diagnostic picture needed by later stages, but it should not preserve model-thought history such as WHAT attempt 1, WHAT attempt 2, or hidden reasoning traces.

LangGraph state is the shared runtime memory between diagnostic stages. A model invocation does not automatically know results from an earlier graph node unless the relevant information is supplied again through the current state or the local agent-loop context. Each stage therefore receives only the case information it needs from the temporary state. At the end of the run, the temporary state is discarded; only the approved final diagnosis outcome and the DiagnosticArtifacts actually used to support or contextualize it are persisted.
Accepted Diagnosis Capability Landscape
After the evidence-by-evidence research and boundary review, the Diagnosis Engine currently owns one core specialized capability family: Knowledge / Response Tracing. The registry remains extensible, but a new Diagnosis-owned capability should be added only when it provides a distinct, research-grounded measurement or computation that clearly belongs inside the Diagnosis boundary and should not be performed merely through general LLM reasoning. Not every evidence family requires a separate Diagnosis capability.
1. Knowledge / Response Tracing
This family contains validated tracing models such as DKT, AT-DKT / Option Tracing, future AKT variants, and other justified KT implementations. These models may support both WHAT and WHY reasoning. Depending on the implementation, they can provide future-performance predictions, response or option tendencies, and evidence associated with recurring distractor or misconception patterns when those mappings are known. Their outputs are measurements or evidence, not proof of mastery, misconception, or root cause.
Behavioral / Process Evidence Boundary
Behavioral and process signals remain accepted Diagnosis evidence, but raw event normalization, aggregate metric calculation, sequence analysis, response-time processing, retry/hint/abandonment computation, and similar event-processing logic are upstream evidence-production responsibilities outside the Diagnosis Engine. Diagnosis consumes normalized behavioral evidence or structured behavioral measurements produced elsewhere and may use them during WHAT, WHY, Synthesis, or Quality Validation.
Evidence and Analyses Not Owned as Separate Diagnosis Capabilities
Open responses and conversations remain direct evidence for the Diagnosis Orchestrator. The Orchestrator may retrieve rubrics, expected concepts, Domain Graph context, Learner State, history, and other information and reason over the text directly. A second generic LLM call is not treated as a specialized capability merely because it produces structured text.
Misconception detection is not a generic standalone capability at this level. Misconception evidence may come from AT-DKT / Option Tracing when distractors are mapped to misconception knowledge components, from learner text or conversation evidence, or from other corroborating evidence. The Orchestrator forms and tests the misconception hypothesis.
Cognitive Diagnostic Modeling, long-term mastery/state estimation, metacognitive calibration, and long-term forgetting or stability measurements belong primarily to Learner State. Diagnosis retrieves and uses those values as context when relevant rather than owning the persistent estimation mechanisms.
Item calibration, item difficulty/discrimination, cognitive-demand metadata, and similar assessment properties are treated as task, assessment, or domain context rather than Diagnosis-owned capabilities.
Prerequisite reasoning and domain relationships come from the Domain Knowledge Graph and Learner-State / Personal Graph through Unified Diagnostic Information Access. Domain or solution truth should be represented or supplied by the relevant domain systems and evidence sources; Diagnosis uses that information rather than owning a separate domain-verification engine.
Coding and problem-solving artifacts remain evidence. Compiler/test outcomes and other objective results can be consumed directly. Large raw behavioral or debugging event streams should be normalized and summarized by upstream evidence-processing systems before Diagnosis consumes them. Semantic interpretation of the diagnostic case remains with the Orchestrator.
Cross-evidence consistency and evidence sufficiency are responsibilities of Diagnostic Synthesis and Diagnosis Quality Validation, not separate capabilities. Transfer/generalization is currently treated as an Orchestrator reasoning pattern over evidence from multiple contexts rather than as a dedicated capability.
Capability Gap Check Result
No additional core specialized Diagnosis capability is currently required. Future capabilities may still be added when research or implementation work identifies a specialized, measurable operation that materially improves diagnosis, cannot be handled well through direct Orchestrator reasoning over available evidence/context, and clearly belongs inside the Diagnosis boundary.
Known Model Implementations and Status
Model names are implementations behind capabilities rather than the capability architecture itself. DKT and AT-DKT / Option Tracing are existing project implementations inside the Knowledge / Response Tracing family. Generic AKT-DKT is not yet finished and may become another implementation in the same family once completed. Future KT variants may be added only when they provide validated value and a clear contract. The Orchestrator consumes their outputs as evidence; no tracing model is treated as a final diagnosis by itself.


High-Level Implementation Meaning
The approved architecture now implies implementation work for: the persistent Diagnosis Orchestrator; unified context-access integration; the shared Capability Registry and common capability contract; capability adapters for existing models; future research-backed capabilities added to the living landscape; iterative WHAT/WHY/Synthesis/Quality-Validation control flow; structured diagnosis output; and tests, observability, versioning, provenance, and validation around those components.




























Core Diagnosis Architecture — Canonical Diagram
This is the canonical high-level view. The Orchestrator is the center of the system. At any reasoning stage it may retrieve information, call diagnostic capabilities, or use both together. Results return to the Orchestrator and may change earlier conclusions during the active run.
                         DIAGNOSIS CASE
                         Evidence / request
                                │
                                ▼
        ┌──────────────────────────────────────────────┐
        │          DIAGNOSIS ORCHESTRATOR              │
        │                                              │
        │        Temporary in-run case context          │
        │                                              │
        │  WHAT ↔ WHY ↔ SYNTHESIS ↔ QUALITY VALIDATION│
        │          iterative reasoning loop            │
        │                                              │
        │  At ANY stage the Orchestrator may use:      │
        │                                              │
        │  ↔ Unified Diagnostic Information Access     │
        │    learner state • domain graph • history    │
        │    profile • prior diagnoses • case context  │
        │                                              │
        │  ↔ Diagnostic Capability Registry            │
        │    shared, reusable, research-grounded       │
        │    living capability set                     │
        │                                              │
        │  Information + capability results update     │
        │  the current case and can trigger rethinking │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
                  STRUCTURED DIAGNOSIS
                    or INSUFFICIENT EVIDENCE


Implementation Blocks — Not a Runtime Sequence
The architecture translates into five main buildable blocks: Unified Diagnostic Information Access; Capability Registry and capability adapters; Diagnosis Orchestrator; iterative WHAT/WHY/Synthesis/Quality-Validation control; and structured Diagnosis Output with persistence, provenance, observability, and tests. Temporary in-run reasoning state is an implementation detail of the active Orchestrator run rather than a separately persisted architecture block. Capability research and implementation continue as a living workstream rather than as one fixed step in the runtime flow.
Evidence-to-Capability Research Program
The current capability landscape is not considered complete. From this point, architecture work will systematically examine every accepted evidence family and determine which research-backed diagnostic capabilities can extract useful signals from that evidence.
For each evidence family we will: (1) identify the diagnostic signals that can legitimately be extracted; (2) review relevant educational-data-mining, learning-analytics, cognitive-diagnosis, NLP, learner-modeling, and related research; (3) identify candidate capabilities, models, or algorithms; (4) define their applicability and limitations; (5) check whether ALI already has an implementation; and (6) add missing capabilities to the living Capability Registry and later implementation backlog.
The goal is coverage rather than forcing every evidence type through the same model. Structured assessment, open responses, conversations, coding activity, behavioral/process signals, metacognitive evidence, and external/validated evidence may require different capabilities. Cross-evidence capabilities may then combine or compare results across modalities.
Synthesis and Quality Validation — Architectural Meaning
Diagnostic Synthesis creates a coherent candidate diagnosis from the current in-run case context. It combines the current WHAT findings, WHY hypotheses, supporting and contradicting evidence, relevant context, capability results, and uncertainty. Synthesis does not prove that the diagnosis is correct; it organizes the best current explanation of the case.
Diagnosis Quality Validation is the internal quality gate applied to that candidate diagnosis. It asks whether the diagnosis is sufficiently supported, internally consistent, within capability limitations, appropriately uncertain, and free of unsupported claims. If validation exposes missing evidence, contradictions, or overclaiming, the Orchestrator does not simply fail; it loops back to WHAT, WHY, context retrieval, or additional capability calls and tries again. A valid final outcome may also be explicitly unresolved or insufficient evidence.


Behavioral / Process Evidence — Ownership Boundary
Status: Accepted as an evidence family, not as a Diagnosis-owned capability. Large behavioral event streams may contain useful quantitative and sequential signals, but normalization and metric extraction belong upstream of Diagnosis. The Diagnosis Engine should not own the raw event-processing pipeline.
Purpose
Upstream learning/process analytics may convert raw learning-process events into structured behavioral observations that the Diagnosis Orchestrator can consume as evidence or context. Examples include timing, retries, hint usage, transitions between actions, abandonment or revisiting, repeated error loops, debugging behavior, and related process patterns. Diagnosis interprets these observations together with other evidence; it does not own the event-normalization or metric-computation implementation.
Evidence It Consumes
The primary input is timestamped process evidence: task or item identifier, event/action type, outcome, response time, retry events, hint requests, navigation or revisit events, abandonment/completion state, and, when available, coding/IDE events such as compile/test executions, error types, edits, repeated failures, debugging actions, and AI/help requests. The analyzer may also receive task metadata needed to interpret timing or event meaning.
What It Should Measure
The first implementation should support four analysis groups. Sequence and process patterns identify recurring action paths, loops, transitions, bottlenecks, and deviations across a session or evidence window. Effort and rapid-response analysis measures unusually short response behavior and related indicators that may reduce the diagnostic reliability of correctness evidence. Help-seeking analysis measures when help is requested, whether attempts occur before help, the level of assistance used, and what happens after help. Coding/debugging process analysis measures repeated error cycles, changes between failures, debugging strategy transitions, repeated compiler/test errors, and relevant help or AI-use events.
Expected Output
The output is structured measurement, not a diagnosis. Example fields include rapid-response rate, retry rate, hint rate, attempt-before-help rate, abandonment rate, revisit rate, repeated-error counts, detected action sequences, transition patterns, debugging-loop summaries, evidence count, time window, and reliability or uncertainty metadata. Every derived observation must retain provenance back to the events from which it was computed.
How the Diagnosis Orchestrator Uses It
During WHAT reasoning, the Orchestrator can use behavioral measurements to qualify or refine an observed learning problem. For example, many incorrect answers accompanied by extremely rapid responses should not be interpreted in the same way as many incorrect answers produced after sustained attempts. During WHY reasoning, repeated retry loops, ineffective help-use patterns, or repeated debugging failures can become evidence for hypotheses about the process contributing to the learning difficulty. During Synthesis and Quality Validation, behavioral measurements can strengthen, weaken, or contextualize evidence from KT, learner state, conversations, open responses, and other sources.
Implementation Plan
Any event-normalization layer, aggregate metrics, time-based measures, transition counting, rule-based process detectors, and sequence-analysis functions should be implemented in the upstream evidence/analytics pipeline rather than inside Diagnosis. Their outputs should be exposed to Diagnosis through stable evidence or information contracts with provenance.
If ALI later adds educational process-mining, sequence-mining, or learned behavioral classifiers, those analyzers remain upstream producers unless a future architecture review demonstrates a distinct operation that truly belongs inside Diagnosis. Diagnosis should consume their structured outputs without depending on their internal implementation.
How We Observe and Validate It
Upstream behavioral measurements supplied to Diagnosis should expose the evidence window, relevant source references, producer/version metadata, and uncertainty or reliability information needed for inspection and provenance. Validation of the upstream metric calculations belongs with the producing subsystem. Diagnosis tests should verify that such measurements can be retrieved and interpreted without treating them as proof of a diagnosis.
Scientific and Architectural Limits
Behavioral signals must remain observations. A rapid response is not proof of guessing; repeated help requests are not proof of low ability; repeated debugging failures are not proof of a knowledge gap. Timing thresholds are task-dependent, behavior can have several explanations, and process patterns should be combined with other evidence before a diagnostic conclusion is made. The capability therefore reports measurements and uncertainty while the Diagnosis Orchestrator performs the interpretation.
Research Basis
This capability is grounded in Educational Process Mining and sequential learning-process analysis, research on response-time effort and rapid responding, metacognitive/help-seeking work in intelligent tutoring systems, and programming-education research that analyzes debugging and problem-solving traces. Representative foundations include Bogarín, Cerezo, and Romero on Educational Process Mining; Wise and Kong on response-time effort; Aleven, McLaren, Roll, and Koedinger on help-seeking behavior in intelligent tutors; and research using sequence analysis of learner debugging processes.
Accepted Architectural Rule
Behavioral / process evidence may be used at any reasoning stage when it can reduce uncertainty, but the Diagnosis Engine does not currently own a Behavioral / Process Analytics capability. Diagnosis consumes structured behavioral observations produced upstream and remains responsible for combining them with other evidence and context without treating those observations as final diagnoses.
Agent Runtime Decision — LangGraph
The Diagnosis Engine will use LangGraph as the selected orchestration runtime for one persistent Diagnosis Orchestrator run. LangGraph is an implementation mechanism, not the Diagnosis architecture itself: ALI keeps ownership of the Diagnosis domain model, evidence/context contracts, capability contracts, persistence, and the high-level WHAT ↔ WHY ↔ Synthesis ↔ Quality Validation policy.
LangGraph manages the outer diagnostic workflow and routing between WHAT, WHY, Diagnostic Synthesis, and Diagnosis Quality Validation. These are separate conceptual graph stages/nodes and remain revisitable: WHY may send the run back to WHAT, Synthesis may reveal missing investigation, and Quality Validation may route back to WHAT or WHY.

Inside a stage that requires open-ended model/tool interaction, use a mature prebuilt agent loop rather than reimplementing the low-level think/tool/result cycle manually. The graph controls where the diagnosis is in the overall process; the inner agent loop handles reasoning and tool use within the active stage. Deterministic retrieval, validation, routing, limits, and other code-driven operations may remain ordinary graph nodes rather than LLM decisions.
This runtime choice remains replaceable. LangGraph-specific types must stay behind a runtime/orchestration boundary so a future runtime could be substituted without changing Diagnosis domain contracts, Unified Diagnostic Information Access contracts, concrete capability contracts, or final diagnosis contracts.

For SCRUM-11, the first implementation should prove the runtime architecture with template/mock stage behavior, mocked information access, and mocked concrete capabilities. Real WHAT/WHY intelligence, real capability logic, and real external data-retrieval implementations are intentionally deferred to later tasks. The purpose of the first graph is to prove state flow, routing, looping, tool invocation, failure handling, and safe termination.
Architecture Freeze — Implementation Ready
The high-level Diagnosis Engine architecture is now considered frozen and ready to move into implementation. The major ownership boundaries, accepted evidence families, context sources, iterative reasoning model, Unified Diagnostic Information Access, Capability Registry contract, capability ownership decisions, structured diagnosis outcome, and internal quality-validation behavior have been decided.
The current specialized Diagnosis capability landscape contains one core family: Knowledge / Response Tracing. Behavioral/process signals, long-term learner-state estimates, metacognitive calibration, domain/prerequisite knowledge, assessment metadata, open responses, conversations, compiler/test outcomes, and historical context are retrieved or consumed as evidence/context rather than being forced into additional Diagnosis-owned capabilities.
Detailed class structure, API schemas, storage choices, thresholds, individual model adapters, prompts, tests, and deployment details are intentionally deferred to implementation design. They may evolve without reopening the high-level architecture as long as they preserve the accepted boundaries and contracts.
Architecture change rule: a new core capability or ownership change should be introduced only when research or implementation evidence shows a real missing specialized operation, a boundary problem, or a measurable diagnostic need that cannot be handled cleanly by the existing Orchestrator, Unified Diagnostic Information Access, Learner State, Knowledge Graphs, or the Knowledge / Response Tracing family.