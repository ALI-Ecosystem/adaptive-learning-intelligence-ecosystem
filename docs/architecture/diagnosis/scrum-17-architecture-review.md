# SCRUM-17 architecture investigation and refactoring

## Investigation and decision (2026-10-22, before refactoring)

The accepted design requires one logical orchestrator, four revisitable goals,
LangGraph as a replaceable outer runtime, a mature inner agent/tool loop, shared
temporary state, and provider-independent domain contracts. It does not require
two state representations or a second mock-only graph in the production package.

| Responsibility | SCRUM-11 | Initial SCRUM-17 | Decision |
| --- | --- | --- | --- |
| Run state | `DiagnosisRuntimeState`, domain findings/hypotheses, provisional result dictionaries | `Case` repeats request, subject, findings, hypotheses, candidate and outcome | Evolve the existing state, retain its descriptive field names, move it inward to `application/orchestration/state.py`; remove `Case` |
| Graph wiring | `graph.py` composes four nodes; fixed forward edges and validation-only refinement | `agent_graph.py` builds another graph inside `run`, with a one-field `_GraphState` wrapper | One `graph.py`, conditional routing from every stage; no wrapper state |
| State ownership | Nodes consume the state argument and return updates | Node ignores its argument and mutates the closure's `case`; tools also hold it | Read the actual graph state, work on a detached stage copy, return explicit field updates; route from that result |
| Stage behavior | Separate functions, but all diagnostic content and capability identity are hardcoded | Real prebuilt model/tool loop and typed decisions | Keep four named graph stages; share one node executor because their execution lifecycle is identical; remove mock node bodies |
| Navigation | `validation_decisions` tuple and fixed edges | Agent-supplied next stage, checked publication policy | Retain autonomous navigation; deterministic decisions belong only in test agents |
| Model outputs | Provisional dictionaries | Four Pydantic decisions; `StageDecision` is only their union | Retain: domain outcomes do not express intermediate findings, refinement requests or validation decisions |
| Model/agent replacement | None in the mock proof | `StageAgent` protocol and LangChain adapter | Retain: isolates provider/framework-specific agent execution from application policy |
| Runtime replacement | Callers import compiled LangGraph graph | `DiagnosisRuntime.run` protocol and `RunReport` | Retain: caller receives domain outcome/artifacts/metrics without LangGraph types; not a second orchestrator |
| Information | Existing gateway and source protocol | Same gateway plus source selection and artifact mappers | Reuse unchanged; mappings adapt source-specific dictionaries to the accepted artifact contract |
| Capabilities | Existing registry; WHY insists on a concrete mock class | Registry discovery plus allowlisted execution bindings | Keep controlled execution: registry metadata alone cannot validate arguments, applicability, outputs or execution |
| History | Snapshot per validation round | Current state only | Remove snapshot/history machinery; keep counters and current public validation assessment |

The preferred approach is an evolution of SCRUM-11's composition and state structure
with SCRUM-17's real agent behavior. Reverting to the old graph would lose arbitrary
stage revisits, tool choice and real model execution. Keeping both graphs would leave
duplicate responsibilities, misleading defaults and regression tests on the wrong path.

## Planned dependency and responsibility map

- Domain: existing request, findings, hypotheses, outcomes, metadata and artifacts;
  no changes to accepted contracts.
- Application state: one `DiagnosisRuntimeState`; current findings/hypotheses,
  typed candidate/validation, artifact map, tool-failure codes and bounded counters.
  The artifact map replaces provisional information/capability dictionaries rather
  than storing the same results twice. No snapshots or raw model conversations.
- Application contracts: stage-output schemas, `StageAgent`, `DiagnosisRuntime`,
  and `RunReport`. The state is separate from wire/output contracts to make ownership clear.
- Application policy: validate and apply stage outputs, enforce identity/provenance,
  invalidate stale synthesis, publish only at validation, select supporting artifacts.
- Application tools: existing gateway/registry plus controlled invocation; tool errors
  live in shared state so changing stage-local tool objects cannot lose failure context.
- Infrastructure graph: four named nodes, adaptive edges and routing only.
- Infrastructure node executor: clone incoming state, bind stage-local tools, invoke
  the injected agent, apply policy, return updated fields. No closure-owned case.
- Infrastructure runtime adapter: per-run budget/dependency composition, deadline,
  graph invocation and conversion of its returned state to `RunReport`.
- Infrastructure LLM adapter: unchanged prebuilt tool loop and provider-independent
  prompts; sends current state to the model, exposes controlled tools, parses stage output.

The two protocols protect different replacement axes. `StageAgent` is not a second
agent per goal: the same logical agent implementation handles all four goals with
shared run state. `DiagnosisRuntime` is the caller boundary around that entire run.
`RunReport` adds supporting artifacts and aggregate usage to the unchanged domain
outcome; it does not create an alternative diagnosis contract.

## Regression strategy

Capture the baseline with live tests explicitly excluded. Migrate useful SCRUM-11
assertions (stage order/refinement, state isolation, dependency use, limits, final
contracts) to the consolidated graph. Replace assertions tied to scripted production
decisions, mock-result dictionaries or stored snapshots with the corresponding real
architecture invariants. Retain SCRUM-17 tool, provenance, budget, prompt, provider
transport and failure tests. Add graph-state/stream isolation, concurrent-run and
model-tool-result-driven refinement tests. Make no paid or live model calls.

## Implemented result and verification

The comparison above was implemented without changing the accepted architecture
documents, domain contracts, gateway/source interfaces, or registry ownership.

- **Reused/evolved:** `graph.py`, `routing.py`, four conceptual graph stages,
  `DiagnosisRuntimeState` (moved inward, original descriptive fields retained),
  `InformationGateway`, `CapabilityRegistry`, domain models, typed outputs, prompts,
  provenance/publication policy, resource limits and the real LLM adapter.
- **Removed:** `Case`, `_GraphState`, `agent_graph.py`, `DiagnosticSnapshot`,
  `diagnostic_history`, hardcoded mock stage bodies/dependencies, fixed forward
  edges, production mock decision tuples, and duplicate provisional result stores.
- **Separated:** `runtime.py` owns run lifecycle; `graph.py` owns wiring;
  `nodes.execute_stage` owns a common stage execution lifecycle. Four trivial
  forwarding node functions would not add distinct responsibilities, so the same
  executor is explicitly bound to each named goal. Stage-specific behavior remains
  in typed decisions, prompts and application policy.
- **Retained intentionally:** `StageDecision` is a union of validated intermediate
  outputs; `StageAgent` protects agent/model replacement; `DiagnosisRuntime` protects
  whole-runtime replacement. Removing these would couple application callers or
  policy to framework types rather than eliminate redundant orchestration.

Every stage now reads the actual incoming LangGraph state. Its tools update a
detached working copy, and a validated decision produces explicit graph updates.
Routing reads that updated state. The runtime constructs its final report from the
graph result rather than a closure's mutable object. The same logical agent and
shared run budget span all stages; each model call receives current evidence and
conclusions, and its inner prebuilt loop receives actual tool-result messages.
Tool failure codes travel with state across stage boundaries. No copy is retained
as private reasoning or diagnostic-attempt history.

Verification on **2026-10-22**:

- Baseline: **84 passed, 9 live tests deselected**.
- After refactoring: **81 passed, 9 live tests deselected** using
  `.cache/scrum17-venv/Scripts/python.exe -m pytest -q -m 'not live'`, with
  `ALI_DIAGNOSIS_RUN_LIVE=0` explicitly set.
- Test count is not a direct coverage comparison: snapshot persistence and
  production mock-script assertions were retired; their relevant state isolation,
  routing, dependency, limit and outcome invariants were migrated to the real graph.
- New checks cover detached input/stream updates, validation refinement counters,
  cycles from all four goals, concurrent run isolation, failures/budgets across stage
  transitions, and incorrect stage output without publication of partial state.
- A deterministic model double inside the **actual prebuilt agent loop** discovers
  a renamed capability, receives its result, routes WHY back to WHAT, and changes
  the final finding for two different measurements. This checks agent plumbing and
  response-driven behavior, not real-model intelligence.
- Existing OpenAI/Anthropic adapter substitution tests pass using controlled HTTP
  transports; no provider network requests or paid model calls are made.
- `compileall`, `git diff --check`, and wheel build pass. Wheel contents include the
  unified state/runtime and all five prompts and exclude retired modules.

## Remaining limitations and migration

Live-model quality/acceptance and production capability validation remain deferred.
Synthetic tests establish orchestration behavior, not educational diagnostic accuracy.
Existing cooperative-I/O deadline and conservative cost-reservation limitations are
unchanged; see the implementation guide. Persisting final approved artifacts/outcomes
remains outside this change.

The mock builder API is intentionally replaced: callers supply an agent, tool factory
and per-run budget, or use `LangGraphDiagnosisRuntime.run`. Import shared state from
`application.orchestration.state`. Code importing removed mock modules or relying on
snapshot history must migrate to test doubles/current state. No compatibility copy
of the old graph is retained. No commit, merge, push or Jira modification was made.
