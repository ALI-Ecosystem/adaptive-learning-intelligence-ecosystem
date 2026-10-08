# Learner State Knowledge — Architecture Specification

**Module:** Learner State (blocks 4 & 5 of the system pipeline)
**Owner:** Kody
**Version:** 0.5 — concept-id stability contract with the Domain Knowledge module (§11.4); late-evidence policy decided (§6.5); `getReadiness` made exact (§7.3); RLS hardened (§9.3.1); erasure specified column by column (§9.4); single-tenant (§11.3 #4); partial credit fixed (§3.4); exposure layer added (§3.10); Prisma as access layer (App. C)
**Date:** 2026-10-06

> **Changes in v0.2** (all four items raised in review):
> 1. **Decay logic de-duplicated** — the SQL decay view is removed; `DecayFunction` in the application layer is now the single source of truth (§5.3). Risk R6 eliminated rather than mitigated.
> 2. **Ontology replication** — a local, event-synchronised read-model replica replaces the synchronous cross-service graph call on the ingest path (§5.5).
> 3. **Evidence payload signing** — Ed25519 signatures verified at ingest, extending T1 mitigation from perimeter trust to Zero Trust, plus non-repudiation (§9.2.1).
> 4. **Lock key widened** to 64-bit via `hashtextextended` (§6.2.1). An external lock manager was evaluated and **rejected**; the analysis is recorded there.
>
> **Changes in v0.3** — implementation plan realigned to the above (§10):
> 5. Signature verification moved into **P3** (write path), with its envelope schema pulled forward to **P0** so the Evidence team is not blocked; KMS integration remains in P8.
> 6. New **P4.5** delivers the ontology replication *seam* (local table, change consumer, reconciliation), separating it from the Diagnosis-facing API work in P4.
> 7. **P1 reduced** — one decay implementation, no cross-language consistency harness.
> 8. Every phase now carries an **exit criterion**, and each test level is bound to a phase gate (§10.2). Concurrency testing moved from P8 to **P3**.
>
> **Changes in v0.4** — five defects found in review of the implementation roadmap:
> 9. **Numeric determinism.** `α`, `β` and the priors move from `DOUBLE PRECISION` to `NUMERIC(12,6)`, with quantisation performed **once at the persistence boundary** — not inside the functional core (§5.6). Without this, replay determinism (AP-1, P7) is not achievable; with it done in the wrong layer, the `n`-conservation invariant of Appendix B.2 breaks.
> 10. **`outcome_digest` is now defined**, not assumed: an explicit ordered field list over canonical decimal strings (§6.2). A digest over raw floats is not reproducible across Node versions or summation orders.
> 11. **`tenantId` moves into the signed payload** (§6.1). Replay must be a pure function of the log; deriving tenancy from `attemptId` at replay time re-couples reconstruction to another service's present state. The *physical* `tenant_id` column stays deferred — AP-1 makes that retrofit a replay, so it is the cheap half of the decision (§11.3 #4).
> 12. **Signature input specified exactly** — Ed25519 over the canonical bytes, **no pre-hash** (§9.2.1). "SHA-256 then sign" and "sign directly" are both defensible; silently mixing them across two teams means nothing ever verifies.
> 13. **The concurrency test is now a proof, not a timing measurement** (§10.2), and a **Definition of Done** (§10.4) binds each acceptance criterion to the phase that delivers it. A compressed roadmap will drop a phase while keeping the claim it was supposed to earn — replay determinism without P7 is the standard instance — and the binding makes that visible in one place.
>
> **Changes in v0.5** — guided review, 2026-10-06/07; closes §11.3 #1, #4, #5, #6:
> 14. **Concept-id stability is now a contract, not an assumption** (§11.4, LS-CR-001). A `concept_id` is immutable and never deleted; structural changes (split, merge, deprecate, re-identify) arrive as explicit operations with an old→new mapping in the `OntologyChanged` changeset. §6.6's migration table is only executable under this contract — without the mapping, a split is indistinguishable from a deletion plus two unrelated new concepts, and the learner's accumulated evidence is silently orphaned. Risk R2's mitigation now points at the contract.
> 15. **Late-evidence policy decided** (§6.5, closes §11.3 #5). Out-of-order evidence up to `late_bound` (7 days) is applied **exactly**, by re-folding the affected tuples in `occurred_at` order; older evidence is recorded and deferred, never silently dropped. v0.4's default — "append with reduced weight" — is **removed**: it named no weight, so it was not implementable, and the prototype has no offline client, so nearly all lateness is seconds of delivery reordering, where the exact strategy costs almost nothing. `processed_event` gains `disposition` and `deferred_payload`; `transition_type` gains `REORDER`; §3.9 gains `late_bound`.
> 16. **`getReadiness` made exact** (§7.3). `ready` is now *defined* — every prerequisite at or above `minEdgeStrength` passes the §3.6 `MASTERED` test — so it is a fact about the learner and stays inside the §1.3 boundary. `minEdgeStrength` is a new optional parameter: which edges count is the caller's policy (the Adaptive Engine's `σ_min`), and this module had no way to know it. `readinessScore` is **removed**: it had no formula anywhere and no consumer read it. **Follow-up outside this document:** the Adaptive Engine's G3 must pass `σ_min` as `minEdgeStrength`.
> 17. **RLS hardened** (§9.3.1). v0.4 placed RLS on `learner_concept_state` only; it now covers every learner-scoped table, including `state_transition` (the full history `getHistory` reads). Two silent-bypass paths are closed: the table owner (tables are `FORCE`d; the service connects as non-owner roles `ls_api` / `ls_ingest`) and connection-pool leakage (the learner variable is set transaction-locally with `set_config(…, true)`). An unset variable returns no rows — fail closed.
> 18. **Erasure specified column by column** (§9.4). v0.4 said "personally identifying fields are encrypted" without naming any, so P2's encrypted-column layout was unbuildable. Now: `learner_id` stays a plaintext pseudonym (it is the key, the RLS predicate and the lock key); `item_id`, `evidence_signature` and `deferred_payload` become DEK-encrypted `BYTEA`; snapshot tables are hard-deleted and the cache purged. Three limitations are stated rather than hidden: the result is strong pseudonymisation, not anonymisation (timestamps stay plaintext); erasure is a cross-module workflow; backups can resurrect a destroyed DEK.
> 19. **Partial credit fixed** (§3.4 step 3, closes §11.3 #6). `PARTIAL` is now a credit-weighted mixture of the correct and incorrect responsibilities. v0.4 treated it as a correct answer at reduced weight, which made every partial answer positive evidence: twenty consecutive 10% answers reached mastery 0.734. Under the mixture: 0.146. Binary outcomes are bit-identical to v0.4. Appendix A and `verify_mastery_model.py` updated; four new checks.
> 20. **Single-tenant** (§11.3 #4 closed). No physical `tenant_id` column; `tenantId` stays in the signed envelope.
> 21. **Exposure layer added** (§3.10, R9) — proposed in team review. The module now records *what the learner was taught or shown* separately from *what the system believes they know*. The two are different facts calling for different interventions: "never taught" → teach; "taught, not acquired" → teach differently. Before v0.5 both read as the same low mastery. Exposure is a second **data layer over the same shared ontology**, not a second graph, and it **never** moves `α`/`β`. New `ExposureEvent` input (§6.1a), new tables `exposure_event` (log) and `learner_concept_exposure` (snapshot), new `exposure` field on `ConceptStateView`; RLS and erasure extended to both tables; request **LS-CR-002** to the Evidence Module.
> 22. **"Personal Knowledge Graph" defined as a logical overlay** (§5.1). The ontology is stored once; per learner, only numbers keyed by `concept_id` are stored. Learner input never changes ontology *structure* — only the Domain Knowledge module creates nodes or edges.
> 23. **Prisma adopted as the access layer** (Appendix C.2) to match the team standard, replacing Kysely/Slonik. Prisma's generated API is **not** used on the write path or for RLS-scoped reads: those statements are raw SQL on the `tx` handle of one interactive `$transaction`, so the idempotency claim, advisory lock and `set_config(…, true)` share one connection and one transaction. Migrations are Prisma Migrate files with hand-written SQL. Two runtime clients with different connection strings (`ls_api`, `ls_ingest`); migrations run as `ls_owner`.
> 24. **`outcome_digest` written in two steps** (§6.2, found while building SCRUM-34). The claim runs before the update (§6.3 step 2), but the digest is computed after it (P3 step 6), so the claim cannot supply it. The claim inserts the sentinel `'PENDING'`; the persist step overwrites it with the real digest **in the same transaction**, so `'PENDING'` is never visible after commit. The DDL is unchanged.
>
> **Technology stack of record:** see **Appendix C**.

**Target:** academic prototype (single Postgres, in-process events), with a documented migration path to the distributed target architecture

---

## 1. Purpose and Scope

### 1.1 What this module is

The Learner State module maintains, for every learner, a **probabilistic, temporal, per-concept estimate of what that learner knows** — including how confident the system is in that estimate, and which misconceptions the learner appears to hold.

It is the only *stateful* component in the pipeline. The Domain Knowledge module is effectively static reference data; the Diagnosis Engine and Adaptive Learning Engine are stateless consumers. Everything downstream reads from here.

> **Consequence:** the public read contract of this module (§7) is on the critical path for two other teams. It must be frozen early, even before the internals are built.

### 1.2 Responsibilities (in scope)

| # | Responsibility | Corresponding doc block |
|---|---|---|
| R1 | Consume validated evidence events and update learner knowledge estimates | 4 — Knowledge State Updater |
| R2 | Apply temporal decay / forgetting to estimates | 4 — Temporal State Updater |
| R3 | Track and score active misconceptions | 4 — Misconception Detector |
| R4 | Handle schema and ontology version migration of stored state | 4 — State Migration Handler |
| R5 | Persist per-concept knowledge state across cognitive dimensions | 5 — Concept Knowledge State, Cognitive Dimensions |
| R6 | Quantify and expose uncertainty as a first-class value | 5 — Uncertainty |
| R7 | Retain an auditable history of state transitions | 5 — State History |
| R8 | Serve read queries to Diagnosis and Adaptive engines at low latency | — (implicit) |
| R9 | Record what each learner has been **exposed to** (taught, shown, practised), separately from what they are believed to know (§3.10) | 5 — Concept Knowledge State *(v0.5)* |

### 1.3 Explicitly out of scope

These are **not** this module's job, and the design must actively resist absorbing them:

- **Deciding what to teach next** → Adaptive Learning Engine
- **Explaining *why* a gap exists** (root cause) → Diagnosis Engine
- **Defining the concept ontology or prerequisite edges** → Domain Knowledge Module
- **Grading a submission / extracting evidence from a raw answer** → Evidence Module
- **Item difficulty calibration** → Task/Assessment Module

The boundary rule: **Learner State answers "what is true about this learner?", never "what should we do about it?"** The moment a `recommendNext()` method appears in this service, the boundary has been violated.

### 1.4 Upstream / downstream contracts

```
  ┌──────────────────────┐        ┌──────────────────────┐
  │ 1. Domain Knowledge  │        │ 2. Task / Assessment │
  │    (concepts,        │        │    (items, difficulty│
  │     prerequisites,   │        │     distractor→      │
  │     misconceptions)  │        │     misconception)   │
  └──────────┬───────────┘        └──────────┬───────────┘
             │ read-only, cached             │
             │ IDomainGraph port             │
             ▼                               ▼
  ┌────────────────────────────────────────────────────┐
  │              3. Evidence Module                    │
  │        emits: validated EvidenceEvent              │
  └────────────────────────┬───────────────────────────┘
                           │  EvidenceEvent (§6.1)
                           ▼
  ╔════════════════════════════════════════════════════╗
  ║   4. LEARNER STATE ORCHESTRATOR   (this module)    ║
  ║   ┌──────────────────────────────────────────┐     ║
  ║   │ Ingest → Idempotency → Lock → Update →    │     ║
  ║   │ Propagate → Persist transition → Snapshot │     ║
  ║   └──────────────────────────────────────────┘     ║
  ║                       ↓                            ║
  ║   5. LEARNER STATE STORE                           ║
  ║   (current snapshot + append-only history)         ║
  ╚════════════════════════┬═══════════════════════════╝
                           │  read API (§7)
             ┌─────────────┴─────────────┐
             ▼                           ▼
  ┌────────────────────┐      ┌──────────────────────┐
  │  Diagnosis Engine  │      │ Adaptive Learning    │
  │  (Gap Detector,    │      │ Engine (Target       │
  │   Analyzers)       │      │ Selection, Ranker)   │
  └────────────────────┘      └──────────────────────┘
```

---

## 2. Architectural Principles

Five decisions drive the entire design. Each is stated with the alternative that was rejected and why.

### AP-1 — State is a projection of an append-only evidence log, not a mutable row

**Decision:** the system of record is an immutable, append-only sequence of state transitions. `learner_state_current` is a *materialized read model* derived from it, and can be dropped and rebuilt at any time.

**Rejected alternative:** a single mutable `learner_state` table updated in place, with an optional audit trigger.

**Rationale:**
- `State History` (block 5) and `Provenance` (block 3) are stated requirements. If history is a side-effect of mutation, it will drift out of sync with the state it claims to describe.
- The mastery model **will** change during the project (BKT parameters will be retuned, weights adjusted). With a log, retuning means *replay*; without it, all existing learner state becomes silently invalid.
- The Evaluation/Validation system requires `Confidence Calibration` and `Strategy Comparison` — both of which mean running two different update algorithms over the same evidence. Only possible with a replayable log.

**Cost:** roughly 2× write volume and more code than a naive UPDATE. Accepted.

### AP-2 — Exactly one writer per learner at any instant

**Decision:** all state mutations for a given `learner_id` are serialized.

**Rationale:** Bayesian updates are **non-commutative** once decay is involved — applying evidence A then B with a time gap gives a different result than B then A. Concurrent writers produce lost updates and non-reproducible state, which destroys replay determinism (AP-1).

**Implementation:**

| Phase | Mechanism |
|---|---|
| Prototype | `pg_advisory_xact_lock(hashtextextended(learner_id, 0))` at the start of the update transaction — 64-bit key, see §6.2.1 |
| Production | Kafka topic partitioned by `learner_id` → one consumer per partition |

These are the *same guarantee* at two scales, which is why the prototype is an honest rehearsal of the target design rather than a throwaway.

### AP-3 — Knowledge is a distribution, never a scalar

**Decision:** the stored unit is a Beta distribution `(α, β)`, not a float in `[0,1]`.

**Rationale:** `Uncertainty` is a required output (block 5) and the Diagnosis Engine's Gap Detector must distinguish two situations that a scalar cannot:

| | mastery = 0.50 | interpretation |
|---|---|---|
| Beta(1, 1) | 0.50, sd ≈ 0.29 | **we have no idea** → send a diagnostic probe |
| Beta(20, 20) | 0.50, sd ≈ 0.08 | **genuinely partial mastery** → send instruction |

With a scalar these are indistinguishable, and the Adaptive Engine would treat them identically — which is pedagogically wrong. Uncertainty falls out of the distribution for free rather than requiring a parallel bookkeeping mechanism.

### AP-4 — Decay is computed at read time, never by a batch job

**Decision:** store `(α, β, last_evidence_at)` and apply the forgetting function as a pure function during reads.

**Rejected alternative:** a nightly cron that iterates all learners and decays their state.

**Rationale:**
- The batch job is `O(learners × concepts)` per night, for data that in most cases nobody will read.
- It is a correctness trap: a missed run, a job that dies halfway, or a learner inactive for six months all produce wrong state.
- Read-time decay is `O(1)`, always exactly correct for the current instant, and — critically — is a **pure function**, therefore trivially unit-testable and replay-deterministic.

### AP-5 — Learner state lives in Postgres; the ontology lives in the graph

**Decision:** do not store learner state in the graph database.

**Rationale:**

| | Domain ontology | Learner state |
|---|---|---|
| Write pattern | rare, bulk, curated | continuous, per-event |
| Read pattern | multi-hop traversal | point lookup by key |
| Data shape | topology | numeric time series |
| Cardinality | thousands of nodes | learners × concepts × levels |
| Best fit | **graph DB** | **relational** |

Writing a `:KNOWS {mastery}` edge per learner per concept turns the graph into a high-churn write target, which is precisely its weakest workload, and mixes slow-changing reference data with fast-changing personal data in one blast radius.

The one operation that genuinely wants a graph — prerequisite propagation — is **deliberately bounded to 1–2 hops** (§6.4), so it does not require graph-native performance.

**Access is via a port, not a driver.** The module depends on an `IDomainGraph` interface (§5.4). Whether the ontology is served by Neo4j, or by Postgres recursive CTEs in the prototype, is invisible to this module and can change without touching it.

---

## 3. The Mastery Model — Beta-Bernoulli with BKT Correction

### 3.1 Model selection

Three candidates were considered:

| Model | Uncertainty | Explainable | Cold start | Notes |
|---|---|---|---|---|
| **Beta-Bernoulli + BKT** | native (variance) | yes | works day one | chosen |
| IRT / Elo | via SE(θ) | partly | needs item calibration | revisit once item response data exists |
| DKT (neural) | poor | **no** | needs large corpus | incompatible with Diagnosis Engine's explanation requirement |

**Decision:** Beta-Bernoulli posterior updating, corrected for guessing and slipping using BKT's emission parameters, with a BKT-style learning transition.

Rationale: it gives calibrated uncertainty for free (AP-3), every update step is a single arithmetic expression that can be shown to a human — which the Explanation Builder in the Diagnosis Engine depends on — and it requires no training corpus, which we do not have.

**Honest limitation to state in the paper:** this is a *moment-matching approximation*, not exact inference over the BKT hidden Markov model. We maintain a Beta belief over the knowledge probability rather than the exact HMM posterior. Exact BKT filtering tracks only a point probability `P(L)` and carries no uncertainty; our formulation trades exactness for a usable variance estimate. This trade-off should be named explicitly rather than glossed over.

### 3.2 The state unit

The atomic record is **not** one row per concept. It is:

```
(learner_id, concept_id, cognitive_level)  →  Beta(α, β)
```

The `cognitive_level` dimension is mandatory, not optional. The Diagnosis Engine's `Cognitive Gap Analyzer` asks "is there a gap between remembering, understanding and applying?" — a question that is unanswerable if state is collapsed to one number per concept.

Cognitive levels (reduced Bloom taxonomy, 4 levels):

| Level | Ordinal | Meaning |
|---|---|---|
| `REMEMBER` | 1 | recalls the definition/fact |
| `UNDERSTAND` | 2 | explains it in own terms, recognises examples |
| `APPLY` | 3 | uses it to solve a standard problem |
| `ANALYZE` | 4 | decomposes, transfers to a novel situation |

### 3.3 Prior

An unobserved `(learner, concept, level)` tuple is **never stored** (§8.2 — sparsity). It is materialised on demand from a prior:

```
Beta(α₀, β₀)   with   α₀ + β₀ = n₀ = 2      (weak prior, ~2 pseudo-observations)
```

The prior mean is derived, in order of preference:

1. **Graph-informed** — if the learner has mastered concepts that this concept is a prerequisite *for*, raise the prior. If prerequisites of this concept are unmastered, lower it. (Requires `IDomainGraph.getNeighbours`.)
2. **Cohort-informed** — mean mastery of this `(concept, level)` across the learner's cohort.
3. **Flat** — `Beta(0.6, 1.4)`, i.e. mean 0.3, reflecting "probably not known yet".

For the prototype, implement (3) with (1) behind a feature flag. Do not start with cohort priors — they create a hidden coupling between learners that complicates both privacy and replay determinism.

### 3.4 Evidence update

An `EvidenceEvent` carries an outcome and a weight. Update proceeds in a fixed order — **the order matters and must not be rearranged**:

**Step 1 — bring state to the present (decay).** See §3.5. Produces `(α', β')`.

**Step 2 — current belief.**

```
p = α' / (α' + β')
```

**Step 3 — responsibility (was this observation actually caused by knowing?).** BKT's emission correction with slip `s` and guess `g`:

```
correct   observation:   q = p(1−s) / [ p(1−s) + (1−p)g ]
incorrect observation:   q = p·s    / [ p·s    + (1−p)(1−g) ]
```

`q` is the posterior probability that the learner knew the concept, given what we saw. This is what prevents a lucky guess on a 4-option multiple-choice item from being counted as full evidence of mastery.

**Partial credit (v0.5).** Every outcome is mapped to a credit `c ∈ [0, 1]` — `CORRECT` → 1, `INCORRECT` → 0, `PARTIAL` → `partialCredit` — and the responsibility is the credit-weighted mixture of the two cases above:

```
q = c · q_correct + (1 − c) · q_incorrect
```

`c = 1` and `c = 0` reproduce the two formulas exactly, so binary items are unaffected. A `PARTIAL` answer therefore splits into `c` of a correct observation and `1 − c` of an incorrect one, still totalling one observation's weight `w`.

*Rejected — v0.4's reading, "a `PARTIAL` with credit `c` is a correct answer at weight `c·w`".* It feeds only the correct-branch responsibility, so **any** partial answer is positive evidence: a 10% answer raises the mean (0.500 → 0.521 from `Beta(1,1)`, open response), and twenty consecutive 10% answers drive it to **0.734** — one step below `MASTERED` for a learner who is failing consistently. The mixture takes the same sequence to **0.146**. Verified in `verify_mastery_model.py`.

*Still an approximation, and named as such:* it reads "60% credit" as "60% of a correct observation". A rubric-aware likelihood (which rubric criteria were met) would be more faithful and needs per-item rubric data the prototype does not have.

**Step 4 — weighted Beta update.**

```
α'' = α' + w·q
β'' = β' + w·(1 − q)
```

`w ∈ (0, 1]` is the evidence weight supplied by the Evidence Module (block 3 — `Weighting`), reflecting item quality, response time plausibility, and whether the item was a strong or weak discriminator for this concept.

**Step 5 — learning transition (BKT `P(T)`).** Applied only when the interaction included instruction or feedback:

```
n   = α'' + β''
m   = α'' / n
m*  = m + (1 − m)·T
α''' = m*·n ,   β''' = (1 − m*)·n
```

This shifts the mean upward while **preserving total evidence count `n`** — i.e. learning changes what we believe, not how sure we are. That separation is deliberate.

**Step 6 — precision cap.** Enforce `n ≤ n_max`:

```
if n > n_max:   α, β ← α·(n_max/n), β·(n_max/n)
```

Without this, a learner with 300 observations becomes effectively frozen — new evidence cannot move the estimate, so genuine forgetting or newly acquired misconceptions are invisible. The cap gives an exponential-forgetting / sliding-window effect and keeps the model responsive forever. **This is the single most commonly omitted detail in Bayesian mastery implementations and it is worth a paragraph in the paper.**

### 3.5 Temporal decay (forgetting)

Applied lazily at read time and at the start of each update (AP-4). Exponential reversion **toward the prior**, not toward zero:

```
Δt = now − last_evidence_at            (in days)
d  = 2^( −Δt / h )                     (h = half-life, days)

α' = α₀ + (α − α₀)·d
β' = β₀ + (β − β₀)·d
```

Properties, all of which are correct behaviour and worth verifying in a unit test:

- `Δt = 0` → `d = 1` → state unchanged (identity).
- `Δt → ∞` → `d → 0` → state returns exactly to the prior: *we have forgotten that we ever knew anything about this learner and this concept*, which is the epistemically honest limit.
- Total evidence `n = α+β` shrinks toward `n₀`, so **variance grows** — decay increases uncertainty as well as lowering the mean. A model that decays the mean but not the variance will confidently assert stale beliefs.

**Spacing effect.** Half-life is not constant; repeated successful review lengthens it:

```
h = h_base · (1 + κ · ln(1 + r))
```

where `r` = number of *distinct* reinforcement sessions (sessions ≥ 24h apart, counted in `reinforcement_count`). `κ ≈ 1.0`, `h_base ≈ 14` days. This reproduces the standard spaced-repetition curve without adopting a full SM-2/FSRS scheduler, which would be scope creep into the Adaptive Engine.

### 3.6 Derived quantities

Everything exposed through the API is derived from `(α, β)` — nothing else is stored.

| Quantity | Formula |
|---|---|
| Mastery (mean) | `μ = α / (α+β)` |
| Variance | `σ² = αβ / [(α+β)²(α+β+1)]` |
| Evidence count | `n = α + β` |
| **Confidence** | `conf = clamp(1 − n₀/n, 0, 1)` — evidence sufficiency |
| Credible interval | 90% equal-tailed interval from the Beta quantile function |

**Two distinct notions of "how sure are we", deliberately kept separate:**

- **`confidence`** answers *"how much of this belief comes from evidence rather than from the prior?"* It depends only on the amount of evidence, never on what the evidence said.
- **`credibleInterval`** answers *"how tightly is the value pinned down?"* — the statistical uncertainty.

An earlier draft defined confidence as `1 − σ/σ_prior`. **Numerical verification showed this to be wrong** (§12): the standard deviation of a Beta depends on both `n` *and* how extreme the mean is, so that formula reported *higher* confidence for a learner whose mastery estimate happened to be near 0 or 1 than for one near 0.5 on **identical** evidence. Two learners who have each answered one question would get different "confidence" values purely because one got it right and the other got it wrong. The `1 − n₀/n` form is outcome-independent, which is what the word is supposed to mean; genuine statistical spread is reported by the credible interval instead.

**Mastery label** — the coarse enum the Diagnosis Engine's Gap Detector filters on ("*a simple filter over Learner State*", per the team doc). Evaluated in order; first match wins:

| Order | Label | Condition |
|---|---|---|
| 1 | `MISCONCEPTION` | an active misconception linked to this concept has activation > 0.5 |
| 2 | `DECAYED` | `peak_mastery ≥ 0.7` **and** `μ < 0.6` — was known, has faded |
| 3 | `UNKNOWN` | `conf < 0.5` — fewer than ~2 effective observations; decline to label |
| 4 | `MASTERED` | `P(θ > 0.7) ≥ 0.8` — conservative: uses the credible lower bound, not the mean |
| 5 | `DEVELOPING` | `μ ≥ 0.4` |
| 6 | `NOT_MASTERED` | otherwise |

**`DECAYED` must be evaluated before `UNKNOWN`.** This ordering was found by verification, not by design: decay reduces `n`, so it reduces confidence, so a once-mastered concept that has faded falls below the `UNKNOWN` threshold and — with the checks in the natural-looking order — gets reported as "we have no idea". That silently discards the most useful thing we know about it. *"Used to know it, has faded"* calls for review; *"never knew it"* calls for teaching. Collapsing the two would make the Adaptive Engine re-teach material the learner only needs to be reminded of. Verified in Appendix B.5, row 5.

Using `P(θ > 0.7) ≥ 0.8` rather than `μ ≥ 0.7` means a learner is not declared to have mastered something on thin evidence. `Beta(3,1)` has mean 0.75 but only `P(θ>0.7) = 0.657` (verified, Appendix B.5) — correctly *not* mastered. `peak_mastery` is stored precisely so `DECAYED` can be distinguished from `NOT_MASTERED`; the two require completely different interventions (review vs. teach), which is exactly the distinction the Diagnosis Engine exists to make.

### 3.7 Cognitive-level coupling

The four levels are not independent: evidence of `APPLY` is also evidence of `REMEMBER`. Model this as **downward damped propagation along the cognitive axis**:

```
evidence at level L with weight w
  → also applied at level L−1 with weight γ_c·w
  → and at level L−2 with weight γ_c²·w
```

with `γ_c ≈ 0.5`. Propagation is **downward only** — succeeding at applying implies remembering, but remembering implies nothing about applying. That asymmetry is the whole basis of the Cognitive Gap Analyzer: a learner with high `REMEMBER` and low `APPLY` has a *procedural* gap, not a knowledge gap, and the two need different interventions.

Propagated evidence is tagged `derived` in the transition log and **does not itself propagate further** (§6.4).

### 3.8 Misconception state

Misconceptions are tracked as separate Beta-distributed entities:

```
(learner_id, misconception_id)  →  Beta(α, β)   →   activation ∈ [0,1]
```

Evidence source: the Task module's `Distractor Mapping` (block 2). A distractor is not merely "wrong" — it is diagnostic, mapped to a specific misconception. Selecting it is positive evidence for that misconception.

Two deliberate asymmetries versus concept mastery:

1. **Decay half-life is much longer** (`h ≈ 180` days). Misconceptions are stable; a learner does not passively stop believing something wrong over a semester break.
2. **Clearing requires discriminating evidence.** Activation only decreases on evidence from items specifically flagged as discriminating for that misconception — i.e. items where the misconception would predict a *different* answer from the correct one. Answering an unrelated item correctly is not evidence that the misconception is gone.

This asymmetry matters: without it, the system will quietly declare misconceptions resolved simply because the learner stopped encountering them.

### 3.9 Parameter table (prototype defaults)

All parameters live in a versioned config, **not** in code. The config version is stamped on every transition so replay is reproducible.

| Param | Symbol | Default | Scope | Notes |
|---|---|---|---|---|
| Prior strength | `n₀` | 2.0 | global | weak |
| Prior mean | `μ₀` | 0.3 | per concept | overridable by graph prior |
| Slip | `s` | 0.10 | per concept | P(error \| knows) |
| Guess | `g` | 1/k | per item | `k` = number of options; 0.05 for open response |
| Learn rate | `T` | 0.10 | per concept | applied only with instruction |
| Precision cap | `n_max` | 30 | global | keeps model responsive |
| Base half-life | `h_base` | 14 d | per concept | |
| Spacing coefficient | `κ` | 1.0 | global | |
| Misconception half-life | `h_m` | 180 d | global | |
| Prerequisite damping | `γ_p` | 0.30 | global | §6.4 |
| Cognitive damping | `γ_c` | 0.50 | global | §3.7 |
| Mastery threshold | `θ*` | 0.70 | per concept | |
| Mastery credibility | — | 0.80 | global | `P(θ > θ*)` required |
| `UNKNOWN` conf. threshold | — | 0.50 | global | ≈ 2 effective observations |
| `DECAYED` peak / current | — | 0.70 / 0.60 | global | §3.6 |
| Late-evidence bound | `late_bound` | 7 d | global | §6.5 — beyond it, evidence is recorded and deferred, not applied |

Per-concept parameters default to the global value; the Evaluation/Validation system's `Confidence Calibration` output is what will eventually tune them per concept.

---

### 3.10 Exposure — what was taught, as distinct from what is known *(v0.5)*

Everything above estimates **what the learner knows**. It says nothing about **what the learner has been taught**, and the two are different facts:

| | Not exposed | Exposed |
|---|---|---|
| **Low mastery** | *never taught* → teach it for the first time | *taught, not acquired* → teach it **differently** |
| **High mastery** | learned elsewhere | normal progress |

Before v0.5 the two top cells were indistinguishable — both read as `NOT_MASTERED` — and they call for opposite interventions. This is exactly the kind of distinction the Diagnosis Engine exists to make.

**Exposure is a second data layer over the same shared ontology, not a second graph.** The structure is identical for every learner; only per-learner facts differ (§5.1). Per `(learner, concept)` the module keeps: first exposure, last exposure, a count, and counts by source.

```
ExposureSource = 'LESSON' | 'READING' | 'WORKED_EXAMPLE' | 'PRACTICE' | 'CONVERSATION'
```

Rules:

1. **Exposure never moves `α` or `β`.** Watching a lesson is not evidence of knowing. Mastery changes only through assessed evidence (§3.4). This separation is the whole point of the layer — if exposure leaked into the Beta posterior, the two questions would collapse back into one.
2. **Concept level, not cognitive level.** A lesson exposes a concept; which cognitive level it reached is a property of an *assessed* response, not of the material.
3. **No propagation.** A lesson on recursion does not expose its prerequisites. Exposure records what was actually shown.
4. **No decay.** Exposure is a historical fact, not a belief. Consumers judge recency from `lastExposedAt`.
5. **The existing `hadInstruction` flag on `EvidenceEvent` is unchanged.** It gates the BKT learning transition for feedback *within* an assessed interaction (§3.4 step 5); exposure records instruction that happens *outside* one. An assessed interaction with `hadInstruction = true` also writes one `PRACTICE` exposure.
6. **`CONVERSATION` exposure is the weakest signal and stays exposure only.** Inferring *knowledge* from a chat is the Evidence Module's job and, if done, arrives as an ordinary `EvidenceEvent` with a low `weight` (§11.3 #3).

Mastery labels (§3.6) are **unchanged**. Exposure is returned alongside them (§7.2), and the Diagnosis Engine combines the two. Adding a `NOT_TAUGHT` label instead would have changed a contract two consumers already build against, and would have made labelling depend on an input that may be absent.

---

## 4. Internal Component Decomposition

### 4.1 Functional core / imperative shell

The module is split along a single seam:

```
┌─────────────────────── IMPERATIVE SHELL (I/O, effects) ──────────────────────┐
│  EvidenceConsumer · IdempotencyGuard · LearnerLock · StateRepository          │
│  TransitionWriter · SnapshotProjector · Cache · DomainGraphAdapter            │
│                                                                              │
│   ┌──────────────────── FUNCTIONAL CORE (pure, no I/O) ────────────────────┐  │
│   │  DecayFunction · MasteryUpdater · LabelClassifier · PriorResolver      │  │
│   │  PropagationPlanner · MisconceptionScorer                             │  │
│   │  — deterministic: (state, event, config) → (state', transitions[])    │  │
│   └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

Why this matters here specifically, beyond general good practice:

- **Replay determinism (AP-1).** Replaying the log must produce byte-identical state. It cannot if the update logic reads the clock or the database. In the core, `now` is an *argument*, not an ambient value.
- **Testability.** Every claim in §3 becomes a unit test with no fixtures, no database, no mocks.
- **Strategy comparison.** The Evaluation system needs to run two mastery models over one evidence log. If the model is a pure function behind `IMasteryUpdater`, that is a config switch. If it is smeared across repository methods, it is a rewrite.

### 4.2 Components

| Component | Kind | Responsibility |
|---|---|---|
| `EvidenceConsumer` | shell | Subscribes to validated evidence; deserialises, validates envelope, dispatches |
| `IdempotencyGuard` | shell | Rejects already-processed `event_id` (§6.2) |
| `LearnerLockManager` | shell | Serialises writes per learner (AP-2) |
| `StateRepository` | shell | Loads/persists `learner_concept_state`; materialises priors for missing rows |
| `PriorResolver` | core | Computes `Beta(α₀,β₀)` for an unobserved tuple (§3.3) |
| `DecayFunction` | core | `(state, now, config) → state` (§3.5) |
| `MasteryUpdater` | core | `(state, observation, config) → state` — implements §3.4 behind `IMasteryUpdater` |
| `PropagationPlanner` | core | Given an update and graph neighbourhood, returns the bounded set of secondary updates (§6.4) |
| `MisconceptionScorer` | core | Maps distractor selections to misconception activation deltas (§3.8) |
| `LabelClassifier` | core | `(state, now) → MasteryLabel` (§3.6) |
| `TransitionWriter` | shell | Appends immutable transition records |
| `SnapshotProjector` | shell | Applies transitions to the current-state table in the same transaction |
| `StateMigrationHandler` | shell | Rewrites stored state when the ontology or model config version changes (§6.6) |
| `StateQueryService` | shell | Read API (§7); applies decay on read |
| `StateCache` | shell | Redis/in-memory read-through cache, invalidated on write (§8.3) |
| `ExposureRecorder` | shell | Ingests `ExposureEvent`; appends `exposure_event`, upserts `learner_concept_exposure`. Never touches `α`/`β` (§3.10) *(v0.5)* |

Note `DomainGraphAdapter` is the **only** component permitted to talk to the ontology store. Everything else depends on `IDomainGraph` (§5.4).

---

## 5. Data Model

### 5.1 Conceptual model

```
Learner ──1:N──> ConceptState ──N:1──> Concept        (owned by Domain Knowledge module)
   │                   │
   │                   └──1:N──> StateTransition       (append-only, immutable)
   │
   └──1:N──> MisconceptionState ──N:1──> Misconception (owned by Domain Knowledge module)
```

Per learner there are two independent layers over the same concept ids: **belief** (`ConceptState`, the Beta posterior) and **exposure** (`ConceptExposure`, §3.10, logged in `ExposureEvent`).

**"Personal Knowledge Graph" is a logical overlay, not a stored graph.** The proposal's term means *the shared ontology, joined with one learner's rows at query time*. The ontology is stored **once**, in the Domain Knowledge module; per learner this module stores only numbers keyed by `concept_id` — the id is the pointer into the shared graph — and only for concepts with evidence or exposure (sparsity, §8.2). A per-learner copy of the graph would multiply storage by roughly 12–35× at the scales of §8.2, and every curriculum edit would have to be applied to every copy.

**Learner input never changes ontology structure.** Evidence and exposure update numbers on concepts that already exist; they never create, delete or re-link nodes or edges. Structure is authored and extended (including LLM-assisted augmentation with human review) only by the Domain Knowledge module. If learner input could add structure, one learner could poison the graph for everyone, and the ontology would fill with one-off branches.

`Concept` and `Misconception` are **foreign identities**. This module stores their IDs and never their content — no concept name, no description, no edges. If a concept label is needed for display, it is resolved through `IDomainGraph` at read time. Duplicating ontology content here would create a second source of truth and guarantee drift.

### 5.2 Postgres schema

```sql
-- ───────────────────────────────────────────────────────────────
-- Enumerations
-- ───────────────────────────────────────────────────────────────
CREATE TYPE cognitive_level AS ENUM ('REMEMBER','UNDERSTAND','APPLY','ANALYZE');

CREATE TYPE transition_type AS ENUM (
  'INITIALIZATION',   -- prior materialised into a real row
  'EVIDENCE',         -- direct evidence from an assessed interaction
  'PROPAGATED',       -- damped, derived from another update (prereq or cognitive axis)
  'MIGRATION',        -- ontology or model-version rewrite
  'MANUAL_OVERRIDE',  -- instructor correction; always auditable
  'REORDER'           -- re-fold after late evidence (§6.5); history is appended, never rewritten
);

CREATE TYPE evidence_outcome AS ENUM ('CORRECT','INCORRECT','PARTIAL','SKIPPED');

-- ───────────────────────────────────────────────────────────────
-- Current state (materialised read model — rebuildable from transitions)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE learner_concept_state (
    learner_id            UUID              NOT NULL,
    concept_id            UUID              NOT NULL,
    cognitive_level       cognitive_level   NOT NULL,

    -- Beta posterior.  NUMERIC, not DOUBLE PRECISION — see §5.6.
    alpha                 NUMERIC(12,6)     NOT NULL,
    beta                  NUMERIC(12,6)     NOT NULL,

    -- the prior this row decays back toward; stored so decay is self-contained
    alpha_prior           NUMERIC(12,6)     NOT NULL,
    beta_prior            NUMERIC(12,6)     NOT NULL,

    -- temporal
    last_evidence_at      TIMESTAMPTZ       NOT NULL,
    reinforcement_count   INTEGER           NOT NULL DEFAULT 0,
    last_reinforced_at    TIMESTAMPTZ,
    half_life_days        DOUBLE PRECISION  NOT NULL DEFAULT 14.0,

    -- derived-but-persisted (needed to distinguish DECAYED from NOT_MASTERED)
    peak_mastery          NUMERIC(9,6)      NOT NULL DEFAULT 0,

    -- provenance / audit
    direct_evidence_count INTEGER           NOT NULL DEFAULT 0,
    derived_evidence_count INTEGER          NOT NULL DEFAULT 0,
    model_config_version  TEXT              NOT NULL,
    ontology_version      TEXT              NOT NULL,
    state_version         BIGINT            NOT NULL DEFAULT 1,  -- optimistic concurrency
    updated_at            TIMESTAMPTZ       NOT NULL DEFAULT now(),

    PRIMARY KEY (learner_id, concept_id, cognitive_level),

    CONSTRAINT alpha_positive  CHECK (alpha > 0),
    CONSTRAINT beta_positive   CHECK (beta  > 0),
    CONSTRAINT precision_capped CHECK (alpha + beta <= 1000),
    CONSTRAINT peak_in_range   CHECK (peak_mastery BETWEEN 0 AND 1)
);

-- every read is scoped by learner; this is the index that matters
CREATE INDEX idx_lcs_learner        ON learner_concept_state (learner_id);
CREATE INDEX idx_lcs_learner_concept ON learner_concept_state (learner_id, concept_id);
-- cross-learner analytics (Evaluation module only)
CREATE INDEX idx_lcs_concept        ON learner_concept_state (concept_id, cognitive_level);

-- ───────────────────────────────────────────────────────────────
-- Append-only history — the actual system of record (AP-1)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE state_transition (
    transition_id         UUID              PRIMARY KEY,   -- UUIDv7: sortable by time
    learner_id            UUID              NOT NULL,
    concept_id            UUID              NOT NULL,
    cognitive_level       cognitive_level   NOT NULL,

    transition_type       transition_type   NOT NULL,
    evidence_event_id     UUID,                            -- NULL for MIGRATION / INITIALIZATION

    -- full before/after so any state is reconstructible without replaying from zero.
    -- These four columns are digest inputs (§6.2) — NUMERIC is load-bearing, not cosmetic.
    alpha_before          NUMERIC(12,6)     NOT NULL,
    beta_before           NUMERIC(12,6)     NOT NULL,
    alpha_after           NUMERIC(12,6)     NOT NULL,
    beta_after            NUMERIC(12,6)     NOT NULL,

    -- the inputs that produced the change (explainability)
    outcome               evidence_outcome,
    weight                NUMERIC(9,6),
    responsibility_q      NUMERIC(9,6),                    -- §3.4 step 3
    item_id               BYTEA,           -- encrypted with the learner's DEK (§9.4)

    -- propagation provenance
    derived_from          UUID REFERENCES state_transition(transition_id),
    propagation_depth     SMALLINT          NOT NULL DEFAULT 0,

    model_config_version  TEXT              NOT NULL,
    ontology_version      TEXT              NOT NULL,       -- detects state computed on a stale replica (§5.5)

    -- non-repudiation: which service asserted this, provably (§9.2.1)
    evidence_signature    BYTEA,           -- encrypted with the learner's DEK (§9.4)
    signature_key_id      TEXT,

    -- bi-temporal
    occurred_at           TIMESTAMPTZ       NOT NULL,       -- when the learning event happened
    recorded_at           TIMESTAMPTZ       NOT NULL DEFAULT now(),  -- when we learned of it

    CONSTRAINT depth_bounded CHECK (propagation_depth BETWEEN 0 AND 2)
) PARTITION BY RANGE (recorded_at);

CREATE INDEX idx_st_learner_time ON state_transition (learner_id, occurred_at DESC);
CREATE INDEX idx_st_event        ON state_transition (evidence_event_id);
CREATE INDEX idx_st_target       ON state_transition (learner_id, concept_id, cognitive_level, occurred_at DESC);

-- ───────────────────────────────────────────────────────────────
-- Idempotency ledger (§6.2)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE processed_event (
    evidence_event_id     UUID              PRIMARY KEY,
    learner_id            UUID              NOT NULL,
    processed_at          TIMESTAMPTZ       NOT NULL DEFAULT now(),
    outcome_digest        TEXT              NOT NULL,  -- hash of resulting transitions; detects replay divergence
    disposition           TEXT              NOT NULL DEFAULT 'APPLIED'
                          CHECK (disposition IN ('APPLIED','DEFERRED_LATE')),   -- §6.5
    deferred_payload      BYTEA,            -- full signed EvidenceEvent, DEK-encrypted (§9.4); only when DEFERRED_LATE
    CONSTRAINT deferred_has_payload
        CHECK ((disposition = 'DEFERRED_LATE') = (deferred_payload IS NOT NULL))
);

-- ───────────────────────────────────────────────────────────────
-- Misconceptions (§3.8)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE learner_misconception_state (
    learner_id            UUID              NOT NULL,
    misconception_id      UUID              NOT NULL,

    alpha                 NUMERIC(12,6)     NOT NULL,
    beta                  NUMERIC(12,6)     NOT NULL,
    alpha_prior           NUMERIC(12,6)     NOT NULL DEFAULT 0.2,
    beta_prior            NUMERIC(12,6)     NOT NULL DEFAULT 1.8,

    last_evidence_at      TIMESTAMPTZ       NOT NULL,
    half_life_days        DOUBLE PRECISION  NOT NULL DEFAULT 180.0,
    first_detected_at     TIMESTAMPTZ       NOT NULL,
    peak_activation       NUMERIC(9,6)      NOT NULL DEFAULT 0,
    resolved_at           TIMESTAMPTZ,                     -- set when activation drops below threshold
    model_config_version  TEXT              NOT NULL,
    state_version         BIGINT            NOT NULL DEFAULT 1,

    PRIMARY KEY (learner_id, misconception_id)
);

CREATE INDEX idx_lms_learner_active
    ON learner_misconception_state (learner_id) WHERE resolved_at IS NULL;

-- ───────────────────────────────────────────────────────────────
-- Exposure (§3.10) — what was taught, never what is known
-- ───────────────────────────────────────────────────────────────
CREATE TYPE exposure_source AS ENUM
  ('LESSON','READING','WORKED_EXAMPLE','PRACTICE','CONVERSATION');

-- append-only log, same discipline as state_transition (AP-1)
CREATE TABLE exposure_event (
    exposure_event_id     UUID              PRIMARY KEY,   -- idempotency key, from the Evidence Module
    learner_id            UUID              NOT NULL,
    concept_id            UUID              NOT NULL,
    source                exposure_source   NOT NULL,
    content_ref           BYTEA,            -- lesson/material id, DEK-encrypted (§9.4)
    duration_seconds      INTEGER,          -- optional, as reported by the source
    evidence_signature    BYTEA,            -- DEK-encrypted (§9.4)
    signature_key_id      TEXT,
    ontology_version      TEXT              NOT NULL,
    occurred_at           TIMESTAMPTZ       NOT NULL,
    recorded_at           TIMESTAMPTZ       NOT NULL DEFAULT now()
) PARTITION BY RANGE (recorded_at);

CREATE INDEX idx_ee_learner_concept ON exposure_event (learner_id, concept_id, occurred_at DESC);

-- snapshot, rebuildable from exposure_event
CREATE TABLE learner_concept_exposure (
    learner_id            UUID              NOT NULL,
    concept_id            UUID              NOT NULL,
    first_exposed_at      TIMESTAMPTZ       NOT NULL,
    last_exposed_at       TIMESTAMPTZ       NOT NULL,
    exposure_count        INTEGER           NOT NULL CHECK (exposure_count > 0),
    count_by_source       JSONB             NOT NULL,      -- {"LESSON": 2, "PRACTICE": 5, ...}
    PRIMARY KEY (learner_id, concept_id)
);

-- ───────────────────────────────────────────────────────────────
-- Model configuration — versioned, never edited in place
-- ───────────────────────────────────────────────────────────────
CREATE TABLE model_config (
    version               TEXT              PRIMARY KEY,
    params                JSONB             NOT NULL,      -- §3.9 table
    created_at            TIMESTAMPTZ       NOT NULL DEFAULT now(),
    is_active             BOOLEAN           NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX one_active_config ON model_config (is_active) WHERE is_active;
```

### 5.3 Decay lives in the application layer only — single source of truth

Because decay is a closed-form expression, it *can* be evaluated in SQL as a view, pushing the compute into Postgres and keeping reads to one round trip. **This design deliberately rejects that option.**

**Decision: the decay function exists in exactly one place — `DecayFunction` in the functional core (§4.1). There is no SQL decay view.**

The rejected alternative and why:

| | SQL view | Application layer (chosen) |
|---|---|---|
| Source of truth | **two** — SQL + TypeScript | one |
| Divergence risk | silent; only caught by a cross-language consistency test | impossible by construction |
| Changing the model (`κ`, half-life semantics) | edit two implementations, in two languages, in two deployment units | edit one function |
| Rows transferred per query | fewer | a few hundred per learner |
| Testability | needs a live database | pure function, no fixtures |

The SQL version is a *performance optimisation that buys a correctness liability*. The two implementations would have to stay numerically identical across every future change to §3.5 — including the spacing-effect term, which is the part most likely to be retuned. A property test asserting agreement to 1e-9 catches divergence *after* it is written, and only if someone remembers to keep the test's input distribution representative. That is not a guarantee; it is a hope with a CI job attached.

**The cost is negligible and quantifiable.** All online reads are scoped to a single learner, who has at most a few hundred materialised rows (§8.2). The query becomes a plain indexed fetch of `(α, β, priors, last_evidence_at, half_life_days, reinforcement_count)`, and decay is applied in Node over those rows — a few hundred floating-point operations, sub-millisecond. We are trading microseconds of CPU for the elimination of an entire class of silent-wrongness bug. That trade is not close.

**The one case that looks like a counter-argument, and isn't:** the Evaluation module runs unscoped cross-learner analyses over millions of rows, where pulling everything into the application layer would be genuinely wasteful. But those analyses do not read decayed current state — they reconstruct mastery *at specific historical timestamps* from `state_transition` (§6.5), which is a different query against a different table and needs no decay view at all. If a future batch job does need decayed state across all learners, the correct answer is a **materialised snapshot computed by the application at a fixed instant** — still one implementation of the maths, just persisted.

**Consequence downstream:** risk R6 (duplicated decay logic) is eliminated rather than mitigated, the cross-language consistency test is dropped from §10.2, and phase P1 shrinks accordingly.

### 5.4 The domain graph port

```typescript
/** The ONLY interface through which Learner State sees the ontology. */
export interface IDomainGraph {
  /** Direct prerequisites of a concept. */
  getPrerequisites(conceptId: string, maxDepth: 1 | 2): Promise<GraphEdge[]>;

  /** Concepts that have this concept as a prerequisite. */
  getDependents(conceptId: string, maxDepth: 1 | 2): Promise<GraphEdge[]>;

  /** Misconceptions attached to a concept. */
  getMisconceptions(conceptId: string): Promise<MisconceptionRef[]>;

  /** Current ontology version — stamped on every transition. */
  getVersion(): Promise<string>;

  /** Whether a concept id still exists (used by StateMigrationHandler). */
  resolveConcepts(ids: string[]): Promise<Map<string, ConceptRef | null>>;
}

export interface GraphEdge {
  conceptId: string;
  relation: 'PREREQUISITE_OF' | 'PART_OF' | 'RELATED_TO';
  strength: number;   // 0..1, supplied by the Domain Knowledge module
  depth: 1 | 2;
}
```

Three implementations, in the order they should be built:

| Implementation | Phase | Notes |
|---|---|---|
| `PostgresDomainGraph` | prototype | Recursive CTE over a local `concept_edge` table. Zero extra infrastructure. |
| `Neo4jDomainGraph` | interim | Cypher, bounded `*1..2` traversal. Synchronous RPC — **acceptable only as a stepping stone** (§5.5). |
| `ReplicatedDomainGraph` | target | Local read-model replica kept current by events. See below. |

### 5.5 Ontology replication — removing the synchronous cross-service call

In the prototype the ontology lives in the same database, so `IDomainGraph` calls are local. **Once the Knowledge Graph becomes a separate service, a naive port of this design puts a synchronous cross-service RPC on the evidence ingest path**, and that is a structural problem, not a tuning problem:

- **Latency** — every evidence event pays a network round trip (~5–50 ms) to compute propagation, dwarfing the ~1 ms of actual arithmetic.
- **Coupling of availability** — Learner State's write path becomes only as available as the Knowledge Graph service. Two services at 99.9% in series give 99.8%.
- **Load amplification** — the Knowledge Graph absorbs one query per evidence event across all learners, to answer a question whose answer changes perhaps monthly.

§6.3 already keeps this call outside the per-learner lock, which prevents it from destroying *throughput*. But it remains on the hot path and it remains a hard dependency. Mitigating the symptom is not the same as removing the cause.

**Target design: treat the ontology as replicated reference data, not as a remote service to be queried.**

```
┌────────────────────────┐                          ┌─────────────────────────┐
│  Knowledge Graph svc   │   OntologyChanged        │   Learner State svc     │
│  (system of record)    │ ──────────────────────▶  │                         │
│  Neo4j                 │   {version, changeset}   │  local concept_edge     │
│                        │      (async, durable)    │  read-model (Postgres)  │
└────────────────────────┘                          │        ▲                │
                                                    │        │ local query,   │
                                                    │        │ ~0.1 ms        │
                                                    │  PropagationPlanner     │
                                                    └─────────────────────────┘
```

The Knowledge Graph publishes topology changes; Learner State maintains its own local projection of the subgraph it actually needs — concept ids, prerequisite and part-of edges, edge strengths, misconception links. Propagation then queries local tables. **No network call on the ingest path at all.**

Why this is affordable here specifically: the ontology is *small and slow-moving*. Thousands of concepts and tens of thousands of edges is a few megabytes, and it changes on a curriculum-authoring cadence — days or weeks, not seconds. Replicating fast-moving or large data would be a bad trade; replicating this is nearly free.

**What it costs, stated honestly:**

| Concern | Handling |
|---|---|
| Staleness window | Bounded by event propagation lag (seconds). Every transition is already stamped with `ontology_version` (§5.2), so state computed against a stale topology is *detectable after the fact*, not silently wrong. |
| Missed or out-of-order events | Events carry a monotonic `ontology_version`; a gap triggers a full resync. A nightly reconciliation job compares version + checksum regardless — **never rely on the event stream alone for convergence.** |
| Storage duplication | A few MB. Irrelevant. |
| "Two sources of truth" objection | It is not. The Knowledge Graph remains the *only* writer; this is a read-only projection with a clear owner, which is a different thing from divergent authority. Contrast §5.3, where two implementations of the *same computation* would both have been authoritative. |

**Consistency model:** the system becomes eventually consistent with respect to ontology topology, and that is the correct trade. If a prerequisite edge is added at 14:00 and Learner State applies it at 14:00:03, three seconds of propagation used the previous topology. The affected transitions are identifiable by `ontology_version` and can be replayed (AP-1). Trading three seconds of topology staleness for the removal of a hard availability dependency on the write path is a clear win.

**Degradation is already specified** (§8.5): if the replica is stale or a concept id is unknown, the primary update still applies and only propagation is deferred. Losing an enrichment must never cost us the observation itself.

---

### 5.6 Numeric determinism — quantise at the persistence boundary, and only there

AP-1 promises that replaying the log reproduces the state, and §10.2 makes that testable by comparing `outcome_digest` across runs. **IEEE-754 binary floats do not support that promise.** The same evidence sequence can produce a bit-different `α` after a Node upgrade, a change in the order a propagation batch is reduced, or a different libm on the CI runner. The state is still *correct* to eleven decimal places and the digest is still *different*, so the reproducibility alarm fires on noise and is switched off within a week — which is worse than not having it.

**Decision: `α`, `β` and the priors are stored as `NUMERIC(12,6)`. The application rounds to exactly six decimal places once, at the repository boundary, and emits a decimal string. Postgres stores that string verbatim; the digest hashes the same string.**

Three rules make this work, and all three are easy to get wrong:

**1. Quantise at the boundary, never inside the functional core.** The pure functions of §4.1 compute in full `float64` and return full `float64`. It is tempting to have `MasteryUpdater` round its own output — that is a mistake for two reasons. First, one evidence event runs decay → primary update → cognitive propagation → prerequisite propagation; rounding in the core rounds four or more times per event instead of once, and the errors accumulate in the direction of whatever the rounding rule is. Second, it breaks a stated invariant: Appendix B.2 asserts that the BKT learning transition changes the mean while leaving `n = α + β` **exactly** unchanged. Round `α` and `β` independently and `n` moves. Measured over 20 000 randomised learning transitions, independent 6-decimal rounding breaks exact `n`-conservation in **25.2% of cases** (maximum deviation 1 × 10⁻⁶) — so the property test either fails outright or has to be weakened to a tolerance, and the paper loses a clean claim for no benefit.

**2. Exactly one party rounds.** JavaScript's `toFixed` and Postgres's `NUMERIC` cast do not agree at every half-way point (`toFixed` inherits the binary representation of the input; `NUMERIC` rounds half away from zero on the decimal value). If TypeScript hashes its rounded value and Postgres re-rounds during the `INSERT`, the digest can disagree with what was persisted — precisely the failure this section exists to prevent. The application emits a 6-decimal string; nothing downstream re-rounds.

**3. The read path must not silently re-float.** The driver returns `NUMERIC` as a non-float — a string from `node-pg`, a `Prisma.Decimal` from Prisma (v0.5, #23) — specifically to avoid precision loss. Convert it to the canonical string with `.toFixed(6)` in the repository mapper and nowhere else. That is the desired behaviour here — the string *is* the canonical form — but it surprises everyone once. Parse it in exactly one place (the repository mapper), and let the functional core receive plain numbers.

**What is deliberately *not* quantised.** Derived read-model quantities — mean, variance, credible interval, confidence — are computed from `(α, β)` at read time and never stored (§3.6), so they cannot drift. `half_life_days` is configuration, not accumulated state. Timestamps are exact.

**Precision budget.** `n ≤ n_max = 30` and the `precision_capped` CHECK bounds `α + β ≤ 1000`, so four integer digits are ample; six decimal places is roughly four orders of magnitude finer than any decision threshold in §3.6. There is no scenario in this model where the sixth decimal place of `α` changes a label, a ranking, or a recommendation — which is exactly why it is safe to discard it, and why discarding it deterministically is free.

---

## 6. The Update Pipeline (Orchestrator)

### 6.1 Input contract

```typescript
export interface EvidenceEvent {
  eventId:        string;          // UUIDv7 — idempotency key, assigned by Evidence Module
  tenantId:       string;          // see below — carried even while the prototype is single-tenant
  learnerId:      string;
  itemId:         string;
  attemptId:      string;

  /** Concepts this item assesses, with the level and how strongly. */
  targets: Array<{
    conceptId:      string;
    cognitiveLevel: CognitiveLevel;
    relevance:      number;        // 0..1 — how central this concept is to the item
  }>;

  outcome:        'CORRECT' | 'INCORRECT' | 'PARTIAL' | 'SKIPPED';
  partialCredit?: number;          // 0..1, required when outcome = PARTIAL

  /** Distractor chosen, if any — maps to a misconception via the Task module. */
  selectedDistractorId?: string;

  /** Evidence quality, computed by the Evidence Module (block 3 — Weighting). */
  weight:         number;          // 0..1

  /** Item parameters needed for the slip/guess correction. */
  itemParams: {
    guessRate:    number;          // 1/k for k-option MCQ
    slipRate?:    number;          // falls back to concept default
    optionCount?: number;
  };

  /** Did this interaction include instruction/feedback? Gates the BKT learning transition. */
  hadInstruction: boolean;

  occurredAt:     string;          // ISO-8601, valid time
  ontologyVersion: string;
  provenance: {
    sourceService: string;
    evidenceChain: string[];       // upstream event ids
  };
}
```

**`tenantId` is carried in the payload, not derived from it.** The prototype is single-tenant and no table is keyed by tenant (§11.3 #4), so this field is unused on the write path today. It is present anyway because of AP-1: **replay must be a pure function of the log.** If tenancy were recovered later by resolving `attemptId` against the Task module, or inferred from `provenance.sourceService`, then a replay run in two years would depend on that module's state *at that future moment* — and if the attempt record was archived, re-keyed, or the service now serves several tenants, the replay silently reconstructs the wrong thing. This is the same argument §5.5 makes for replicating the ontology rather than calling across the network on the ingest path. Note also that `sourceService` is a *service* identity, not a *tenant* identity; one service will serve many tenants.

The asymmetry is what makes this cheap: adding the field now costs one string per event, while omitting it makes the tenancy retrofit unrecoverable rather than merely expensive. The physical column is the reversible half of the decision and stays deferred.

**`SKIPPED` is not `INCORRECT`.** A skip carries almost no information about knowledge (it may signal low confidence, time pressure, or disengagement) and must be handled with a very low weight or discarded — treating it as a wrong answer systematically underestimates mastery for cautious learners. This is a real fairness issue, not a detail.

### 6.1a Exposure input *(v0.5)*

```typescript
export interface ExposureEvent {
  eventId:         string;         // UUIDv7 — idempotency key, assigned by the Evidence Module
  tenantId:        string;
  learnerId:       string;
  conceptIds:      string[];       // concepts the material actually covers — mapped upstream
  source:          'LESSON' | 'READING' | 'WORKED_EXAMPLE' | 'PRACTICE' | 'CONVERSATION';
  contentRef?:     string;         // lesson / material id
  durationSeconds?: number;
  occurredAt:      string;
  ontologyVersion: string;
}
```

Same envelope and controls as evidence: Ed25519-signed by the Evidence Module over an explicitly ordered field list (§9.2.1), delivered to `POST /internal/exposure`, network-restricted, idempotent on `eventId` through the same `processed_event` ledger. **Mapping material to concepts is upstream's job** — this module never parses lesson content; it receives concept ids. Processing is short: verify → claim → lock → append one `exposure_event` row per concept → upsert `learner_concept_exposure` → commit. No decay, no propagation, no Beta update. Late arrival is harmless: the snapshot is a min/max/count, which is order-independent, so no re-fold is needed.

Requested from the Evidence Module as **LS-CR-002** (§11.4).

### 6.2 Exactly-once processing over at-least-once delivery

Message delivery — whether Kafka or an in-process bus with retries — is at-least-once. Duplicate delivery of a Bayesian update *silently corrupts state*: nothing errors, the numbers are just wrong, and it is undetectable after the fact. This is the highest-severity failure mode in the module.

**Mechanism:** the idempotency insert and the state mutation share one transaction.

```sql
BEGIN;
  -- 1. Claim the event. Duplicate → 0 rows → abort, ack, done.
  --    outcome_digest is not known yet: 'PENDING' until step 3 (v0.5, #24).
  INSERT INTO processed_event (evidence_event_id, learner_id, outcome_digest)
  VALUES ($1, $2, 'PENDING')
  ON CONFLICT (evidence_event_id) DO NOTHING
  RETURNING evidence_event_id;

  -- 2. Serialise all writes for this learner (AP-2).
  --    hashtextextended → int8. NOT hashtext, which is int4. See §6.2.1.
  SELECT pg_advisory_xact_lock(hashtextextended($2::text, 0));

  -- 3. ... read state, apply §3.4, write transitions, upsert snapshot ...
  --    then, still in this transaction:
  UPDATE processed_event SET outcome_digest = $3 WHERE evidence_event_id = $1;
COMMIT;
```

Because the claim and the effect commit atomically, a crash at any point either applies the event exactly once or not at all. The advisory lock is transaction-scoped and released automatically on commit or rollback — no leak on crash.

#### 6.2.1 Lock key width, and why not an external lock manager

`pg_advisory_xact_lock` accepts a 64-bit key, but the obvious `hashtext()` returns **int4** — a 32-bit space. Use `hashtextextended(text, int8)` (PostgreSQL 11+), which returns int8 and uses the full key width.

**Quantifying the risk, because the intuition here is usually wrong.** Collision probability depends on the number of learners holding a lock *at the same instant*, not on the total learner population — a lock is held for the ~2 ms of a transaction, not for the lifetime of an account:

| Concurrent writers | `hashtext` (32-bit) | `hashtextextended` (64-bit) |
|---|---|---|
| 100 | 0.0001% | 2 × 10⁻¹⁶ |
| 1 000 | 0.012% | 3 × 10⁻¹⁴ |
| 10 000 | 1.16% | 3 × 10⁻¹² |
| 50 000 | 25.3% | 7 × 10⁻¹¹ |

Computing this over *total* learners instead of *concurrent* ones inflates the figure by orders of magnitude and is the usual source of alarm about this pattern.

**The failure mode is conservative, and this matters.** A collision makes two *different* learners share a lock key, so one transaction briefly waits for the other — a false conflict, costing milliseconds. It can never allow two writers for the *same* learner to proceed concurrently, because a given `learner_id` always hashes to the same key. Collisions therefore cause **over**-serialisation, never **under**-serialisation. AP-2's correctness guarantee does not depend on the hash being collision-free; only throughput does. Even so, 64-bit is a one-word change and there is no reason to leave the 32-bit space in place.

**Rejected: Redis Redlock or another external distributed lock.** This would be a regression, for three reasons:

1. **It breaks the atomicity of lock and write.** The entire safety argument above rests on the lock being *transaction-scoped in the same transaction as the write* — acquired, used, and released atomically with the commit, with automatic release on crash. An external lock cannot participate in that transaction. A process that acquires a Redis lock, commits to Postgres, then dies before releasing leaves a stuck lock; one that stalls on GC past the lease expiry has its lock silently revoked *while its transaction is still open* — which is exactly the unprotected concurrent write AP-2 exists to prevent. Correcting this requires fencing tokens and monotonic sequence checks at the storage layer, i.e. rebuilding what Postgres already gives us for free.
2. **Redlock's safety is contested.** Its mutual-exclusion guarantee rests on bounded clock drift, bounded pauses, and bounded network delay — assumptions that do not hold under GC pauses, VM migration, or NTP correction. Adopting it means trading a well-understood 10⁻¹¹ false-*conflict* rate for a poorly-bounded false-*exclusion* rate. That is the wrong direction: false conflicts cost latency, false exclusions cost correctness.
3. **It adds an availability dependency** on Redis for the write path, to solve a problem that a wider hash already solves.

**The correct escalation path is the one already in AP-2: Kafka partitioned by `learner_id`.** That replaces locking with *ordering* — one consumer per partition means there is no concurrent writer to exclude, so the problem disappears rather than being managed. If lock contention ever shows up in profiling before that migration, the intermediate step is micro-batching per learner (§8.4), not a second lock manager.

**`outcome_digest`, defined precisely.** "A hash of the transitions produced" is not a specification — two implementations will disagree on field order, number formatting and null handling, and the alarm becomes noise. The digest is:

```
SHA-256 over the UTF-8 concatenation, in this exact order, of the transitions
produced by this event, each transition sorted by (concept_id, cognitive_level,
propagation_depth), fields joined by '\x1f' and records by '\x1e':

  transition_type | concept_id | cognitive_level | propagation_depth
  | alpha_before | beta_before | alpha_after | beta_after | responsibility_q

Numeric fields are the canonical 6-decimal strings of §5.6 — the same bytes
that were persisted.  Absent values serialise as the empty string.
```

Deliberately **excluded**: `transition_id` (a fresh UUIDv7 per run — including it would make every replay differ), `recorded_at` (transaction time, different by construction on replay), and `model_config_version` (it is the *independent variable* when comparing strategies; §6.6 replays the same log under a new config precisely to see the digest change).

On replay, a mismatch proves the update logic or its parameters changed — a useful alarm during model retuning, and the evidence behind the paper's reproducibility claim.

### 6.3 Processing sequence

```
SignedEvidenceEvent
     │
     ▼
[0] Signature verification ─ Ed25519 over the canonical payload (§9.2.1)
     │                       fail → dead-letter + security alert. Nothing is
     │                       recorded, not even that the event was seen.
     ▼
[1] Envelope validation ─── schema, learner exists, ontologyVersion known
     │                      reject → dead-letter, do not retry
     ▼
[2] Idempotency claim ───── already processed? → ACK and stop
     │
     ▼
[3] Acquire learner lock ── pg_advisory_xact_lock(learner_id)
     │
     ▼
[4] Resolve target states ─ load rows; materialise priors for missing tuples
     │                      (emits INITIALIZATION transitions)
     ▼
[5] Decay to occurredAt ─── DecayFunction(state, event.occurredAt)   [pure]
     │
     ▼
[6] Primary update ──────── MasteryUpdater per target  (§3.4)        [pure]
     │                      weight_effective = event.weight × target.relevance
     ▼
[7] Cognitive propagation ─ downward, damped γ_c, depth ≤ 2          [pure]
     │
     ▼
[8] Prerequisite propagation ─ PropagationPlanner, depth ≤ 2, γ_p    [pure]
     │                          (needs IDomainGraph — fetched BEFORE the lock)
     ▼
[9] Misconception scoring ─ if selectedDistractorId present (§3.8)   [pure]
     │
     ▼
[10] Persist ───────────── append transitions + upsert snapshots, same TX
     │
     ▼
[11] COMMIT
     │
     ▼
[12] Post-commit ───────── invalidate cache, publish LearnerStateChanged
```

Two ordering rules that are easy to get wrong:

- **Graph reads happen before the lock (step 8's data is fetched at step 1).** Holding a per-learner lock across a network call turns a 2 ms critical section into a 50 ms one and destroys throughput. Fetch the neighbourhood first, then lock, compute, commit. Note this only mitigates the symptom — §5.5 removes the cross-service call from the ingest path entirely, which is the actual fix.
- **`LearnerStateChanged` is published after commit, not inside the transaction.** Publishing inside means consumers can observe an event for a transaction that later rolls back. If the publish must be reliable, use the transactional-outbox pattern: write the event to an `outbox` table in the same transaction, relay it separately.

### 6.4 Bounded propagation

Evidence about concept C informs neighbouring concepts. Unbounded, one event cascades across the entire ontology — a write amplification bomb and an epistemic one, since derived belief gets recycled as if it were observation.

Four hard constraints:

1. **Depth ≤ 2.** Enforced by a database `CHECK`, not by a code convention, so it cannot regress silently.
2. **Geometric damping.** Effective weight at depth `d` is `w · (γ_p · edge.strength)^d`. With `γ_p = 0.3`, depth-2 evidence carries ≤ 9% of the original weight.
3. **Derived evidence does not re-propagate.** A `PROPAGATED` transition never triggers further propagation. Without this rule, belief circulates around cycles in the graph and inflates itself — the system becomes confident on the basis of its own inferences. `derived_from` and `propagation_depth` make this auditable.
4. **Threshold gate.** Propagation only fires when the primary update moved the mean by more than `ε = 0.02`. Most events are unsurprising and should cost one row, not twenty.

**Directional semantics** — the direction of inference differs by evidence sign:

| Observation | Propagate to | Sign | Reasoning |
|---|---|---|---|
| Success on C | prerequisites of C | positive | you probably know what C requires |
| Success on C | dependents of C | none | says nothing about more advanced material |
| Failure on C | prerequisites of C | weak negative | the cause may lie upstream — but this is a *hypothesis*, and generating hypotheses is the Diagnosis Engine's job |
| Failure on C | dependents of C | none | already unknown |

The asymmetry matters. Note that "failure on C means a prerequisite is missing" is deliberately propagated only weakly here: converting it into a firm belief is root-cause analysis, and belongs to the Prerequisite Analyzer, not to this module. Learner State supplies the evidence; it does not draw the conclusion.

### 6.5 Bi-temporality and late-arriving evidence

Two timestamps are stored:

- `occurred_at` — **valid time**: when the learner actually did the thing.
- `recorded_at` — **transaction time**: when the system found out.

They differ for offline clients that sync later, for evidence re-derived from stored transcripts, and for manual instructor corrections.

This enables the query the Evaluation module needs for `Confidence Calibration`:

> *"What did the system believe about learner L at time T, using only what it knew at time T?"*

which is `WHERE recorded_at <= T` — distinct from *"what do we now believe was true at time T"*, which is `WHERE occurred_at <= T`. Conflating the two makes calibration analysis wrong in a way that flatters the system, because it evaluates predictions using information that arrived after the prediction.

**Handling out-of-order arrival.** An event with `occurred_at` earlier than the row's `last_evidence_at` breaks the sequential assumption. Three strategies were considered:

| Strategy | Cost | Correctness |
|---|---|---|
| A. Reject | trivial | loses data |
| B. Append with reduced weight | trivial | approximate — and v0.4 never said *how much* reduced, so it was not implementable |
| **C. Re-fold the affected tuples in `occurred_at` order** | one bounded recomputation | **exact** |

**Decision (v0.5, closes §11.3 #5):**

| Lateness = `last_evidence_at − occurred_at` | Action |
|---|---|
| ≤ 0 (in order — the normal case) | ordinary update (§6.3) |
| 0 < lateness ≤ `late_bound` (7 d) | **C** |
| > `late_bound` | **record and defer**: `processed_event.disposition = 'DEFERRED_LATE'`, full signed payload kept in `deferred_payload`, state untouched. An instructor or operator can apply it explicitly, which runs C. |

**Why C is affordable, and B is gone.** The prototype has a web client only and no offline mode (research proposal: prototype scope and out-of-scope list), so almost all lateness comes from two sources: delivery reordering of answers submitted seconds apart, which is *routine*, and instructor corrections, which are rare. For the routine case, B would down-weight a perfectly good observation for no reason and A would throw it away; C costs a recomputation over a few dozen rows. Paying an approximation to save that is a bad trade. **If an offline client is ever added, revisit this decision** — multi-day lateness would become routine and the cost profile of C changes.

**How C works — within the learner lock (AP-2), in the same transaction as the idempotency claim (§6.2):**

1. Determine the affected set: the late event's target tuples (primary + cognitive-axis, §3.7) and, for every transition on those tuples with `occurred_at ≥` the late event's `occurred_at`, the tuples it propagated to (§6.4). Depth ≤ 2 bounds this set.
2. Reconstruct each affected tuple's state as of the late event's `occurred_at` from its last transition before that instant.
3. Re-fold all evidence for those tuples from that instant onward, **ordered by `occurred_at`**, the late event included, under the transitions' recorded `model_config_version`.
4. **Append** exactly one `REORDER` transition per affected tuple: `evidence_event_id` = the late event, `alpha_before`/`beta_before` = the tuple's **current snapshot**, `alpha_after`/`beta_after` = the re-folded result, `recorded_at = now()`. Then upsert the snapshot. Earlier transitions are **never edited**: they remain the record of what the system believed at the time, which is exactly what the transaction-time query above needs (AP-1). Recording the re-fold as one before→after step per tuple — rather than re-emitting each intermediate step — keeps the `alpha_before = previous alpha_after` chain intact in `recorded_at` order, so the roadmap's P3 lost-update proof holds unchanged over late evidence.

**Note for the paper:** this is a genuine consistency trade-off, not an implementation detail — and the choice is defensible precisely because the lateness distribution here is dominated by seconds, not days.

### 6.6 State migration (block 4 — State Migration Handler)

Two independent version axes, and they need different handling:

**Ontology version changed** (a concept was split, merged, deprecated):

| Ontology change | State action |
|---|---|
| Concept renamed / re-identified | rewrite `concept_id`, emit `MIGRATION` transition |
| Concept split A → A1, A2 | copy state to both, **widen the variance** (multiply `n` by 0.5) — we are now less sure |
| Concepts merged A, B → C | combine as a precision-weighted average of the two posteriors |
| Concept deprecated | soft-delete: retain rows, exclude from reads |

The variance widening on split is the important one: after a split we genuinely know less about each finer-grained concept than we knew about the coarse one, and the state must say so.

**Precondition — LS-CR-001 (§11.4).** Every row of the table above is triggered by an explicit structural operation carrying an old→new id mapping. This module never *infers* a split or merge from ids appearing and disappearing: an unknown new id gets a prior (§3.3), and a vanished id without a `DEPRECATE` or `SPLIT`/`MERGE` operation is a contract violation — logged and alerted, with the rows retained and excluded from reads exactly as for a deprecation, so that the evidence can still be re-attached once the mapping is supplied.

**Model config version changed** (parameters retuned): do **not** rewrite existing state in place — the stored `(α, β)` were produced under different assumptions and are not comparable. Instead **replay** the evidence log under the new config into a shadow table, then swap. This is the payoff of AP-1, and it is also exactly the mechanism the Evaluation system's `Strategy Comparison` needs.

Migration runs as an offline job with the learner lock held per learner, in batches, and is itself recorded as `MIGRATION` transitions so the audit trail never has a gap.

---

## 7. Public API Contract

**This section is the deliverable that unblocks the rest of the team.** Freeze it first; teammates can then build against a mock while the internals are unfinished.

### 7.1 Design rules

1. **Read-only from outside.** The only write path is the evidence stream. There is no public `setMastery()`. Instructor overrides go through a separate, audited, authorization-gated endpoint.
2. **Never return a bare number.** Every mastery value ships with its confidence and evidence count. A consumer that ignores uncertainty is a bug we want to make visible, not easy.
3. **Bulk by default.** The Adaptive Engine needs state for dozens of concepts to rank candidate activities. A per-concept API guarantees an N+1 problem.
4. **`asOf` on every read.** Enables the Evaluation module's calibration analysis with no separate API surface.

### 7.2 Types

```typescript
export type CognitiveLevel = 'REMEMBER' | 'UNDERSTAND' | 'APPLY' | 'ANALYZE';

export type MasteryLabel =
  | 'UNKNOWN'         // insufficient evidence — probe before concluding anything
  | 'NOT_MASTERED'
  | 'DEVELOPING'
  | 'MASTERED'
  | 'DECAYED'         // was mastered, has faded — needs review, not teaching
  | 'MISCONCEPTION';  // actively holds an incorrect belief

export interface ConceptStateView {
  conceptId:        string;
  cognitiveLevel:   CognitiveLevel;

  mastery:          number;            // posterior mean, 0..1, decay applied
  confidence:       number;            // 0..1 — evidence sufficiency (1 − n₀/n)
  credibleInterval: [number, number];  // 90% interval — statistical uncertainty
  label:            MasteryLabel;

  evidenceCount:    number;            // effective n = α+β
  directEvidence:   number;            // observations, excluding propagated
  lastEvidenceAt:   string | null;     // null ⇒ this is a prior, never observed
  isPrior:          boolean;           // true ⇒ nothing has ever been observed here

  peakMastery:      number;
  decayApplied:     number;            // how much decay reduced the mean — for explanations

  /** v0.5 — what was taught/shown, independent of belief (§3.10). null ⇒ never exposed. */
  exposure: {
    firstExposedAt: string;
    lastExposedAt:  string;
    count:          number;
    bySource:       Partial<Record<'LESSON' | 'READING' | 'WORKED_EXAMPLE' | 'PRACTICE' | 'CONVERSATION', number>>;
  } | null;
}

export interface MisconceptionView {
  misconceptionId:  string;
  conceptIds:       string[];
  activation:       number;            // 0..1
  confidence:       number;
  firstDetectedAt:  string;
  lastEvidenceAt:   string;
  evidenceItemIds:  string[];          // the Explanation Builder needs concrete instances
}

export interface LearnerStateSnapshot {
  learnerId:        string;
  asOf:             string;
  ontologyVersion:  string;
  modelVersion:     string;
  concepts:         ConceptStateView[];
  misconceptions:   MisconceptionView[];
}
```

### 7.3 Service interface

```typescript
export interface ILearnerStateService {

  /** Bulk read. Unobserved tuples are returned as priors, never omitted. */
  getState(q: {
    learnerId:       string;
    conceptIds?:     string[];          // omit ⇒ all concepts with materialised state
    cognitiveLevels?: CognitiveLevel[];
    asOf?:           string;            // default: now
    includePriors?:  boolean;           // default true
  }): Promise<LearnerStateSnapshot>;

  /**
   * Gap Detector support: concepts below mastery threshold, ranked by
   * (a) how far below and (b) how confident we are about it.
   * This is the "simple filter over Learner State" from the team design.
   */
  getGaps(q: {
    learnerId:       string;
    scopeConceptIds?: string[];         // e.g. prerequisites of a learning goal
    threshold?:      number;            // default 0.7
    minConfidence?:  number;            // default 0.5 — excludes states we can't claim
    limit?:          number;
  }): Promise<Array<ConceptStateView & { gapMagnitude: number }>>;

  /**
   * Adaptive Engine support: where would a new observation most reduce
   * uncertainty? Highest-variance states, i.e. best diagnostic value.
   */
  getMostUncertain(q: {
    learnerId:       string;
    scopeConceptIds?: string[];
    limit?:          number;
  }): Promise<ConceptStateView[]>;

  /** Active misconceptions, optionally scoped to a concept set. */
  getMisconceptions(q: {
    learnerId:       string;
    conceptIds?:     string[];
    minActivation?:  number;            // default 0.3
  }): Promise<MisconceptionView[]>;

  /**
   * Readiness for a target concept: are its prerequisites in place?
   * A FACT about the learner, not a decision (§1.3): `ready` is true iff every
   * prerequisite whose edge strength ≥ minEdgeStrength passes the MASTERED test
   * of §3.6, i.e. P(θ > θ*) ≥ credibility, decay applied. Which edges count is
   * the caller's policy and is passed in; what "mastered" means is this module's
   * and is never re-implemented by a consumer.
   */
  getReadiness(q: {
    learnerId:        string;
    targetConceptId:  string;
    minEdgeStrength?: number;           // default 0 ⇒ every prerequisite edge counts
  }): Promise<{
    ready:            boolean;
    blockingConcepts: ConceptStateView[];  // the prerequisites that fail the test
    confidence:       number;           // min confidence over the prerequisites considered
  }>;

  /** Audit / explanation: the transition history for one tuple. */
  getHistory(q: {
    learnerId:       string;
    conceptId:       string;
    cognitiveLevel?: CognitiveLevel;
    from?:           string;
    to?:             string;
    limit?:          number;
  }): Promise<StateTransitionView[]>;

  /** Time series of mastery for one tuple — for dashboards and evaluation. */
  getTrajectory(q: {
    learnerId:       string;
    conceptId:       string;
    cognitiveLevel:  CognitiveLevel;
    granularity:     'DAY' | 'WEEK';
    from:            string;
    to?:             string;
  }): Promise<Array<{ at: string; mastery: number; confidence: number }>>;
}
```

### 7.4 REST surface (NestJS)

| Method | Path | Consumer |
|---|---|---|
| `GET` | `/learners/:id/state?conceptIds=&levels=&asOf=` | both engines |
| `GET` | `/learners/:id/gaps?scope=&threshold=` | Diagnosis — Gap Detector |
| `GET` | `/learners/:id/uncertain?scope=&limit=` | Adaptive — Target Selection |
| `GET` | `/learners/:id/misconceptions` | Diagnosis — Misconception Analyzer |
| `GET` | `/learners/:id/readiness/:conceptId?minEdgeStrength=` | Diagnosis — Prerequisite Analyzer; Adaptive — prerequisite gate |
| `GET` | `/learners/:id/concepts/:conceptId/history` | Explanation Builder, audit |
| `GET` | `/learners/:id/concepts/:conceptId/trajectory` | dashboards, Evaluation |
| `POST` | `/internal/evidence` | Evidence Module **only** — network-restricted (§9.2) |
| `POST` | `/internal/exposure` | Evidence Module **only** — network-restricted; `ExposureEvent` (§6.1a) |
| `POST` | `/learners/:id/overrides` | instructor role only, fully audited |

### 7.5 Consumer usage patterns

Mapping the API onto what the other two engines in the team design actually need:

**Diagnosis Engine — Gap Detector → Root Cause Orchestrator**

```typescript
const gaps = await state.getGaps({ learnerId, scopeConceptIds: unitConcepts });

// Prerequisite Analyzer
const readiness = await state.getReadiness({ learnerId, targetConceptId: gaps[0].conceptId });

// Misconception Analyzer
const mis = await state.getMisconceptions({ learnerId, conceptIds: [gaps[0].conceptId] });

// Cognitive Gap Analyzer — the reason cognitiveLevel is in the primary key
const levels = await state.getState({
  learnerId,
  conceptIds: [gaps[0].conceptId],
  cognitiveLevels: ['REMEMBER','UNDERSTAND','APPLY','ANALYZE'],
});
// high REMEMBER + low APPLY ⇒ procedural gap, not a knowledge gap
```

**Adaptive Engine — Target Selection**

```typescript
// what to work on: real gaps, weighted by confidence
const targets = await state.getGaps({ learnerId, minConfidence: 0.5 });

// what to probe: where we are least certain — highest information gain
const probes  = await state.getMostUncertain({ learnerId, limit: 5 });
```

The split between `getGaps` (act on what we know) and `getMostUncertain` (find out what we don't) is the **exploit/explore** boundary. It exists in the API on purpose: the Adaptive Engine must be able to choose between teaching and diagnosing, and it cannot make that choice from a single scalar mastery number.

---

## 8. Scalability and Performance

### 8.1 Workload characterisation

| Path | Frequency | Latency budget (p95) | Shape |
|---|---|---|---|
| Evidence ingest | 1 per learner interaction | 200 ms (async) | write, serialised per learner |
| `getState` | several per diagnosis/adaptation cycle | 50 ms | point read, learner-scoped |
| `getGaps` | 1 per diagnosis cycle | 100 ms | small scan, learner-scoped |
| `getHistory` | rare (explanation, audit) | 500 ms | range scan |
| Evaluation batch | nightly | minutes | full scan, offline |

The system is **read-dominated by roughly 10:1** and every online read is scoped to one learner. That single fact drives the entire physical design: partition and index by learner, and no online query ever needs to touch another learner's data.

### 8.2 Sizing

Dense cardinality is `learners × concepts × 4`, which is the number that scares people:

| Scenario | Learners | Concepts | Dense rows | Sparse @ 5–15% | Verdict |
|---|---|---|---|---|---|
| Prototype | 200 | 300 | 240 K | ~35 K | trivial |
| Course-scale | 5 K | 800 | 16 M | ~1.6 M | single Postgres, comfortable |
| Institution | 50 K | 2 000 | 400 M | ~20 M | partition by `hash(learner_id)`, still one Postgres |

**Sparsity is the mechanism that makes this tractable**, and it is a design decision, not an accident: rows are materialised only when evidence exists, and everything else is served from a computed prior (§3.3). A design that eagerly initialises every learner against every concept multiplies storage by 7–20× and buys nothing, because the eager rows contain no information.

Transition volume is the real growth driver: roughly 8 transitions per evidence event (1 primary + ~3 cognitive + ~4 propagated). At institution scale that is on the order of 10⁸ rows/year — hence `PARTITION BY RANGE (recorded_at)` monthly, with partitions older than 12 months detached to cold storage. Retention policy must be explicit; "keep everything forever" is not a plan.

### 8.3 Caching — cache the undecayed state, not the answer

The natural instinct is to cache `getState` responses. **Don't**: the response depends on `now()` through decay, so it is stale the moment it is written, forcing a short TTL and gutting the hit rate.

Instead:

```
cache key:   ls:{learnerId}:{ontologyVersion}:{modelVersion}
cache value: raw (α, β, last_evidence_at, priors)   ← time-invariant
TTL:         long (1 h) — invalidated explicitly on LearnerStateChanged
read path:   cache hit → apply DecayFunction(now) → serialise
```

Because the cached value is time-invariant, it is only invalidated by an actual state change. Decay is applied after the cache read, so responses stay exactly correct at all times. Including the ontology and model versions in the key makes deployments self-invalidating.

Expected hit rate is high: a diagnosis cycle issues several reads for the same learner within seconds.

### 8.4 Known bottlenecks and their mitigations

| Bottleneck | Cause | Mitigation |
|---|---|---|
| Per-learner lock contention | one learner, many rapid submissions | micro-batch events per learner (100 ms window) and apply as one transaction |
| Propagation write amplification | ~8 rows per event | depth cap, ε-threshold gate (§6.4); batch-insert transitions |
| Graph traversal latency in the hot path | cross-service call per event | **replicate the ontology locally** (§5.5) — removes the call entirely. Interim: fetch before the lock, cache by `ontology_version` |
| Lock contention on a hot learner | rapid successive submissions | 64-bit lock keys (§6.2.1); micro-batching; ultimately Kafka partitioning |
| Transition table growth | append-only by design | monthly partitions, detach + archive after 12 months |
| Cross-learner analytical scans | Evaluation module | run against a read replica, never the primary |

### 8.5 Failure modes

| Failure | Behaviour | Recovery |
|---|---|---|
| Duplicate event delivery | no effect | idempotency ledger (§6.2) |
| Crash mid-update | transaction rolls back; event redelivered | at-least-once + idempotency ⇒ exactly-once effect |
| Graph DB / ontology replica unavailable or stale | propagation skipped, primary update still applied, event flagged `propagation_deferred` | **degrade, do not fail** — losing the primary update because a secondary enrichment is down is the wrong trade |
| Signature verification fails | event rejected before any state is touched; security alert | investigate; never "accept and flag" — an unverified event is not evidence |
| Snapshot table corrupted | reads wrong | rebuild by replaying `state_transition` (AP-1) |
| Model config bug ships | state drifts | replay under corrected config into a shadow table, then swap (§6.6) |
| Poisoned evidence detected | state inflated | reverse by replaying with the offending `event_id` excluded — the reason `evidence_event_id` is on every transition |

The last row is worth emphasising: because state is a projection of a log, **any bad input can be surgically removed and the state rebuilt without it**. With in-place mutation, the same incident is unrecoverable.

---

## 9. Security Architecture

Learner state is a personal educational record and, under GDPR, the basis of automated decisions affecting the individual. Two consequences follow immediately: the data is sensitive, and **the decisions must be explainable** (Art. 22) — which retroactively justifies rejecting the neural model in §3.1 on legal as well as engineering grounds.

### 9.1 Threat model

| ID | Threat | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| **T1** | **Evidence poisoning** — forged evidence events inflate mastery | High | High | §9.2 |
| **T2** | **IDOR** — `/learners/{id}/state` with another learner's id | High | High | §9.3 |
| **T3** | Cypher / SQL injection through concept identifiers | High | Medium | parameterised queries only; validate ids as UUIDs at the DTO boundary; never string-concatenate Cypher |
| **T4** | Inference attack — `getTrajectory` exposes fine-grained behaviour (study times, struggle patterns) | Medium | Medium | role-scoped access; coarse granularity for non-owner roles; audit every cross-subject read |
| **T5** | Erasure request vs. immutable log | Compliance | Certain | crypto-shredding (§9.4) |
| **T6** | Resource exhaustion — unbounded `getState` / `getHistory` | Medium | Medium | mandatory `limit` with server-side cap; pagination; per-token rate limit |
| **T7** | Replay of a captured evidence event | Medium | Low | idempotency ledger makes replay a no-op (§6.2) |
| **T8** | Privilege escalation via the override endpoint | High | Low | separate role, mandatory reason string, immutable audit, alert on volume |

### 9.2 T1 — Evidence poisoning is the primary threat

This is the attack that actually matters, and it is specific to this module. A learner who can submit evidence events can mark themselves as having mastered everything — bypassing required content, and in a graded context, committing fraud. The system would show no error; the numbers would simply be wrong.

Controls, in depth:

1. **The evidence endpoint is not on the public edge.** `/internal/evidence` is reachable only from the Evidence Module — enforced at the network layer (security group / NetworkPolicy), not by an application-level check alone.
2. **Service-to-service authentication** — mTLS or a signed service token with a narrow audience claim. An authenticated *learner* token must never be sufficient to call it.
3. **Cryptographic signing of the event payload at source** — see §9.2.1. This is the control that survives an internal-network compromise.
4. **Every event must reference a verifiable attempt.** `attemptId` must exist, belong to `learnerId`, and be in a submitted state. This makes forgery require a real attempt, not just a well-formed JSON body.
5. **Outcomes are computed server-side, never client-supplied.** The client submits an answer; the Evidence Module grades it. A client that can send `outcome: 'CORRECT'` has already won.
6. **Anomaly detection as a backstop** — implausibly fast response times, impossible mastery velocity, or a burst of perfect answers should raise a flag. Detection is not prevention, but it bounds the damage window.
7. **Reversibility** — §8.5: replay without the offending events.

#### 9.2.1 Payload signing — Zero Trust for the evidence stream

Controls 1 and 2 are **perimeter controls**: they establish that the *connection* came from an authorised place. They say nothing about the *payload*, and they fail completely against the realistic attack — an attacker who has already pivoted onto the internal network, compromised any service holding a valid client certificate, or gained access to the message bus. Once inside the perimeter, forging evidence is trivial. For a system whose output affects grades and progression, "we trust everything inside the VPC" is not an adequate position.

**Control: the Evidence Module signs each event with a private key; Learner State verifies before the idempotency claim.** Signature verification is step 0 of §6.3 — before any state is touched, before the event is even recorded as seen.

```typescript
interface SignedEvidenceEvent {
  payload:   EvidenceEvent;
  signature: {
    alg:       'Ed25519';
    keyId:     string;      // for rotation
    value:     string;      // base64 over the canonical serialisation
    signedAt:  string;
  };
}
```

Implementation details that decide whether this actually works:

- **Canonicalisation is where signature schemes break.** Signing `JSON.stringify(payload)` is a bug: key order, unicode escaping, and number formatting all vary between serialisers and languages, producing valid events that fail verification and — worse — pushing teams to "fix" it by verifying a re-serialised copy, which voids the guarantee. Use **JCS (RFC 8785)** or sign a hash over an explicitly ordered field list. Specify this in the contract, not in prose.
- **Sign the whole semantic payload**, including `eventId`, `learnerId`, `attemptId`, `outcome`, `weight` and `occurredAt`. A signature covering only some fields lets an attacker rewrite the rest.
- **Ed25519 over RSA** — small signatures (64 bytes), fast verification (~50 µs), no parameter-choice footguns. Verification cost is irrelevant next to a database transaction.
- **Sign the canonical bytes directly. No pre-hash.** Ed25519 already hashes its input internally (SHA-512, per RFC 8032), so "SHA-256 the canonical form, then sign the digest" and "sign the canonical form" are *both* workable schemes — and they are not interoperable. If the Evidence Module implements one and Learner State verifies the other, **nothing will ever verify**, and the failure presents as a key-management or canonicalisation problem, which is where the debugging week goes. The contract says: `Ed25519_sign(privateKey, canonicalBytes)`, no intermediate digest. SHA-256 appears in this system in exactly one other place — `outcome_digest` (§6.2) — and the two must not be conflated in the P0 contract.
- **Key custody composes with Ed25519 on both major clouds**, which was not true until recently and is worth stating so nobody re-litigates the curve choice: Google Cloud KMS exposes `EC_SIGN_ED25519`, and AWS KMS added Ed25519 signing in November 2025. The prototype uses a locally generated dev keypair (§10.1); neither cloud is a dependency before P8.
- **Private key in a KMS/HSM, never in application config.** The Evidence Module calls a sign operation; it never holds the raw key. This is what makes compromise of the *service* insufficient to forge events retroactively.
- **`keyId` enables rotation** without a flag day: Learner State holds a small set of valid public keys with validity windows.
- **Replay of a validly signed event** is already neutralised by the idempotency ledger (§6.2) — a signature does not authorise re-application, and the two controls compose.

**Store the signature on the transition record.** Beyond preventing forgery, this gives **non-repudiation**: months later it is cryptographically provable which service asserted a given piece of evidence. In a system that affects academic outcomes, "prove this grade was derived from real evidence" is a question that will eventually be asked, and an unsigned log cannot answer it.

**The rejection path is dead-letter plus an alerting rate, not an HTTP status.** It is tempting to implement verification as a NestJS Guard that returns `403`, and for a synchronous caller that is a fine *side effect* — but it is not the control. Evidence ingest is asynchronous (§8.1), and in the target architecture it arrives from a Kafka partition where there is no status code to return and no client waiting for one. What the security requirement actually needs is: the event goes to a dead-letter store, the attempt is alerted on, and the **verification-failure rate** is monitored (R8) — a single forged event is noise, a rising rate is an attack or a botched key rotation. A Guard is the wrong layer to own dead-lettering and alerting; put verification where §6.3 puts it, at step 0 of the orchestrator, and let the HTTP edge translate the outcome into a status if a synchronous caller happens to be present.

**What signing does not solve, stated plainly:** it proves *origin*, not *truth*. If the Evidence Module itself is compromised, its signatures are valid and the evidence is still poison. Signing raises the bar from "reach the network" to "compromise the specific service and its KMS grant" — a substantial improvement, not a closed door. Controls 4–7 remain necessary; this is defence in depth, not a silver bullet.

### 9.3 T2 — Authorization

Three layers, deliberately redundant:

```
1. Non-enumerable identifiers  — learner_id is UUIDv7, never a sequential integer.
                                 (Sequential ids turn a missing authz check into a
                                  full database dump via a for-loop.)

2. Application authorization   — a policy guard on every endpoint:
                                 subject == learner  OR  subject teaches learner's course
                                 OR subject has an explicit analytics grant.
                                 Deny by default; the check is a guard, not an if-statement
                                 inside a service method.

3. Postgres Row-Level Security — RLS on EVERY learner-scoped table, keyed to a
                                 transaction-local variable set per request. Defence
                                 in depth: an authz bug in the app layer still cannot
                                 return another learner's rows.
```

#### 9.3.1 Making layer 3 real — three ways RLS looks enabled and does nothing

RLS fails **silently**: a misconfigured policy does not error, it simply returns every row. Each rule below closes one specific way that happens, and each has a P4 exit test in the roadmap.

**1. Coverage — every table that holds learner data, not one** (six since v0.5).

| Table | Learner data it holds |
|---|---|
| `learner_concept_state` | current mastery |
| `state_transition` | the learner's **entire** history — `getHistory`/`getTrajectory` read it, so an IDOR here is a full-history leak |
| `learner_misconception_state` | active misconceptions |
| `processed_event` | `deferred_payload` holds full signed evidence events (§6.5) |
| `exposure_event`, `learner_concept_exposure` | what the learner was taught, and when *(v0.5, §3.10)* |

Policy on each: `USING (learner_id = current_setting('app.learner_id', true)::uuid)`. If the variable is unset, `current_setting(..., true)` returns NULL, the comparison is NULL, and **no rows** are returned — fail closed.

**2. The table owner bypasses RLS.** In Postgres, a table's owner is exempt from its policies unless the table is forced, and a role with `BYPASSRLS` is exempt always. A prototype that connects as the role that ran the migrations has RLS that never fires. Therefore:

- `ALTER TABLE … ENABLE ROW LEVEL SECURITY` **and** `ALTER TABLE … FORCE ROW LEVEL SECURITY` on every table above.
- Migrations run as `ls_owner`. The service never connects as it.
- Two runtime roles, neither owner, neither `BYPASSRLS`:
  - `ls_api` — read surface (§7.4). `SELECT` only; subject to the policy above.
  - `ls_ingest` — evidence pipeline (§6.3). Writes for any learner, so its policy is permissive (`USING (true)`) — ingest is protected by network placement, service authentication and payload signatures (§9.2), not by learner scoping. It is never reachable from the public edge.
- Cross-learner analytics (Evaluation) gets a third role with its own explicit grant, never `ls_api` with the variable left unset.

**3. Connection-pool leakage.** Connections are reused across requests. `SET app.learner_id = …` is **session**-scoped: it survives on the pooled connection, and the next request — a different user — inherits it. Set it **transaction-locally** instead, as the first statement of every request's transaction:

```sql
SELECT set_config('app.learner_id', $1, true);   -- true ⇒ local to this transaction
```

The value is discarded at `COMMIT`/`ROLLBACK`, so a reused connection starts with the variable unset — which, by rule 1, returns nothing.

**The graph database is never exposed.** Neo4j's native authorization is coarse, and no learner-scoped query should ever reach it — the graph holds only ontology, which is not personal data. All learner data access goes through the service layer where RLS applies. If a future requirement seems to need learner-scoped graph queries, that is a signal the AP-5 boundary is being violated.

### 9.4 T5 — Erasure vs. an append-only log

GDPR Art. 17 requires deletion; AP-1 requires immutability. These are genuinely in tension, and hand-waving it is a weakness a reviewer will find.

**Solution: pseudonymisation plus crypto-shredding.** This module already stores no direct identifiers — no name, no national id — only `learner_id`, a UUID whose link to a person lives in the identity service (§5.1). Severing that link is necessary but **not sufficient**: hundreds of log rows sharing one pseudonym, with exact timestamps and item ids, are a behavioural fingerprint that can be re-joined to a person (course roster + lab attendance at 14:02). Under GDPR, pseudonymised data is still personal data. So the quasi-identifying fields are additionally encrypted with a per-learner data encryption key (DEK), wrapped by a KMS master key, and erasure destroys the DEK. The log stays byte-for-byte immutable (AP-1); the encrypted content becomes unrecoverable.

**Column-by-column decision (v0.5).** "Personally identifying fields" is not a specification — P2 cannot build an encrypted-column layout from it.

| Table / column | Treatment | Why |
|---|---|---|
| `learner_id` (every table) | **plaintext pseudonym** | primary key, RLS predicate (§9.3.1), advisory-lock key (AP-2), partition locality — cannot be encrypted. Its link to a person is destroyed in the identity service |
| `state_transition.item_id` | **encrypted** (`BYTEA`) | a specific item plus an exact time is a fingerprint |
| `state_transition.evidence_signature` | **encrypted** (`BYTEA`) | signs a payload containing `attemptId`, which joins back to the Evidence Module's records |
| `processed_event.deferred_payload` | **encrypted** (`BYTEA`) | the full signed event — `learnerId`, `attemptId`, answer metadata |
| `α`, `β`, `outcome`, `weight`, `responsibility_q`, `concept_id`, `cognitive_level`, `transition_type` | plaintext | the statistical residue the Evaluation module needs; not identifying on its own |
| `occurred_at`, `recorded_at` | plaintext — **stated limitation** | `recorded_at` is the partition key and `occurred_at` drives replay order; neither can be encrypted |
| `exposure_event.content_ref`, `exposure_event.evidence_signature` | **encrypted** (`BYTEA`) | which lesson, and when, is as identifying as which item *(v0.5)* |
| `learner_concept_state`, `learner_misconception_state`, `learner_concept_exposure` | **hard-deleted** on erasure | derived read models (AP-1) — deleting a cache is not mutating the record |
| Read-through cache (§8.3) | **purged** on erasure | otherwise it serves the erased learner's state until TTL |

Keys live in `learner_key (learner_id PK, wrapped_dek BYTEA NOT NULL, key_version INT NOT NULL, destroyed_at TIMESTAMPTZ)`; erasure overwrites `wrapped_dek` and stamps `destroyed_at`. Reads of an erased learner's encrypted columns return NULL, never an error.

**Stated honestly in the paper — what this does and does not achieve:**

1. **Strong pseudonymisation, not anonymisation.** After erasure the residue still shares one pseudonym and carries exact timestamps. The claim is "no link to a person remains in this module", not "statistically anonymous".
2. **Erasure is cross-module.** The identity service must destroy the `learner_id` ↔ person mapping and the Evidence Module must erase its attempt records; this module alone cannot guarantee erasure. The erasure request is an orchestrated workflow, and this module's part is listed above.
3. **Backups.** A backup taken before erasure contains the wrapped DEK, and the KMS master key that unwraps it is still alive. Backups therefore need a retention window shorter than the erasure SLA, or the DEK must be held in the KMS itself. The prototype states this rather than solving it.

What survives erasure — and should — is the pseudonymous statistical residue: *"some learner's mastery of concept C moved from 0.42 to 0.51 on this date"*. That keeps the Evaluation module's aggregate analyses valid after erasure requests.

### 9.5 Baseline controls

- TLS 1.3 in transit; encryption at rest (disk-level plus column-level for the fields above).
- All identifiers validated as UUIDs at the DTO boundary (`class-validator`); numeric parameters range-checked. Reject, do not coerce.
- Structured audit log for: cross-subject reads, overrides, migrations, erasures. Append-only, separate retention.
- No learner data in application logs — log `learner_id` only, never mastery values or item content.
- Dependency scanning and secret scanning in CI; no credentials in config files.

---

## 10. Implementation Plan

Ordered so that **the interface others depend on ships first**, and every phase produces something demonstrable. The stack these phases are built on — and the alternatives rejected — is recorded in **Appendix C**.

**Governing rule, added in v0.2:** *a phase is not done until the property it claims to establish has been tested.* The v0.1 plan had no exit criteria, which is why verification silently pooled at the end — concurrency tests that prove AP-2 had drifted into P8 alongside general load testing, three phases after the code they validate. That is a plan-shaped defect, not a scheduling detail: it means the phase that introduces the correctness risk ships without demonstrating correctness. Every phase below now carries an explicit **exit criterion**, and no phase's tests may be deferred to a later one.

| Phase | Deliverable | Exit criterion | Est. |
|---|---|---|---|
| **P0** | Frozen API contract (§7) + OpenAPI spec + in-memory mock service. **Plus the `SignedEvidenceEvent` envelope and the canonicalisation spec (§9.2.1).** | Diagnosis/Adaptive teams are building against the mock; Evidence team has the signed-envelope schema in hand | 3 d |
| **P1** | Functional core: `DecayFunction`, `MasteryUpdater`, `LabelClassifier`, `PriorResolver` — pure | All Appendix B vectors reproduce; all §12 invariants pass as property tests | 2–3 d |
| **P2** | Schema + repositories + `getState`; prior materialisation. **Bi-temporal columns and the `NUMERIC(12,6)` boundary land here** | Real read returns priors for unobserved tuples and decayed state for observed ones; a value written and re-read is byte-identical | 3 d |
| **P3** | Orchestrator write path: **signature verification (step 0)**, idempotency ledger, 64-bit learner lock, transition + snapshot in one transaction | **Idempotency, concurrency and signature-rejection tests all green** — see below | 5 d |
| **P4** | `getGaps`, `getMostUncertain`, `getReadiness` + `PostgresDomainGraph` (co-located ontology) | Diagnosis Engine runs end-to-end against real state | 3 d |
| **P4.5** | **Ontology replication seam**: local `concept_edge` table, `OntologyChanged` consumer interface, version-gap detection, reconciliation job | A simulated `OntologyChanged` event updates the local replica; an injected version gap triggers resync | 2 d |
| **P5** | Bounded propagation (cognitive + prerequisite) | Depth cap and no-re-propagation enforced and tested; ε-gate measured | 3 d |
| **P6** | Misconception tracking | Distractor → activation → `MISCONCEPTION` label, end to end | 3 d |
| **P7** | `getHistory`, `getTrajectory`, replay tooling | Replaying a fixed log twice yields identical `outcome_digest` | 3 d |
| **P8** | Caching, RLS policies, **KMS key integration and rotation**, load test, security review | p95 targets met; RLS blocks cross-learner reads with the app guard disabled | 3 d |

**Total: 31 working days (~6 weeks)** for one developer, excluding integration time with other modules.

**Critical-path note:** P0 and P1 have no dependency on any other team. Start there on day one — `IDomainGraph` (§5.4) lets you stub the ontology entirely.

**Droppable under time pressure**, in this order: P6 (misconceptions — depends on the Task module anyway), P5 (propagation — everything works without it), P4.5 (the seam can be documented as design-only). **P0–P3 are not droppable**: they are the contract, the model, and the correctness core.

### 10.1 Where the v0.2 changes landed, and why

**Signature verification moves to P3 — and its *envelope* moves all the way to P0.** The review correctly placed implementation in P3: §6.3 makes verification step 0 of the pipeline, so a write path that accepts unverified events is not a partial implementation, it is a wrong one, and "reject unverified events" cannot be retrofitted as hardening.

But there is an earlier dependency the review didn't reach. The `SignedEvidenceEvent` shape and the RFC 8785 canonicalisation rule are a **contract between two teams**, and the Evidence Module has to produce that envelope. If the envelope is first defined in P3, the Evidence team will already have built and tested unsigned events, and P3 becomes a renegotiation instead of an implementation. **The schema belongs in P0 with the rest of the frozen contract; only the verification logic belongs in P3.**

To keep P3 off the critical path of another team, split the work by what it depends on:

| Work | Phase | Depends on |
|---|---|---|
| Envelope schema + canonicalisation spec | P0 | nobody |
| Verification logic, rejection path, dead-letter, alerting — using a **locally generated dev keypair** | P3 | nobody |
| KMS-held keys, rotation, overlapping validity windows | P8 | infrastructure |

Verifying against a dev keypair exercises every code path that matters — canonicalisation, signature check, rejection, alerting — with zero infrastructure. Swapping the key source for a KMS later touches one provider class. This keeps the security-critical behaviour in P3 where the review rightly wants it, without making P3 wait on key management.

**P1 shrinks (3–4 d → 2–3 d).** With the SQL decay view gone (§5.3), `DecayFunction` is one pure function with one implementation. No database fixtures, no cross-language consistency harness, no dual-maintenance burden downstream. The verification script already covers its behaviour; P1 is now largely a port of `verify_mastery_model.py` into TypeScript property tests.

**P4.5 exists, but its scope needs a judgement call the review left open.** The plan must say when `ReplicatedDomainGraph` arrives — agreed. But building full asynchronous replication in *this* prototype would be speculative work, because in the prototype the ontology lives in the same Postgres instance: `PostgresDomainGraph` is already the degenerate case of the replicated design, co-located with zero replication lag. The architecture in §5.5 matters when the Knowledge Graph becomes a separate service, which is out of scope for the academic prototype.

So P4.5 delivers **the seam, not the machinery**:

- a local `concept_edge` table owned by Learner State (not a foreign-key join into someone else's schema);
- an `OntologyChanged` consumer interface with an in-process implementation;
- version-gap detection and the reconciliation job — **these are built now**, because they are the parts teams habitually skip and then discover missing under a production incident;
- `ReplicatedDomainGraph` implementing `IDomainGraph` over the local table.

The migration to a genuinely remote Knowledge Graph then becomes a transport swap behind an existing interface, and the document can state the target design with a credible migration path rather than claiming an unbuilt capability. Splitting this out of P4 also keeps the Diagnosis-Engine-facing API work from competing with ontology plumbing, as the review suggested.

### 10.2 Testing strategy

Each test level is bound to the phase that must not ship without it.

| Level | What | Phase gate |
|---|---|---|
| Unit (core) | Every equation in §3 against Appendix B vectors | **P1** |
| Property-based | `Δt=0` is the identity; decay never raises the mean; `α,β > 0`; `n ≤ n_max`; update monotone in outcome; confidence outcome-independent | **P1** |
| Idempotency | Same event delivered 100× ⇒ exactly one *effect*; `outcome_digest` stable | **P3** |
| **Concurrency** | 20 parallel events for one learner ⇒ final state identical to sequential application **in `occurred_at` order**, and the lock-hold intervals do not overlap | **P3** |
| Security | Tampered payload rejected; unsigned event rejected; unknown/expired `keyId` rejected; canonicalisation stable across serialisers | **P3** (dev keys) → **P8** (KMS, rotation) |
| Ontology sync | `OntologyChanged` updates the replica; injected version gap triggers resync; reconciliation detects a silently divergent replica | **P4.5** |
| Propagation | Depth ≤ 2 enforced; derived transitions never re-propagate; ε-gate suppresses trivial updates | **P5** |
| Replay | Replay a fixed log twice ⇒ identical `outcome_digest` | **P7** |
| Load | 1 000 events/s ingest; `getState` p95 < 50 ms | **P8** |

Two tests carry more weight than the rest:

**The concurrency test proves AP-2 and belongs in P3, full stop.** Deferring it to a general load-testing phase confuses two different questions — *is it fast enough* (P8) versus *is it correct under concurrency* (P3). The second is not a performance property, and a lost update discovered in P8 invalidates every phase built on top of P3 in the meantime. It is also the test most likely to fail on first run.

*How to assert it, because the obvious method does not work.* Timing is not a correctness oracle: "parallel wall-time ≥ the serialised total" is both circular and flaky — it goes red on a loaded CI runner and green on a slow machine where the lock silently failed. Use two assertions instead, one for the outcome and one for the mechanism:

```sql
-- test-schema table.  NOT a TEMP table: temp tables are session-scoped, and the
-- 20 requests run on 20 pooled connections, so each would write to its own
-- invisible copy and the overlap query below would pass against nothing.
CREATE TABLE lock_audit (
    learner_id  UUID        NOT NULL,
    event_id    UUID        NOT NULL,
    locked_at   TIMESTAMPTZ NOT NULL,   -- clock_timestamp(), immediately after the lock
    released_at TIMESTAMPTZ NOT NULL    -- clock_timestamp(), immediately before COMMIT
);

-- must return zero rows
SELECT a.event_id, b.event_id
FROM   lock_audit a JOIN lock_audit b
       ON a.learner_id = b.learner_id AND a.event_id < b.event_id
WHERE  a.locked_at < b.released_at AND b.locked_at < a.released_at;
```

1. **Outcome:** the final `(α, β)` equals sequential application of the same events *in `occurred_at` order* (§6.5 — arrival order is not the invariant). Since v0.5 this holds for any fixture whose lateness is within `late_bound`, because late evidence is re-folded exactly; events beyond `late_bound` are deferred and excluded from the comparison.
2. **Mechanism:** the recorded hold intervals are pairwise non-overlapping.

Use `clock_timestamp()`, not `now()`/`transaction_timestamp()` — the latter are frozen at transaction start and would record identical instants for every transaction, producing a vacuous pass. Because `released_at` is written just before `COMMIT` while the lock is actually held until the commit completes, the recorded intervals slightly *understate* the true hold: gaps between intervals are expected and fine, overlaps are the failure. Assertion 2 is what distinguishes "the lock worked" from "the test never created contention" — a green run that never exercised the lock is the failure mode that matters here, and it is invisible to assertion 1 alone.

**A signature check that silently passes is worse than no signature check**, because it manufactures unearned confidence. The security tests must include a *negative* case that provably fails verification — tamper one byte of the payload and assert rejection — not merely a positive case that passes.

---

### 10.3 Phase detail for P0–P3

The four phases on the critical path, in the order the work is actually done. P4–P8 remain as specified in the table above; nothing here replaces them.

**P0 — the contract (unblocks three teams).** Nothing here requires a database or a line of model code, which is the point: it is pure interface work that three other teams are waiting on.

1. **OpenAPI spec** for the §7.3 read surface — `getState`, `getGaps`, `getMostUncertain`, `getReadiness` — with the exact `LearnerStateSnapshot` shape, including `confidence` and `credibleInterval` as *separate* fields (§3.6).
2. **`SignedEvidenceEvent` schema** (§6.1 + §9.2.1), including `tenantId`, and the canonicalisation rule written as an **explicitly ordered field list** rather than a reference to a library. An ordered list is testable across languages, survives a serialiser upgrade, and can be checked into the contract; "both sides use RFC 8785" is a hope about two dependency trees. State the signing input as the canonical bytes with **no pre-hash**.
3. **Mock service** — a NestJS controller returning hard-coded snapshots that satisfy the schema, deployed to dev. It is a promise: P4 is where it is paid off with real implementations.

**P1 — the functional core.** Pure functions, no I/O, `float64` throughout (§5.6 rule 1 — no rounding in this layer). `DecayFunction`, `MasteryUpdater`, `LabelClassifier`, `PriorResolver`. Tests are the Appendix B vectors plus `fast-check` properties from §12. The offline sensitivity study (R1) starts here and runs **in parallel** with P2–P3; it blocks nothing, because parameters live in versioned config and retuning is a replay (AP-1).

**P2 — schema and reads.** Migrations for `learner_concept_state`, `state_transition` (range-partitioned), `processed_event`, `learner_misconception_state`, `model_config`. Both temporal columns (`occurred_at`, `recorded_at`) land here — they are a schema decision, and P3's concurrency assertion is undefined without `occurred_at`. So does the `NUMERIC(12,6)` boundary and its repository mapper (§5.6). Then `getState` with prior materialisation, replacing the first of the P0 mocks.

**P3 — the write path.** In this order:

| # | Step | Why here |
|---|---|---|
| 1 | Verify signature over the canonical bytes; on failure → dead-letter + alert, nothing recorded | §6.3 step 0 — before the event is recorded as even having been seen |
| 2 | Validate envelope; resolve graph neighbourhood **before** taking the lock | Holding a per-learner lock across a network call turns a 2 ms critical section into 50 ms (§6.3) |
| 3 | `INSERT … ON CONFLICT DO NOTHING RETURNING` on `processed_event` — 0 rows ⇒ ack and stop | §6.2 |
| 4 | `pg_advisory_xact_lock(hashtextextended(learner_id, 0))` | AP-2; 64-bit key per §6.2.1 |
| 5 | Load state, apply §3.4 and §3.5 in the pure core | full-precision arithmetic |
| 6 | Quantise to 6-decimal strings; compute `outcome_digest` over the §6.2 field list | one rounding event per write, at the boundary |
| 7 | Append transitions, upsert snapshot, write `outcome_digest`, `COMMIT` | claim and effect commit atomically |
| 8 | Post-commit: invalidate cache, publish `LearnerStateChanged` | never inside the transaction (§6.3) |

The out-of-order arrival policy (§6.5 — strategy C within `late_bound`, defer beyond it; decided in v0.5) is decided here rather than discovered later, because it changes what step 5 does with an event whose `occurred_at` precedes `last_evidence_at`.

### 10.4 Definition of done

Each criterion names the phase that delivers it. A criterion whose phase has been dropped must be struck from the list in the same edit — a defence checklist claiming a capability that was descoped is worse than an honest omission.

| # | Criterion | Delivered by |
|---|---|---|
| 1 | A tampered payload, an unsigned payload, and an unknown `keyId` are each rejected before any state is touched, and each raises an alert | P3 |
| 2 | The same event delivered 100× produces **exactly one effect** — one `processed_event` row, one set of transitions, a stable `outcome_digest`. Note this is *not* "one database write": one event legitimately writes ~8 transition rows plus a snapshot upsert plus the ledger row (§8.2) | P3 |
| 3 | 20 concurrent events for one learner yield the sequential result in `occurred_at` order, with non-overlapping lock-hold intervals (§10.2) | P3 |
| 4 | A read returns a materialised prior for an unobserved tuple and correctly decayed state for an observed one, with `confidence` and `credibleInterval` reported separately | P2 / P4 |
| 5 | Replaying a fixed log twice yields identical `outcome_digest` values; replaying under a *new* `model_config_version` changes them | **P7 — requires the replay tooling; do not claim this criterion without it** |
| 6 | With the application authorization guard disabled, RLS still blocks a cross-learner read; erasure destroys the DEK and leaves the log internally consistent (§9.3, §9.4) | P8 |
| 7 | Propagation depth never exceeds 2, and a `PROPAGATED` transition never triggers further propagation | P5 — **if P5 is dropped, strike this row** |

Criteria 5 and 6 are the ones most often quietly lost. Criterion 5 depends on a phase (P7) that a compressed plan tends to drop while keeping the claim; criterion 6 covers T2, which is a larger examiner target than T1 for a system holding student records — "can another student read this?" and "can a student be erased?" get asked before "how does your advisory lock work?".

---

## 11. Risks and Open Questions

### 11.1 Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | BKT parameters (`s`, `T`, `h_base`, `κ`) are guessed, not fitted — no training data exists | Estimates may be poorly calibrated | **Decision-stability analysis** (§11.2) — demonstrate that consumer-visible *decisions* are invariant to the parameters rather than claiming a calibration the data cannot support |
| R2 | Ontology is not stable while this module is being built | State keyed to concept ids that change | `IDomainGraph` port + `MIGRATION` transitions + id-stability contract **LS-CR-001** (§11.4) — requested from the Domain Knowledge team, must be agreed before P2 |
| R3 | Distractor→misconception mapping may not be delivered | Misconception tracking has no input | P6 is scheduled last and is independently droppable |
| R4 | Cognitive-level tagging of items may be inconsistent or missing | The Bloom dimension becomes noise | Default to `APPLY` when untagged; measure the tagged fraction and report it |
| R5 | Scope creep — "just add a recommendation" | Boundary erosion, module becomes untestable | §1.3 is a hard boundary; reject at review |
| R6 | ~~Duplication of decay logic between SQL and TypeScript~~ | — | **Eliminated** in v0.2: the SQL decay view was removed, leaving one implementation (§5.3) |
| R7 | Ontology replica drifts from the Knowledge Graph service | Propagation uses stale topology | Version-stamped events + gap detection + nightly reconciliation (§5.5); affected transitions identifiable by `ontology_version` and replayable |
| R8 | Signing key compromise or rotation error blocks ingest | Evidence stops flowing | KMS-held keys, overlapping validity windows, `keyId` on every event; alert on verification-failure rate (§9.2.1) |

### 11.2 R1 in detail — what synthetic data can and cannot prove

R1 is the most likely point of attack in a defence, and the instinctive mitigation is circular. Generating trajectories from a BKT process with parameters θ and then estimating with a BKT model at θ proves that the TypeScript implements the Python. It says nothing about whether BKT describes a student. **Synthetic data cannot validate calibration** — state that before a reviewer does.

Three things it *can* establish, in ascending order of value:

**1. Parameter recovery.** Generate with known `s`, `T`; measure how many observations bring the posterior mean within ±0.05 of truth. Yields a usable statement — *"mastery is identified to ±0.05 within N observations at s = 0.10"* — and tells the Diagnosis Engine how much evidence must exist before `getGaps` output means anything. It also anchors the `UNKNOWN`/`DEVELOPING` boundary of §3.6 in something other than taste.

**2. Decision stability — the argument that actually retires R1.** No consumer reads `μ`. The Gap Detector filters on the `label` enum; the Adaptive Engine consumes a *ranking* from `getGaps` and `getMostUncertain`. So the defensible question is not "are the numbers calibrated", which cannot be answered without real data, but **"does the decision change when the parameters do?"** Sweep the grid and, for each configuration, compare the resulting gap list against the default configuration's by top-*k* overlap (Jaccard) and Kendall's τ over the full ordering. If the top-5 gaps are stable across the plausible range, the arbitrariness of `s` and `T` has been shown not to propagate into curriculum decisions — a strong, honest claim that survives having no training data.

**3. Misspecification robustness.** Generate from a *different* process than the estimator assumes — an IRT-style logistic responder, a learner whose slip rate drifts with fatigue, or power-law rather than exponential forgetting — and show the estimator degrades gracefully instead of being confidently wrong. This is what answers the circularity objection, and it is nearly free once (1) exists.

**Scope the grid.** Of the fifteen parameters in §3.9, most are not in question: `g = 1/k` is *derived* from the item's option count rather than guessed, and `n₀`, `n_max`, `γ_p`, `γ_c` are design choices with stated rationales. The genuinely unfitted parameters are **`s`, `T`, `h_base`, `κ`**, plus the label boundaries `θ*` and the 0.80 credibility threshold — and the expectation is that the boundaries and `h_base` dominate decision flips far more than `s` does, since they sit directly on the enum edges while `s` mostly rescales convergence speed. Reporting that influence ranking is itself a result.

**Where it lives.** In Python, extending `verify_mastery_model.py` (§12) — this is research code that wants NumPy/SciPy and plots, not production code, and the existing script is already the numerical oracle for §3. It runs **offline and in parallel with P2–P3**, and gates nothing: parameters live in versioned config, so retuning is a replay (§6.6). The only thing that must be frozen early is the *shape* of the §3.9 parameter table, not its values.

### 11.3 Open questions for the team

1. ~~**Concept id stability**~~ — **Resolved in v0.5** by contract LS-CR-001 (§11.4): ids are immutable and never deleted, and every structural change arrives as an explicit operation with a mapping. §6.6 migration is therefore a rare, explicitly triggered event rather than something this module has to detect.
2. **Cognitive-level tagging** — will the Task module tag every item with a Bloom level? If not, the `cognitive_level` dimension degrades to a single default value and the Cognitive Gap Analyzer cannot function.
3. **Evidence weighting** — who computes `weight`, and from what? If the Evidence Module does not supply it, this module needs a default policy, and that policy becomes an unowned assumption.
4. ~~**Multi-tenancy**~~ — **Resolved in v0.5: single-tenant.** The prototype serves one institution. The irreversible half was already settled in v0.4 and stays: `tenantId` is carried inside the signed envelope (§6.1), so the log records it. The reversible half is now decided rather than deferred: **no physical `tenant_id` column** in keys, indexes or RLS policies. Revisit trigger: a second institution — at which point AP-1 makes the retrofit a schema migration plus a replay (§6.6), not a data-recovery problem.
5. ~~**Late evidence bound**~~ — **Resolved in v0.5** (§6.5): `late_bound` = 7 days. Within it, late evidence is applied exactly by re-folding the affected tuples; beyond it, it is recorded with `disposition = 'DEFERRED_LATE'` and applied only explicitly. Revisit if an offline client is added.
6. ~~**Partial credit semantics**~~ — **Resolved in v0.5** (§3.4 step 3): credit-weighted mixture of the correct and incorrect responsibilities. v0.4's "correct answer at reduced weight" is rejected — it made every partial answer, however low, raise mastery.

### 11.4 Cross-team contract requests

Requests this module makes of other modules. Each one is a precondition for a named part of this design; until it is agreed, that part rests on an unowned assumption.

#### LS-CR-001 — Concept-id stability (to: Domain Knowledge module)

**Status:** requested 2026-10-06 · **Needed by:** P2 · **Unblocks:** §6.6, risk R2, §11.3 #1

1. **An id is forever.** A `concept_id` (and a `misconception_id`) once published is never reused, never reassigned to a different concept, and never deleted. A concept that is withdrawn is marked `DEPRECATED`; its id remains resolvable through `IDomainGraph`.
2. **Structural changes are explicit operations.** The `OntologyChanged` changeset (§5.5) carries one typed operation per change, each with the full old→new mapping:
   - `SPLIT { from: A, into: [A1, A2, …] }`
   - `MERGE { from: [A, B, …], into: C }`
   - `REIDENTIFY { from: A, to: A′ }` — permitted, but should be rare
   - `DEPRECATE { id: A }`
3. **A rename is not a new id.** Changing a concept's label, description or language is an update to the existing node. Minting a new id to "fix" an existing concept is a `REIDENTIFY` and must be published as one.

**Why it is needed.** This module stores only foreign ids, never ontology content (§5.1). Without (2), a split is observationally identical to "A deleted, A1 and A2 created": the learner's accumulated evidence about A is orphaned and the two new concepts start from the prior. Without (1), §6.6 stops being a rare, explicitly triggered migration and becomes a guessing exercise this module has no information to perform.

**Analogy for reviewers:** this is API versioning applied to identifiers — a producer may evolve, but may not break its consumers without telling them how.

#### LS-CR-002 — Exposure events (to: Evidence Module)

**Status:** requested 2026-10-07 · **Needed by:** P0 (field list), P3 (ingest) · **Unblocks:** §3.10, R9

1. Emit an `ExposureEvent` (§6.1a) whenever a learner is taught or shown material: lesson, reading, worked example, practice with feedback, tutoring conversation.
2. **Map the material to concept ids upstream.** This module never parses content.
3. Sign it with the same Ed25519 key and the same explicitly ordered field-list discipline as `SignedEvidenceEvent`; the field list is frozen in P0 alongside the evidence list.
4. Exposure is **not** assessment. Do not encode "the learner watched it" as an `EvidenceEvent` — that would move mastery on no evidence of knowing.

**Why it is needed.** Without it, "never taught" and "taught but not acquired" are indistinguishable in Learner State, and the Diagnosis Engine cannot choose between teaching and re-teaching differently.

---

## Appendix A — Reference Implementation of the Functional Core

```typescript
export interface BetaState {
  alpha: number; beta: number;
  alphaPrior: number; betaPrior: number;
  lastEvidenceAt: Date;
  halfLifeDays: number;
  reinforcementCount: number;
  peakMastery: number;
}

export interface ModelConfig {
  nMax: number;          // 30
  kappa: number;         // 1.0  spacing coefficient
  masteryThreshold: number; // 0.7
  masteryCredibility: number; // 0.8
}

/** §3.5 — exponential reversion toward the prior. Pure; `now` is an argument. */
export function decay(s: BetaState, now: Date, cfg: ModelConfig): BetaState {
  const dtDays = (now.getTime() - s.lastEvidenceAt.getTime()) / 86_400_000;
  if (dtDays <= 0) return s;

  const hEff = s.halfLifeDays * (1 + cfg.kappa * Math.log(1 + s.reinforcementCount));
  const d = Math.pow(2, -dtDays / hEff);

  return {
    ...s,
    alpha: s.alphaPrior + (s.alpha - s.alphaPrior) * d,
    beta:  s.betaPrior  + (s.beta  - s.betaPrior)  * d,
  };
}

/** §3.4 — evidence update with slip/guess correction and learning transition. */
export function update(
  s: BetaState,
  obs: { credit: number;  // 1 = CORRECT, 0 = INCORRECT, partialCredit for PARTIAL (§3.4)
         weight: number; slip: number; guess: number;
         hadInstruction: boolean; learnRate: number },
  now: Date,
  cfg: ModelConfig,
): BetaState {
  // Step 1 — bring to the present
  const d = decay(s, now, cfg);

  // Step 2 — current belief
  const p = d.alpha / (d.alpha + d.beta);

  // Step 3 — responsibility: P(knew | observation), credit-weighted mixture
  const qCorrect   = (p * (1 - obs.slip)) / (p * (1 - obs.slip) + (1 - p) * obs.guess);
  const qIncorrect = (p * obs.slip)       / (p * obs.slip       + (1 - p) * (1 - obs.guess));
  const q = obs.credit * qCorrect + (1 - obs.credit) * qIncorrect;

  // Step 4 — weighted Beta update
  let alpha = d.alpha + obs.weight * q;
  let beta  = d.beta  + obs.weight * (1 - q);

  // Step 5 — BKT learning transition: shift the mean, preserve precision
  if (obs.hadInstruction) {
    const n = alpha + beta;
    const m = alpha / n;
    const mStar = m + (1 - m) * obs.learnRate;
    alpha = mStar * n;
    beta  = (1 - mStar) * n;
  }

  // Step 6 — precision cap keeps the model responsive forever
  const n = alpha + beta;
  if (n > cfg.nMax) { const r = cfg.nMax / n; alpha *= r; beta *= r; }

  const mastery = alpha / (alpha + beta);
  return {
    ...d, alpha, beta,
    lastEvidenceAt: now,
    peakMastery: Math.max(s.peakMastery, mastery),
  };
}

export function mean(s: BetaState): number { return s.alpha / (s.alpha + s.beta); }

export function variance(s: BetaState): number {
  const n = s.alpha + s.beta;
  return (s.alpha * s.beta) / (n * n * (n + 1));
}

/**
 * Evidence sufficiency: the fraction of the belief that comes from observed
 * evidence rather than from the prior. Outcome-independent by construction —
 * see §3.6 for why the sd-based alternative was rejected.
 */
export function confidence(s: BetaState): number {
  const n0 = s.alphaPrior + s.betaPrior;
  const n = s.alpha + s.beta;
  return Math.max(0, Math.min(1, 1 - n0 / n));
}
```

## Appendix B — Verified Test Vectors

Computed from the equations in §3 (see §12 for the verification method). Use these directly as unit-test fixtures.

All figures below are **machine-generated output** from `verify_mastery_model.py`, not hand calculations. Use them directly as unit-test fixtures.

**Prior:** `Beta(0.6, 1.4)` — mean 0.3000, sd 0.2646, `n₀ = 2`.

### B.1 Evidence updates (single step, `w = 1.0`, no instruction)

| # | Start | Observation | `s` | `g` | `q` | Result `(α, β)` | Mean | Conf |
|---|---|---|---|---|---|---|---|---|
| 1 | Beta(0.6, 1.4) | correct | 0.10 | 0.25 | 0.6067 | (1.2067, 1.7933) | 0.4022 | 0.3333 |
| 2 | Beta(0.6, 1.4) | incorrect | 0.10 | 0.25 | 0.0541 | (0.6541, 2.3459) | 0.2180 | 0.3333 |
| 3 | Beta(0.6, 1.4) | correct | 0.10 | 0.05 | 0.8852 | (1.4852, 1.5148) | 0.4951 | 0.3333 |
| 4 | Beta(5.0, 5.0) | correct | 0.10 | 0.25 | 0.7826 | (5.7826, 5.2174) | 0.5257 | 0.8182 |
| 5 | Beta(5.0, 5.0) | incorrect | 0.10 | 0.25 | 0.1176 | (5.1176, 5.8824) | 0.4652 | 0.8182 |

**Vector 1 vs 3** — the *same* correct answer is much stronger evidence on an open-response item (`g = 0.05`, mean → 0.4951) than on a 4-option multiple-choice item (`g = 0.25`, mean → 0.4022). The responsibility term `q` is 0.885 versus 0.607: on the MCQ, nearly 40% of the credit is discounted as possible guessing. A naive `α += 1` update would miss this entirely and systematically overestimate mastery on multiple-choice assessments.

**Vector 2** — a single wrong answer moves the estimate only from 0.300 to 0.218. The model does not overreact to one observation.

**Vectors 1–3 all have `conf = 0.3333`** — identical, because confidence measures *how much* evidence we have, not what it said. This is the property that the corrected formula (§3.6) provides and the sd-based version did not.

### B.2 Learning transition (`T = 0.10`, applied after vector 2)

| | `(α, β)` | Mean | `n` |
|---|---|---|---|
| Before | (0.6541, 2.3459) | 0.2180 | 3.0000 |
| After | (0.8886, 2.1114) | 0.2962 | 3.0000 |

The mean rises by 0.078 while `n` is **exactly** unchanged: instruction moved what we believe without changing how much we know. Verified to machine precision.

### B.3 Decay from `Beta(8, 2)` (mean 0.800), `h_base = 14 d`, `r = 0`

| Δt | `d` | `α` | `β` | Mean | Conf | Note |
|---|---|---|---|---|---|---|
| 0 d | 1.0000 | 8.0000 | 2.0000 | 0.8000 | 0.8000 | identity |
| 7 d | 0.7071 | 5.8326 | 1.8243 | 0.7617 | 0.7388 | |
| 14 d | 0.5000 | 4.3000 | 1.7000 | 0.7167 | 0.6667 | one half-life |
| 30 d | 0.2264 | 2.2756 | 1.5359 | 0.5970 | 0.4753 | |
| 90 d | 0.0116 | 0.6859 | 1.4070 | 0.3277 | 0.0444 | |
| 365 d | 0.0000 | 0.6000 | 1.4000 | 0.3000 | 0.0000 | fully reverted to prior |

Confidence falls monotonically alongside the mean: after a year the system has not concluded that the learner *doesn't* know the concept — it has correctly returned to knowing nothing about it (mean = prior mean 0.300, conf = 0). **A mean-only decay implementation loses exactly this distinction**, and would instead assert with full confidence that mastery is 0.30.

### B.4 Spacing effect (`κ = 1.0`, Δt = 30 d, from Beta(8,2))

| `reinforcement_count` | `h_eff` | Mean after 30 d |
|---|---|---|
| 0 | 14.00 d | 0.5970 |
| 1 | 23.70 d | 0.6904 |
| 3 | 33.41 d | 0.7264 |
| 10 | 47.57 d | 0.7506 |

Repeated spaced review flattens the forgetting curve, as the psychological literature requires: after the same 30 days, a concept reviewed 10 times retains mastery 0.751 versus 0.597 for one never revisited.

### B.5 Mastery labelling (§3.6, `θ* = 0.7`, credibility 0.8)

| State | `peak` | Mean | `P(θ > 0.7)` | Conf | 90% CI | Label |
|---|---|---|---|---|---|---|
| Beta(3, 1) | 0 | 0.7500 | 0.6570 | 0.5000 | [0.368, 0.983] | `DEVELOPING` |
| Beta(12, 3) | 0 | 0.8000 | 0.8392 | 0.8667 | [0.615, 0.939] | `MASTERED` |
| Beta(1, 1) | 0 | 0.5000 | 0.3000 | 0.0000 | [0.050, 0.950] | `UNKNOWN` |
| Beta(2, 6) | 0 | 0.2500 | 0.0038 | 0.7500 | [0.053, 0.521] | `NOT_MASTERED` |
| Beta(2.28, 1.54) | 0.80 | 0.5969 | 0.3699 | 0.4764 | [0.203, 0.928] | `DECAYED` |

Row 5 is the B.3 state after 30 days of decay from `Beta(8,2)`. Its confidence (0.476) is below the `UNKNOWN` threshold — which is precisely why the `DECAYED` check must run first (§3.6).

**Rows 1 and 2 are the entire justification for AP-3.** Both have a high mean (0.75 and 0.80 — a 0.05 difference that a scalar model would consider negligible), but their credible intervals are utterly different: `[0.368, 0.983]` versus `[0.615, 0.939]`. The first learner's true mastery could plausibly be 0.37; the second's could not. Only the second is declared mastered. A scalar model treats these identically, and the Adaptive Engine would stop teaching a concept the first learner has not actually mastered — on the strength of three lucky answers.

---

## 12. Verification

The equations in §3 and every figure in Appendix B were computed and cross-checked numerically (Python + SciPy, `verify_mastery_model.py`) rather than derived by hand. **2 900 randomised property checks pass.**

Invariants asserted:

| Invariant | Status |
|---|---|
| `decay(s, Δt=0) = s` — zero elapsed time is the identity | ✅ |
| `decay(s, Δt→∞) → Beta(α₀, β₀)` — exact reversion to the prior | ✅ |
| Decay is monotone in `Δt` for both the mean and the precision `n` | ✅ |
| Variance increases monotonically under decay whenever `n > n₀` | ✅ |
| `q ∈ (0,1)` for all `p ∈ (0,1)` and valid `s, g` — no division by zero, no out-of-range responsibility | ✅ |
| A correct observation always raises the mean; an incorrect one always lowers it (for `s + g < 1`) | ✅ |
| The learning transition preserves `n` exactly | ✅ |
| The precision cap preserves the mean exactly while reducing `n` to `n_max` | ✅ |
| `α, β > 0` and `n ≤ n_max` hold through 100-step randomised evidence sequences | ✅ |
| `confidence = 0` exactly at the prior, rising monotonically with evidence | ✅ |
| `confidence` is outcome-independent — one observation is one observation | ✅ |
| Decay reduces confidence | ✅ |

### 12.1 What verification changed

Verification was not a rubber stamp — it caught three real defects in the draft:

1. **The confidence formula was wrong.** The original `conf = 1 − σ/σ_prior` made confidence depend on how extreme the mean was, so two learners with identical evidence received different confidence values purely because one answered correctly and the other did not (0.073 vs 0.220 in the original B.1). Replaced with `1 − n₀/n` (§3.6).
2. **The mastery-label precedence was wrong.** `UNKNOWN` was checked before `DECAYED`. Because decay lowers `n` and therefore confidence, a faded but previously-mastered concept fell through to `UNKNOWN` — throwing away the single most actionable fact about it. Caught only by running a decayed state through the classifier (Appendix B.5, row 5). Order corrected in §3.6.
3. **Several hand-computed figures in Appendix B were inaccurate** — e.g. `P(θ>0.7)` for `Beta(3,1)` is 0.657, not the 0.52 originally written, and the 30-day decay confidence was off by a factor of 2.5. All figures are now generated output.

The general lesson for the team: any equation that ends up in the paper should have a script that reproduces it. Hand-derived numbers in an architecture document are a liability, because reviewers *do* check them.

### 12.2 Running it

```bash
pip install scipy numpy
python3 verify_mastery_model.py
```

The script is the executable specification of §3. When a model parameter changes, run it first — it will tell you whether the invariants still hold before any TypeScript is written.

---

## Appendix C — Technology Decisions

The stack of record for the prototype. Each entry states what was chosen, what was rejected, and the property of *this* architecture that forced the choice — a stack list without that last column is a preference, not a decision.

### C.1 Application layer

| Concern | Choice | Rejected | Why this architecture forces it |
|---|---|---|---|
| Language | **TypeScript**, `strict` | JavaScript; Python for the service | The functional core (§4.1) is the correctness boundary of the module. Discriminated unions over `transition_type` and `evidence_outcome` make an unhandled case a compile error rather than a silently wrong Bayesian update |
| Framework | **NestJS** | Express, Fastify bare | Named in the project brief, and its DI container is what lets `IDomainGraph` (§5.4) be swapped between `PostgresDomainGraph`, `ReplicatedDomainGraph` and a test stub without touching call sites. Guards give the §9.3 policy check a home that is structurally impossible to forget, unlike an `if` inside a service method |
| Numeric type | `number` (float64) in the core; **canonical 6-decimal strings at the boundary** | `decimal.js` throughout | §5.6. Arbitrary-precision arithmetic in the core would be slower and would still need a canonical serialisation, so it solves the easy half of the problem |

### C.2 Data and persistence

| Concern | Choice | Rejected | Why |
|---|---|---|---|
| Database | **PostgreSQL 14+** | MySQL; Mongo | Four features are load-bearing and not portable: `pg_advisory_xact_lock` (AP-2), `hashtextextended` (§6.2.1), declarative range partitioning (§8.2) and row-level security (§9.3). This is not a preference — the concurrency argument does not survive a database swap |
| Access layer | **Prisma** — the team standard — with **raw SQL for this module's write path and RLS-scoped reads** *(v0.5, #23)* | Prisma's generated query API on the write path; a second access library (Kysely/Slonik) for this module only | The team adopted Prisma for every service; one access layer across a team of three is worth more than the ideal tool per module. Prisma's generated API cannot be trusted here, because the write path needs `INSERT … ON CONFLICT DO NOTHING RETURNING`, an advisory lock and a transaction-local RLS variable **on the same connection, in the same transaction**, and inserts into partitioned tables. So: every write-path and RLS-scoped statement runs as `$executeRaw`/`$queryRaw` on the `tx` handle inside one **interactive** `prisma.$transaction(async tx => …)`. The generated API is fine elsewhere (config, admin reads). See the rules below the table |
| Migrations | **Prisma Migrate with hand-written SQL** (`prisma migrate dev --create-only`, then edit the generated file) *(v0.5, #23)* | Letting Prisma generate DDL for these tables | Partition definitions, RLS policies (`ENABLE` + `FORCE`), `CHECK` constraints and enum types must be written as SQL — Prisma's schema language cannot express them. Migrations run as `ls_owner`; the runtime clients never do (§9.3.1). Versioned migration history is also what P7's replay tooling reconstructs old schemas against |
| Cache | **Redis — P8, not before** | Redis from day one | At prototype scale (§8.2: ~35 K rows) the entire working set is in Postgres shared buffers. §8.3 is a read-latency optimisation for institution scale. **Redis must never become a lock manager** — §6.2.1 rejects that in detail, and the most likely path to it is having Redis already deployed for an unrelated reason |
| Queue | **In-process bus now; Kafka at target scale** | Kafka in the prototype | AP-2: partitioning by `learner_id` replaces locking with ordering. The prototype's advisory lock is the same guarantee at a smaller scale, which is why it is an honest rehearsal rather than throwaway scaffolding |
| Graph | **`PostgresDomainGraph` behind `IDomainGraph`**; Neo4j only if the Domain module becomes a separate service | Neo4j in the prototype | §10.1: in the prototype the ontology is co-located, so `PostgresDomainGraph` *is* the degenerate case of the replicated design with zero lag. A second database is real operational cost for no prototype benefit |

**Prisma rules for this module (v0.5, #23).** Each closes a way the guarantees of §6.2 and §9.3.1 would break silently:

1. **One interactive transaction per event or request:** `prisma.$transaction(async (tx) => { … })`. Never the array form, never a bare `prisma.$executeRaw` outside it — Prisma may run consecutive top-level calls on different pooled connections.
2. **First statements inside it, in this order:** `SELECT set_config('app.learner_id', $1, true)` (reads) or the idempotency `INSERT … ON CONFLICT DO NOTHING RETURNING` followed by `pg_advisory_xact_lock(hashtextextended($1, 0))` (writes). All via `tx.$executeRaw` / `tx.$queryRaw` with tagged-template parameters — never `$executeRawUnsafe` with string concatenation (T3).
3. **Two clients, two roles.** `PrismaClient` for reads connects as `ls_api`; the ingest client connects as `ls_ingest`. Neither is the owner; `prisma migrate` uses a separate `ls_owner` URL.
4. **Set the interactive-transaction `timeout`** explicitly (Prisma's default is 5 s) — a re-fold under §6.5 can exceed it at scale; a timed-out transaction rolls back cleanly, which is safe but must be visible in metrics.
5. **Partitioned tables are declared in SQL and mapped read-only in `schema.prisma`** (or not mapped at all); Prisma must never attempt to create or alter them.

### C.3 Security and cryptography

| Concern | Choice | Notes |
|---|---|---|
| Signatures | **Ed25519**, Node's native `crypto` | No `libsodium` — native Ed25519 has shipped since Node 16, and a native build dependency buys nothing here. §9.2.1 |
| Signing input | **Canonical bytes, no pre-hash** | `Ed25519_sign(privateKey, canonicalBytes)`. Ed25519 hashes internally; a SHA-256 pre-hash is a *different, incompatible* scheme. This is the highest-risk line in the P0 contract |
| Canonicalisation | **Explicitly ordered field list**, specified in the contract | RFC 8785 (JCS) is the fallback if a library is preferred, but an ordered list is language-independent, testable, and immune to a serialiser upgrade — and this is a contract between two teams, not an internal detail |
| Digest | **SHA-256** over the §6.2 field list | The *only* other use of a hash in this module. Do not conflate it with the signing input |
| Key custody | **Dev keypair in P3; KMS in P8** | Ed25519 is available in GCP KMS (`EC_SIGN_ED25519`) and in AWS KMS since November 2025, so the curve choice does not constrain the cloud. A dev keypair exercises every code path that matters — canonicalisation, verification, rejection, alerting — with zero infrastructure |

### C.4 Testing and validation

| Concern | Choice | Bound to |
|---|---|---|
| Property-based tests | **fast-check** | P1 — the §12 invariants are the exit criterion, and vector tests alone do not cover the decay/update interaction |
| Unit vectors | Appendix B, as fixtures | P1 |
| Integration | **Testcontainers** (real Postgres) | P2/P3. Advisory locks, `ON CONFLICT` semantics and RLS cannot be exercised against an in-memory substitute; a mocked database would make the P3 concurrency proof meaningless |
| Numerical oracle | **Python + NumPy/SciPy** (`verify_mastery_model.py`) | §12. Two independent implementations agreeing on Appendix B is a stronger correctness argument than one, and SciPy's `betainc` is the reference for the credible intervals |
| Sensitivity study | Python, extending the same script | §11.2 — offline, parallel with P2–P3, gates nothing |

### C.5 What is deliberately absent

No service mesh, no Kubernetes, no separate analytics store, no ORM-generated SQL on the write path, no distributed lock manager, no message broker owned by this module in the prototype. Each would be defensible at institution scale and each is documented above with the trigger that would introduce it. The governing principle is the one in the header: this is an **academic prototype with a documented migration path**, and every component added now must earn its operational cost against a 200-learner workload — while every component *deferred* must have a named seam (`IDomainGraph`, the `OntologyChanged` consumer, the KMS key provider) so that adding it later is a substitution rather than a rewrite.
