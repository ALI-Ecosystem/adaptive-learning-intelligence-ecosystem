# SCRUM-17 implementation: Agentic Diagnosis Orchestrator

This implementation follows the accepted Diagnosis architecture and v0 contracts.
It introduces no domain contracts, persistence model, or new specialized capability.
The synthetic tracing instrument is a test double, not a research-backed model.

## Responsibility and dependency map

```text
Caller -> DiagnosisRuntime.run(DiagnosisRunRequest) -> RunReport
             ^
             | implemented by LangGraphDiagnosisRuntime
             |
    WHAT <-> WHY <-> synthesis <-> validation
       agent proposes goals; policy checks prerequisites
             |
         StageAgent (application protocol)
             ^
             | implemented by LangChainStageAgent
             |
       LangChain create_agent + configured chat model
             |
       controlled DiagnosisTools
          /                 \
 InformationGateway     CapabilityRegistry (discovery only)
 + source mappers       + explicit CapabilityBinding execution adapters
```

`application/orchestration/state.py` owns the single `DiagnosisRuntimeState`, evolved
from SCRUM-11 and moved inward so application policy and adapters share it without
depending on LangGraph. `contracts.py` defines typed stage decisions and the two
replacement interfaces. `policy.py` owns stage prerequisites, publication and
provenance checks. `tools.py` owns source selection, capability authorization,
argument/result validation, applicability, artifact capture, and safe tool feedback.
`budget.py` owns shared run limits. None imports LangGraph, LangChain, or a provider.

`infrastructure/langgraph_runtime/graph.py` wires four conceptual nodes and
conditional edges, preserving the original composition responsibility. `routing.py`
reads the next goal from validated state. `nodes.execute_stage` shares the execution
lifecycle across those four nodes: detach the incoming graph state, bind tools,
invoke the agent, apply application policy and return explicit field updates.
`runtime.py` owns per-run dependency/budget setup, deadline and report assembly from
the graph's returned state. One run keeps one current diagnostic picture across
every stage; there is no closure-captured alternative case or wrapper graph state.
`llm_agent.py` adapts the prebuilt LangChain
`create_agent` tool loop rather than implementing a custom think/tool/result loop.
`model_configuration.py` selects the provider/model and disables SDK retries so the
run budget controls retry attempts. Compatible OpenAI, Anthropic, DeepSeek, Gemini and Groq integrations
share the same prompts, structured-output tool strategy, and application interfaces.

There is one production graph. The former parallel `agent_graph.py`, `Case`, mock-only
node bodies, mock dependencies and snapshot history have been removed. Test agents
live in `tests/orchestration_fakes.py`; all graph tests use the production builder.
Callers use `LangGraphDiagnosisRuntime`, exported from `langgraph_runtime`, through
the application `DiagnosisRuntime` protocol. See the
[architecture review](scrum-17-architecture-review.md) for the comparison and rationale.

Internal API migration: `DiagnosisRuntimeState` is now imported from
`application.orchestration.state`; its original descriptive fields (`subject_ref`,
`what_findings`, `why_hypotheses`, `synthesis_candidate`, `latest_validation_result`,
`final_result`) replace the equivalent `Case` fields. The artifact map replaces
provisional information/capability result stores. `build_diagnosis_graph` requires
an injected agent, tool factory and run budget; it no longer accepts mock decision
tuples or silently creates mock dependencies. The low-level builder binds a per-run
budget; reuse the runtime adapter, which creates a fresh budget for every request.

## Current case and publication

Only the latest WHAT findings, WHY hypotheses, synthesis, and public validation
assessment are retained. Updating WHAT clears WHY; changing either claims or tool
information invalidates synthesis. Validation may accept a current candidate,
request any goal again, or produce `UnresolvedDiagnosis` from insufficient or
contradictory educational evidence. Only validation publishes a result.

Stage navigation is guarded in `apply_decision`, independently of the LLM:

| Destination | Prerequisite |
| --- | --- |
| WHAT | Always revisitable during an active run |
| WHY | A completed WHAT assessment |
| Synthesis | Completed WHAT and WHY assessments for the current findings |
| Validation | Normally a completed WHAT assessment; resource-finalization may assess retrieved evidence before WHAT completes, for unresolved only |
| Validation accept | Completed WHAT and WHY, plus a current synthesis candidate matching the current claims, identities and retrieved sources |

Two temporary state flags, `what_complete` and `why_complete`, distinguish a valid
empty assessment from a skipped stage. Every WHAT output clears WHY completion and
hypotheses, synthesis and the previous validation assessment. Every WHY output clears
synthesis and the previous validation assessment. A new synthesis also clears the
previous validation assessment. New information/capability results clear synthesis
and the previous validation assessment; the agent decides whether their meaning
requires revisiting WHAT or WHY, and fresh synthesis must review the current evidence.
Empty findings or hypotheses never require invented claims: validation can report
unresolved without synthesis, including a supported problem with an unsupported cause.

Invalid proposed transitions raise `InvalidDecisionError` before applying the decision.
The shared node executor offers up to `max_decision_retries` corrections (default 2)
in the same stage, supplying the last actionable `decision_feedback`. It applies each
proposal to a detached copy and publishes only a successful update. Successfully
retrieved artifacts, source identity, tool-failure status and tool-driven invalidation
survive rejection; partially applied claims, counters and transitions do not. Feedback
is cleared after success. Repeated invalid decisions raise a controlled execution
error. No transcript or rejected-decision history is retained.

Corrections call the same agent and share the original model/tool/time/cost budget.
The LLM middleware charges each actual model attempt, including inner schema repair
and provider retries; the executor does not double-charge stage invocations. A custom
`StageAgent` must reserve its actual provider attempts in `RunBudget`. Pure deterministic
test agents may make no model calls. Rejected assessments do not increment completed
stage/validation counters. Valid cycles remain bounded by the stage budget, with a
final assessment attempted before exhaustion. Graph edges remain adaptive.

`current_stage` identifies the next goal to execute at each graph boundary and remains
`validation` on completion. `iteration_count` counts completed validation assessments,
`loop_count` counts validation-requested refinement, and `stage_visits` counts completed
stage decisions, including cycles that never reach validation. A resource handover
does not count as a completed stage and is allowed only once per run; correction calls
are bounded separately and consume the same model budget. Tool-failure codes belong
to this same state, so changing stage-local tools cannot lose an unresolved outage.
Detached node updates prevent later stages from mutating earlier streamed values or
the caller's input. These are temporary copies, not retained diagnostic history.

Final candidates are revalidated against the existing `StructuredDiagnosis` contract,
including finding/hypothesis links. Run and learner identity must match the request.
The main subject comes from the configured triggering-evidence source, not the model;
finding subjects must occur in mapped source artifacts. Every supporting and
contradicting source must be known to this run. These structural checks cannot prove
that a natural-language conclusion follows from evidence; that remains a model
quality/evaluation concern, not a claim of educational accuracy.

`RunReport` returns the domain outcome, cited artifacts and their provenance
dependencies, and bounded aggregate counts. For unresolved outcomes it also returns
the current validated `partial_findings` and `partial_hypotheses`, explicitly not an
accepted diagnosis. `resource_limit_reason` distinguishes resource interruption from
ordinary educational uncertainty. The synthetic CLI includes these fields. It excludes unused retrieved results,
stage conversations, private reasoning, and chronological diagnostic attempts.
There is no database, checkpointer, store, raw-agent logger, or persistence of working
state. Both graph and inner agent invocations disable LangSmith tracing. Local inner
messages are discarded when the stage finishes. Persistence of the approved outcome
and supporting artifacts is the caller's responsibility under the separate persistence
task; existing evidence identities remain references, not a new evidence store.

## Prompt strategy

`application/orchestration/prompts/v1/` contains a shared policy and four goal files.
Each goal defines its responsibility, typed output, relevant case context, available
tools, evidence/confidence limits, and behavior under missing or conflicting evidence.
Prompt files ship as package data. Provider substitution does not edit them.

`prompts.py` supplies the current case, retrieved artifacts, source descriptions,
latest public validation and remaining limits. Evidence and learner text are explicitly
untrusted data. No reasoning transcript is requested or persisted.

## Information and capability lifecycle

1. Composition supplies an `InformationGateway`, named `InformationBinding` mappers,
   an anchor source, the existing `CapabilityRegistry`, and executable bindings.
2. `get_information(source)` selects only a configured source. The gateway's existing
   default behavior still retrieves all sources; optional selection preserves the
   `DiagnosticInformationSource.get_information(request) -> dict` contract.
3. Each source-specific mapper converts that source's arbitrary dictionary into the
   **existing** `DiagnosticArtifact` contract. There is no universal source payload
   schema. The anchor mapper must cite the triggering evidence and resolve its subject.
   Additional source mappers own trustworthy evidence identities and provenance.
4. `discover_capabilities()` returns metadata and concrete input/output schemas only
   for registered capabilities with explicitly installed execution bindings. Registry
   objects and arbitrary application methods are never exposed to the model.
5. `invoke_capability` validates arguments and retrieved references, then runs the
   adapter's applicability check. Its `input_sources` function derives actual provenance
   from validated inputs and a detached case view; model-declared sources must agree.
   Execution and Pydantic output validation precede artifact registration. The artifact
   records concrete inputs, actual source references, producer and implementation version.
6. Tool failures return small safe error codes, not raw exceptions or learner payloads.
   A retry that succeeds clears its dependency failure. An unresolved result with an
   unrecovered dependency failure is a technical `DiagnosisExecutionError`; failures are
   never recast as lack of learner knowledge. A completed, independently supported
   candidate may still be accepted when an optional tool failed.

Capabilities and source mappers are trusted application code. A mapper must not invent
identities; an adapter must derive inputs from retrieved data and enforce its research
applicability rules. The synthetic adapter reads an artifact ID, not invented numeric
measurements supplied by the model. Production KT adapters remain their own workstream.

## Limits and errors

### Budget-aware final assessment

Stage context and refreshed model-request context expose remaining model calls, tool
attempts, completed-stage slots, execution seconds and estimated dollar reservations.
`prioritize_existing_evidence` warns before reaching the limits. `RunBudget` compares
remaining stage/model capacity to a lower bound for the current mandatory progression;
it does not select diagnostic tools or educational conclusions. Monetary planning
conservatively allows the configured maximum input/output envelope for each remaining
stage. This may favor finalization earlier than the actual bill would require.

When normal progression no longer fits, and evidence plus assessment resources remain,
the existing node executor hands the case to the existing Validation node. The same
mechanism protects the last model call even within an inner tool loop. Cooperative
investigation/model timeouts leave `final_assessment_seconds` (default 10 seconds) for
assessment when evidence already exists. A single response and one completed-stage
slot are the minimum reserve, not a guarantee of sufficient time or repair attempts.
The provider's actual response is still required; the application never invents one.

Resource-finalization supplies `finalization_reason`, exposes no investigation tools,
and allows only acceptance of a valid existing candidate or an unresolved assessment.
Acceptance still checks WHAT, WHY, current synthesis, all links, identities and source
provenance. The only prerequisite exception permits **unresolved Validation with
retrieved evidence before WHAT completes**, without marking WHAT or WHY complete.
Existing stage-output schemas and all domain contracts remain unchanged.

Resource-limited unresolved reasons begin with `Investigation interrupted by resource
limits` and explicitly state that this is not evidence of a learner deficit. The
agent describes the unestablished scope; valid partial claims and relevant artifacts
remain available to callers. An unrecovered tool outage still raises a technical
error. If no evidence, assessment slot, affordable model request or execution time
remains, the run raises `ResourceLimitError`; exhaustion itself never fabricates an
outcome. Repeated invalid final assessments also fail with the bounded correction error.

Tool batches are budgeted before dispatch, including malformed/unknown tool requests.
Admitted attempts count even if invalid or a later batch reservation prevents dispatch;
requests rejected beyond the hard cap are not dispatched or charged beyond that cap.
Model-call reservations include the refreshed budget context, remain charged on errors,
and are not reset by corrections or resource handover. A provider exceeding its usage
reservation remains a hard error, not an invitation to make additional model calls.

Limitations: estimates cannot prove semantic evidence sufficiency or predict latency.
The initial evidence acquisition has no useful unresolved fallback until it succeeds.
Oversized final context, repeated malformed final responses, too little remaining
time/cost, or non-cooperative I/O can still prevent finalization. No reserve guarantees
a completed assessment, and this work does not validate live-model behavior.

`RunLimits` applies across all four stages and every inner agent loop:

- Stage visits, model requests (including retries), and tool dispatch attempts.
- A run deadline, provider request timeouts, and a maximum generated token count.
- Input-size preflight and a dollar reservation limit with explicitly supplied prices.
- Bounded transient provider retries; authentication/configuration errors fail immediately.

Tool batches reserve their complete budget before dispatch, including malformed and
unknown requests. Structured-response calls count as model calls, not instrument
invocations. Schema correction uses the prebuilt loop and the same shared limits.

Input reservations conservatively count serialized UTF-8 bytes for messages, system
prompt, tool/response schemas plus a framing allowance; output reservations use the
configured generation cap. Prices must cover the selected provider/model's token
charges (including reasoning tokens where applicable). Reservations are not measured
bills, and failed calls are not refunded because provider billing may be unknown.
Observed usage exceeding the reservation fails closed for further execution. Providers
with non-token fees, unusual tokenization or hidden server-side work need their own
budget adapter before use; a provider account spending limit remains the external
billing backstop. No current model pricing is hardcoded.

Deadline expiration, stage/call/cost exhaustion, repeated invalid decisions, and provider
failures raise typed **technical errors**, never fabricated unresolved diagnoses.
Synchronous information sources are run in a worker thread to avoid blocking the event
loop. Python cannot kill a blocked source thread: adapters must use bounded I/O and
cooperative cancellation. The caller stops awaiting at the run deadline, but an
uncooperative source can continue and delay `asyncio.run` executor shutdown. Capability
adapters must also be asynchronous/cooperative and avoid blocking the event loop.

## Installation and execution

From the repository, with Python 3.11+:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[dev,openai,anthropic,deepseek,google_genai,groq]'
.venv/Scripts/python.exe -m pytest -q -m 'not live'
```

The local pre-existing `.venv` was unusable during implementation; verification used
an isolated `.cache/scrum17-venv` with Python 3.13.3. This does not change the supported
Python requirement or overwrite the user's existing environment.

Set configuration as JSON; credentials remain in the named environment variable:

```powershell
$env:ALI_DIAGNOSIS_MODEL_CONFIG = '{"provider":"openai","model":"YOUR_MODEL_ID","api_key_env":"OPENAI_API_KEY"}'
# Supply actual conservative prices for your selected provider/model:
$env:ALI_DIAGNOSIS_LIMITS = '{"input_usd_per_million":1,"output_usd_per_million":2,"max_cost_usd":1,"max_input_tokens":64000,"max_output_tokens":4096,"max_seconds":180}'
python -m ali_diagnosis.infrastructure.synthetic_cli success
```

The prices above are illustrative, **not provider price quotes**. Running the CLI
invokes a real model; deterministic tests do not require credentials or the CLI.

### Provider configuration

Install only the extras you need. All providers use `init_chat_model` and the same
`LangChainStageAgent`, `create_agent` loop and `ToolStrategy` stage output schemas.
There are no provider-specific diagnostic agents, prompts or graph routes.

| Provider | Extra / package | Tested package version | Conventional credential variable |
| --- | --- | --- | --- |
| `openai` | `openai` / `langchain-openai` | 1.7.2 | `OPENAI_API_KEY` |
| `anthropic` | `anthropic` / `langchain-anthropic` | 1.7.6 | `ANTHROPIC_API_KEY` |
| `deepseek` | `deepseek` / `langchain-deepseek` | 1.1.1 | `DEEPSEEK_API_KEY` |
| `google_genai` | `google_genai` / `langchain-google-genai` | 4.4.2 | `GOOGLE_API_KEY` |
| `groq` | `groq` / `langchain-groq` | 1.1.3 | `GROQ_API_KEY` |

Choose **one** configuration below and replace `YOUR_TOOL_CALLING_MODEL_ID` with a
currently available model supporting custom function/tool calls. The placeholders
are not model recommendations or claims of live acceptance. Put the actual key in
the named environment variable using your normal secret-management mechanism; do
not put it in the configuration JSON. A custom `api_key_env` name is also supported.

```powershell
# OpenAI
$env:ALI_DIAGNOSIS_MODEL_CONFIG = '{"provider":"openai","model":"YOUR_TOOL_CALLING_MODEL_ID","api_key_env":"OPENAI_API_KEY"}'
# Anthropic
$env:ALI_DIAGNOSIS_MODEL_CONFIG = '{"provider":"anthropic","model":"YOUR_TOOL_CALLING_MODEL_ID","api_key_env":"ANTHROPIC_API_KEY"}'
# DeepSeek (non-thinking tool mode)
$env:ALI_DIAGNOSIS_MODEL_CONFIG = '{"provider":"deepseek","model":"YOUR_TOOL_CALLING_MODEL_ID","api_key_env":"DEEPSEEK_API_KEY"}'
# Gemini Developer API
$env:ALI_DIAGNOSIS_MODEL_CONFIG = '{"provider":"google_genai","model":"YOUR_TOOL_CALLING_MODEL_ID","api_key_env":"GOOGLE_API_KEY"}'
# Groq
$env:ALI_DIAGNOSIS_MODEL_CONFIG = '{"provider":"groq","model":"YOUR_TOOL_CALLING_MODEL_ID","api_key_env":"GROQ_API_KEY"}'
```

The factory passes the selected credential explicitly as `api_key` for all five
adapters; missing, empty or whitespace-only credentials fail before initialization.
It does not fall back to other credential variables. Initialization errors are
sanitized. `request_timeout_seconds` defaults to 60 and is capped by the run deadline.
`RunLimits.max_output_tokens` sets the generation cap at initialization and on every
model call. Gemini's constructor accepts `max_tokens`, but its call-time parameter is
`max_output_tokens`; the factory supplies that parameter name to the existing agent
middleware. No Diagnosis policy depends on the provider.

SDK retries are disabled so only the shared application budget owns retry attempts:
the Google adapter requires `max_retries=1` (one total attempt), while the other four
use `max_retries=0`. Gemini converts the configured timeout from seconds to SDK
milliseconds internally. The transport tests check actual timeout/token settings and
one HTTP attempt on a simulated server error for every provider.

Optional `base_url` is forwarded to each adapter. Omit it for the provider default;
custom endpoints must implement that provider's native protocol. A Gemini endpoint
must accept `generateContent`, an Anthropic endpoint must accept Messages, and the
other three use Chat Completions. An OpenAI-compatible URL alone does not make it a
Gemini or Anthropic endpoint. For example, add these fields to your selected JSON:

```json
{"base_url":"https://your-compatible-gateway.example","request_timeout_seconds":30}
```

### Model compatibility and limits

The requirement is **custom tool calling**, including round-tripping tool results
and generating the four stage-output tools. Native JSON-schema output alone is not
sufficient. `ToolStrategy` supplies structured stages through function calls and
Pydantic validation; the engine does not enable a provider's native JSON-output mode.
Local LangChain profile metadata explicitly declaring `tool_calling=false` causes
initialization to fail. Missing or positive metadata is not live certification:
model aliases, deployment permissions and provider schema support can change.

- OpenAI / Anthropic: select a tool-capable chat/Messages model. Non-chat endpoints,
  older models without tools, and models requiring unsupported request options are
  outside this configuration's supported subset. No temperature or special reasoning
  configuration is imposed. Custom gateways still need model-specific acceptance.
- DeepSeek: the factory explicitly requests **non-thinking mode** via
  `extra_body.thinking.type=disabled`. Thinking-mode tool calls require replaying
  `reasoning_content`; the tested adapter parses that field but does not serialize
  it into subsequent requests. Thinking-only models/deployments are therefore not
  supported here. Ordinary tool-based stage output does not use DeepSeek's beta
  strict-schema mode. See [DeepSeek tool calls](https://api-docs.deepseek.com/guides/tool_calls/)
  and [thinking-mode requirements](https://api-docs.deepseek.com/guides/thinking_mode/).
- Gemini: this factory supports **Developer API key authentication**, not Vertex AI,
  service accounts or ADC. Set `GOOGLE_GENAI_USE_VERTEXAI` and
  `GOOGLE_GENAI_USE_ENTERPRISE` to false or leave them unset; conflicting true/1 flags
  fail before SDK construction. Select a model supporting custom function calls;
  image/audio-only models are not interchangeable. Gemini 3 tool round-trips require
  thought signatures, retained by the existing prebuilt loop and verified with a
  synthetic signature in transport tests. Gemini can discard unsupported JSON-schema
  keywords, so application validation remains authoritative. See the
  [LangChain Gemini integration](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai)
  and [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling).
- Groq: choose a model listed with **local tool-use support**, such as the currently
  documented `llama-3.3-70b-versatile`; support varies by model. Native Structured
  Outputs and hosted built-in tools are distinct features and do not substitute for
  the local tools this engine needs. See the [Groq tool matrix](https://console.groq.com/docs/tool-use/overview).

New dependency floors were verified against published package metadata and installed
together: DeepSeek >=1.1.1,<2, Google GenAI >=4.4.2,<5, Groq >=1.1.3,<2. Verification
used Python 3.13.3, LangChain 1.4.6, langchain-core 1.6.12 and LangGraph 1.2.16; `uv pip
check` passed. All extras also resolve for the declared Python 3.11 minimum (dependency
resolution only, not a Python 3.11 test run). These are tested versions and compatible
ranges, not a promise that every future release or hosted model will behave identically.

## Test evidence and remaining acceptance

Before this refactoring, the deterministic baseline was **84 passed, 9 live tests
deselected**. Current refactoring verification is recorded in the architecture review.
Live-model acceptance remains deferred; the refactoring makes no paid model calls.

Stage-navigation verification (2026-10-22): **95 passed, 9 live tests deselected**
using `ALI_DIAGNOSIS_RUN_LIVE=0` and `pytest -q -m 'not live'` (baseline: 81 passed).
The added deterministic cases cover skipped WHY, rejected transitions without state
changes, renewed prerequisites after claim revisions, acceptance revalidation,
evidence-driven WHAT/WHY revisits, unsupported WHY returning unresolved, and fresh
synthesis after information/capability results. The four self-loop tests enter their
goals through valid prerequisites and verify termination at the shared stage limit.

The default suite uses fake stage/model outputs, real LangGraph/prebuilt-agent loops,
and real SDK serializers for all five providers with controlled HTTP transports. It checks
adaptive routing, refinement, contracts, provenance, source selection, capability
execution/recovery, schema repair, budget limits, safe errors and dependency direction.
HTTP fixture tests verify provider-adapter substitution, **not live model quality**.

Provider-extension verification (2026-10-22): **148 passed, 9 live tests deselected**
with all five extras installed, `ALI_DIAGNOSIS_RUN_LIVE=0` and `pytest -q -m 'not live'`.
The configuration/adapter subset passed 68 tests. Each provider completed the same
synthetic four-stage diagnosis through its real SDK serializer and mocked HTTP
responses, and made exactly one HTTP attempt for a simulated server failure with
application retries disabled. No live provider requests were executed. Live-model
behavior, hosted schema acceptance and diagnostic quality remain unverified.

Decision-recovery and budget-finalization verification (2026-10-23): **173 passed,
9 live tests deselected**, using `ALI_DIAGNOSIS_RUN_LIVE=0` and
`pytest -q -m 'not live'` (baseline: 148 passed). Deterministic coverage includes
bounded correction with retained evidence and atomic state updates, renewed WHY
after WHAT revisions, tight-budget validated success, resource-limited unresolved
outcomes, missing-evidence errors, inner model/tool accounting, reserved assessment
time after initial retrieval, and strict provider usage-envelope enforcement.
No live API calls were made; live-model behavior remains unverified.

Real-model tests are opt-in and cover success, insufficient evidence, contradictions,
additional retrieval, capability selection, refinement, tool failure and iteration
limits. The refinement assertion requires an actual revisit; a linear success alone
does not pass. A ninth test exercises an alternate provider when configured.

```powershell
$env:ALI_DIAGNOSIS_RUN_LIVE = '1'
# Optional second provider, required for live substitution acceptance:
$env:ALI_DIAGNOSIS_ALTERNATE_MODEL_CONFIG = '{"provider":"anthropic","model":"YOUR_MODEL_ID","api_key_env":"ANTHROPIC_API_KEY"}'
python -m pytest tests/test_live_diagnosis.py -q
```

Each scenario receives its own run budget, so the suite's worst-case reservation is
the number of enabled cases multiplied by `max_cost_usd`. These tests call real models
over synthetic learner evidence and mock instruments. They make no claims about
educational diagnostic accuracy. They are not accepted as passing merely because
they skip or because deterministic tests pass. At implementation time, no Diagnosis
provider/model and live-test budget had been supplied; real-model acceptance remains
unverified until these tests run successfully with explicit configuration.

Framework references: [prebuilt structured output](https://docs.langchain.com/oss/python/langchain/structured-output),
[middleware hooks](https://docs.langchain.com/oss/python/langchain/middleware/custom).
