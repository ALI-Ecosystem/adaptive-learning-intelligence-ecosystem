# Learner State Module — Implementation Roadmap

**Module:** Learner State (blocks 4 & 5)
**Companion:** `learner-state-architecture.md` v0.5 — this document sequences that one and adds nothing to it. Where they disagree, the architecture wins and this document is the defect.
**Version:** 0.4.3 — aligned to architecture v0.5 (#14–#23): Prisma, `getReadiness`, partial credit, exposure, team platform, honest schedule
**Date:** 2026-10-07

> **Changes in v0.4.3** (2026-10-07) — the roadmap caught up with every architecture v0.5 decision. Marked inline as *(v0.4.3)*.
>
> 1. **Access layer is Prisma** (architecture #23). P2 migrations are Prisma Migrate files with hand-written SQL; P3's whole pipeline runs inside one interactive `prisma.$transaction` with raw SQL on `tx`; P4 uses two Prisma clients (`ls_api`, `ls_ingest`). New exit criteria in P2, P3 and P4 test exactly the ways Prisma could break the guarantees silently.
> 2. **P0 contract updated** — `getReadiness` takes `minEdgeStrength` and no longer returns `readinessScore` (#16); `/internal/exposure` and `ExposureEvent` (#21).
> 3. **P1 gains partial credit** (#19): the credit-weighted mixture in `MasteryUpdater`, and properties I8–I9.
> 4. **Technology section no longer claims "unchanged from v0.4"**, and the *Excluded* list now reflects the team platform (Kafka, Redis, S3 exist team-wide; this module's prototype still does not depend on them).
> 5. **Schedule restated** for one developer at ~2.5 days/week: 33 days ≈ 13–14 calendar weeks before integration and write-up. Part 3 item 3 updated; new Part 3 item 5 lists the platform questions the team doc left open.
> 6. **Four leftovers fixed** (found while writing tasks against the architecture): the Access-layer note still said Kysely/Slonik "return `NUMERIC` as a string", contradicting P2 exit criterion 2; the P3 heading said 5 days against 6 in the table; P2 omitted `model_config` (architecture §10.3); P6 named `misconception_state` instead of `learner_misconception_state`.
>
> **Changes in v0.4.2.** Architecture v0.5 replaced the late-evidence strategy (§6.5): out-of-order evidence within `late_bound` (7 d) is now re-folded **exactly** in `occurred_at` order (strategy C); strategy B is gone. That reverses the premise of v0.4.1 change 5 / Change 6 below, so **P3 exit criterion 4 returns to `occurred_at` order**, scoped to fixtures within `late_bound`. P3 also gains the late-evidence path itself: a fixture with one event arriving out of order must produce the same final state as the in-order fixture, and a fixture beyond `late_bound` must leave state untouched with `disposition = 'DEFERRED_LATE'`. The lost-update chain proof is unaffected — v0.5 §6.5 records each re-fold as one before→after `REORDER` transition per tuple precisely so that it keeps holding.
>
> **Also in v0.4.2 — exposure layer** (architecture v0.5 #21): `ExposureEvent` field list frozen in P0; two new tables in P2; exposure ingest in P3 (+1 day, total 33); RLS tests cover six tables in P4. Exposure must never move `α`/`β` — add that as a P3 property test.
>

> **Changes in v0.4.1.** Eight edits to the v0.4 roadmap. Each is marked inline at the phase it affects, so it can be argued with rather than silently absorbed. Three of them are corrections to exit criteria that would have passed while the underlying claim was false — which is the specific failure mode a Definition of Done exists to prevent.
>
> 1. **P1's quantisation deliverable moved to P2.** §5.6 rule 1 states that the functional core computes in full `float64` and rounds nowhere. Filing "round `α` and `β` to 6 dp" under the phase that builds `MasteryUpdater` is how the rounding ends up inside `MasteryUpdater`.
> 2. **P1's decay property corrected.** *"Decay never raises the mean"* is **false** and is falsified by any uniform generator in under 200 draws (§P1, note).
> 3. **P2's exit criterion replaced.** It tested the read path; P2's actual claim is numeric determinism, and the criterion did not test it.
> 4. **P3's concurrency proof replaced.** Timestamp intervals in a scratch table are a stopwatch, not a proof. Chain continuity over `state_transition` is a proof, is one SQL query, and keeps holding in production.
> 5. **P3's ordering assertion corrected** from `occurred_at` to `recorded_at`. Asserting `occurred_at` order contradicts §6.5, which deliberately chose strategy B (append with reduced weight) over reordering.
> 6. **P0 gains two contract fields** — `interventionId` inside the signed canonical list, `retrievability` on `ConceptStateView`. The first is irreversible after P0; see the note there.
> 7. **RLS moved from P8 to P4.** It is a correctness property on the highest-impact threat, not a hardening task, and P4 is where real learner data first leaves the service.
> 8. **Estimates restored, with the total stated.** 31 working days with no slack, no integration time and no write-up is a planning fact, not a detail.

---

## Part 1 — Technology stack

Changed in v0.4.3: the access layer and migrations follow the team's Prisma standard (architecture v0.5 #23); everything else is unchanged from v0.4. The full justification, including what was rejected and why, is `learner-state-architecture.md` Appendix C — **read the five Prisma rules under C.2 before writing any repository code.**

### Application layer

| Concern | Choice | Note |
|---|---|---|
| Language | **TypeScript**, `strict` | Discriminated unions over `transition_type` and `evidence_outcome` make an unhandled case a compile error rather than a silently wrong Bayesian update |
| Framework | **NestJS** | Guards give the §9.3 authorization check a home that is structurally impossible to forget |

### Database and persistence

| Concern | Choice | Note |
|---|---|---|
| Database | **PostgreSQL 14+** | Four features are load-bearing and not portable: `pg_advisory_xact_lock`, `hashtextextended`, declarative range partitioning, row-level security |
| Access layer | **Prisma** (team standard); write path and RLS-scoped reads as raw SQL inside one interactive `$transaction` — architecture v0.5 App. C.2 rules *(v0.4.3)* | The write path needs `INSERT … ON CONFLICT DO NOTHING RETURNING`, a raw advisory-lock call in the same transaction, a transaction-local RLS variable, and inserts into a partitioned table — so those statements are raw SQL on `tx`. Prisma returns `NUMERIC` as `Prisma.Decimal`, never a JS `number`; the repository mapper converts it with `.toFixed(6)` and nowhere else (§5.6 rule 3; P2 exit criterion 2) |
| Migrations | **Prisma Migrate**, `--create-only` + hand-written SQL *(v0.4.2)* | Partition definitions, RLS policies and enum types must be raw SQL. P7's replay tooling reconstructs old schemas against this history |

### Security and cryptography

| Concern | Choice | Note |
|---|---|---|
| Signatures | **Ed25519**, Node native `crypto` (v16+) | No libsodium; a native build dependency buys nothing |
| Signing input | **Canonical bytes, no pre-hash** | `Ed25519_sign(privateKey, canonicalBytes)`. Ed25519 hashes internally; a SHA-256 pre-hash is a *different, incompatible* scheme |
| Canonicalisation | **Explicitly ordered field list**, not a library | Language-independent, testable, immune to a serialiser upgrade — and this is a contract between two teams, not an internal detail |
| Digest | **SHA-256**, reserved for `outcome_digest` only | Do not conflate with the signing input |
| Key custody | Dev keypair from P3; **KMS at P8** | A dev keypair exercises every code path that matters with zero infrastructure |

### Testing and validation

| Concern | Choice | Bound to |
|---|---|---|
| Property tests | **fast-check** | P1 |
| Numerical oracle | **Python + NumPy/SciPy** (`verify_mastery_model.py`) | P1 |
| Sensitivity / stability | Python, extending the same script; **Kendall's τ** | P1, offline, gates nothing |
| Integration | **Testcontainers** (real Postgres) | P2 onward |

### Excluded from this module's prototype

Cloud KMS, a second database, a service mesh — each with a named trigger in Appendix C and a named seam.

**Kafka, Redis and S3** now exist at team level (team architecture document, 2026-10-07). This module still does not *depend* on them before the phase that needs them: Redis enters at P8 as a read-through cache; Kafka, if the team runs it, replaces the in-process bus as the evidence transport **with `learner_id` as the partition key** (AP-2) — the advisory lock stays regardless, and the idempotency ledger already absorbs Kafka's at-least-once redelivery. *(v0.4.3)*

**Redis must never become a lock manager** — §6.2.1 rejects that in detail, and the most likely path to it is having Redis already deployed for something else and reaching for it.

---

## Part 2 — Phased roadmap

Phases execute in order. A phase is not complete until its exit criteria are *demonstrated*, not asserted.

| Phase | Deliverable | Days |
|---|---|---|
| P0 | The contract | 3 |
| P1 | Pure functional core and math | 3 |
| P2 | Schema, determinism, bi-temporality | 3 |
| P3 | Write path — signature, lock, transaction, late re-fold, exposure ingest | 6 |
| P4 | Diagnosis APIs **+ RLS** | 4 |
| P4.5 | Ontology replication seam | 2 |
| P5 | Bounded propagation | 3 |
| P6 | Misconception tracking | 3 |
| P7 | History and replay tooling | 3 |
| P8 | KMS, crypto-shredding, cache, scale | 3 |
| | **Total** | **33** |

**Read the total before reading the phases.** Thirty-three working days is roughly seven calendar weeks for one full-time developer — and about **13–14 calendar weeks at the ~2.5 days a week actually available** *(v0.4.3)*, and this schedule contains no integration time with the Evidence, Diagnosis or Adaptive teams, no slack, and no time for the write-up. If something has to give, **P4.5 and P6 are the phases whose claims the paper can most easily survive without**. P1, P3 and P7 are the ones that earn the reproducibility argument — dropping any of those while keeping the claim is precisely the failure the Definition of Done table exists to make visible.

---

### P0 — The contract (3 days)

**Goal:** unblock the Evidence, Diagnosis and Adaptive teams on day one. Nothing else in this roadmap has comparable leverage; every day P0 slips is a day three teams are blocked.

**Deliverables**

1. **OpenAPI spec** for `/learners/:id/state`, `/gaps`, `/uncertain`, `/misconceptions`, `/readiness` (with `minEdgeStrength`; **no** `readinessScore` — architecture v0.5 #16), and `/internal/exposure` *(v0.4.3)*. This is transcription of architecture §7.2–7.3, which are already frozen — it does not need the architect and can run in parallel with deliverable 2.
2. **The `SignedEvidenceEvent` canonical field list** (below). This one *does* need the architect and should be done first.
2a. **The `ExposureEvent` canonical field list** (architecture v0.5 §6.1a, LS-CR-002), frozen together with the evidence list and signed the same way; `exposure` on `ConceptStateView` in the OpenAPI spec. *(v0.4.2)*
3. **In-memory NestJS mock** returning schema-valid snapshots, deployed where other teams can reach it.

#### Two fields that must be added before the contract is frozen

**`interventionId` on `EvidenceEvent`, inside the signed field list.**

This is the addendum requested in `adaptive-learning-engine-architecture.md` §7.6. Without it there is no join between what was recommended and what the learner then did, which makes outcome attribution, scaffolding-aware evidence weighting and the entire Evaluation layer unimplementable.

It is urgent rather than merely important because of *where* it lives. Adding a field to the canonical list after P0 changes the byte layout, which is a signature-scheme version bump, which means the verifier carries two canonical forms indefinitely — and because AP-1 makes the log immutable, **history cannot be re-signed**. This is the identical argument v0.4 change #11 already accepted for `tenantId`, and `interventionId` has the stronger claim: `tenantId` is currently unused on the write path, while this field is load-bearing from the first integration.

**`retrievability` on `ConceptStateView`.**

The decay factor `d = 2^(−Δt/h)` at `asOf`. `decayApplied` is a different quantity and cannot be inverted without `h`, which depends on `reinforcement_count` and is internal to this module. The Adaptive Engine needs it for retention urgency and review scheduling; the alternative is that module re-implementing the half-life curve, which recreates exactly the two-implementations defect §5.3 was written to eliminate. Reversible later, so this is a convenience rather than a deadline — but it costs one line today.

#### The canonical field list

Fixed order — **not alphabetical**, and not derived from the TypeScript declaration order, because a refactor must not change the bytes.

```
 1  eventId                 UUID, lowercase, hyphenated
 2  tenantId                UTF-8 NFC
 3  learnerId               UTF-8 NFC
 4  itemId                  UTF-8 NFC
 5  attemptId               UTF-8 NFC
 6  interventionId          UTF-8 NFC, empty string if absent
 7  targets[]               see array rule below
 8  outcome                 CORRECT | INCORRECT | PARTIAL | SKIPPED
 9  partialCredit           decimal(6), empty string if absent
10  selectedDistractorId    UTF-8 NFC, empty string if absent
11  weight                  decimal(6)
12  itemParams.guessRate    decimal(6)
13  itemParams.slipRate     decimal(6), empty string if absent
14  itemParams.optionCount  integer, empty string if absent
15  hadInstruction          "true" | "false"
16  occurredAt              RFC 3339, UTC, exactly 3 fractional digits, "Z"
17  ontologyVersion         UTF-8 NFC
18  provenance.sourceService UTF-8 NFC
19  provenance.evidenceChain[] UUIDs, original order preserved
```

Encoding rules — all six matter, and each is a place two independent implementations will diverge:

| Rule | Specification |
|---|---|
| Field separator | `\x1f` (unit separator) |
| Array element separator | `\x1d` (group separator) |
| Array sub-field separator | `\x1e` (record separator) |
| `targets[]` ordering | sorted by `(conceptId, cognitiveLevel)`, each element serialised as `conceptId \x1e cognitiveLevel \x1e relevance` |
| `evidenceChain[]` ordering | **original order preserved** — it is a causal chain, and sorting it destroys the information |
| Numbers | canonical decimal string, exactly 6 decimal places, `.` separator, no exponent, no thousands separator, `-0` normalised to `0` |
| Integers | no decimal point |
| Absent optional values | empty string — **not** `"null"`, not omitted (omission changes the field count and therefore the byte layout) |
| Strings | UTF-8, Unicode NFC normalised |
| Booleans | lowercase `true` / `false` |

The two ordering rules pull in opposite directions on purpose. `targets[]` is a *set* the producer may emit in any order, so it is sorted to make the bytes canonical. `evidenceChain[]` is a *sequence* whose order is meaning, so it is preserved. Getting this backwards produces signatures that verify and provenance that lies.

**Exit criterion.** Diagnosis and Adaptive have each built at least one call against the mock. The Evidence team holds the field list **and a set of cross-language test vectors** — input JSON, expected canonical bytes as hex, expected signature — that their implementation reproduces before either service exists. Two teams agreeing on a prose description of a byte layout is not agreement; agreeing on hex is.

---

### P1 — Pure functional core and math (3 days)

**Goal:** prove the BKT and decay logic with no database in the picture.

**Deliverables**

1. `DecayFunction` and `MasteryUpdater` in **pure `float64`**, `now` passed as an argument.
2. `PriorResolver`, `LabelClassifier`.
2a. **Partial credit as a credit-weighted mixture** in `MasteryUpdater`: `q = c·q_correct + (1 − c)·q_incorrect` (architecture v0.5 §3.4 step 3, #19). The TypeScript core must reproduce `verify_mastery_model.py`'s partial-credit section, including the 20 × 10% regression (→ 0.146). *(v0.4.3)*
3. Python: extend `verify_mastery_model.py` to sweep the BKT parameter grid and report **Kendall's τ** on the induced ranking, addressing Risk R1.

> **Change 1 — quantisation is not a P1 deliverable.** v0.4 listed "round `α` and `β` to exactly 6 decimal places at the persist boundary" here. The *rule* is right; the *phase* is wrong, and the phase is what a developer reads. §5.6 rule 1 is explicit: the pure functions compute in full `float64` and return full `float64`; rounding happens once, in the repository mapper, which does not exist until P2.
>
> This is not pedantry about filing. One evidence event runs decay → primary update → cognitive propagation → prerequisite propagation. Round inside the core and you round four or more times per event instead of once, with the error biased in the direction of the rounding rule. It also breaks a stated invariant: Appendix B.2 asserts the BKT learning transition changes the mean while leaving `n = α + β` **exactly** unchanged. §5.6 measured independent 6-decimal rounding breaking that in 25.2% of transitions, maximum deviation 1 × 10⁻⁶ — reproduced here, same mechanism, same maximum deviation. The property test then either fails outright or gets weakened to a tolerance, and the paper loses a clean claim for nothing. Quantisation moves to **P2, deliverable 4.**

#### Exit criteria

All `fast-check` properties below pass, and the TypeScript core agrees with `verify_mastery_model.py` on every Appendix B vector to 1 × 10⁻⁹.

| # | Property | Status |
|---|---|---|
| **I1** | `Δt = 0` ⇒ state unchanged (identity) | unchanged from v0.4 |
| **I2** | **`\|μ′ − μ₀\| ≤ \|μ − μ₀\|`** — decay moves the mean monotonically **toward the prior** | **corrected** |
| **I3** | `Δt → ∞` ⇒ state converges to `(α₀, β₀)` | unchanged |
| **I4** | Decay is non-increasing in `n`: `n′ ≤ n`, and variance is non-decreasing | unchanged |
| **I5** | The BKT learning transition preserves `n` **exactly** in `float64` | scoped to the core |
| **I6** | Precision capping preserves `μ` to 1 × 10⁻¹² in the core; **no exactness claim after quantisation** | **corrected** |
| **I7** | `DECAYED` is evaluated before `UNKNOWN` for every reachable state | unchanged |
| **I8** | Credit `c = 1` and `c = 0` are **bit-identical** to `CORRECT` / `INCORRECT` | **new** *(v0.4.3)* |
| **I9** | Posterior mean is monotone non-decreasing in credit `c` | **new** *(v0.4.3)* |

> **Change 2 — I2 replaces "decay never raises the mean", which is false.** Decay reverts toward the **prior**, not toward zero (§3.5): `α′ = α₀ + (α − α₀)·d`. For a learner *below* `μ₀ = 0.30`, decay **raises** the mean.
>
> | State | `μ` | after 14 d | |
> |---|---|---|---|
> | `Beta(8,2)` | 0.8000 | 0.7167 | lowered |
> | `Beta(1,9)` | 0.1000 | **0.1333** | **raised** |
> | `Beta(2,28)` | 0.0667 | **0.0812** | **raised** |
>
> Falsified in under 200 uniform draws. `\|μ′ − μ₀\|` non-increasing holds over 200 000.
>
> The instructive part is *how this would have survived*. Every hand-written decay vector in Appendix B starts above the prior, because that is the intuitive case. The bug is only reachable from below, and only a uniform generator gets there. **Writing the property down wrong converts your strongest verification tool into one that agrees with the vectors you already had** — which is worse than having no property test, because it produces confidence.

> **Change 3 — I6 drops the exactness claim after quantisation.** Proportional capping preserves `μ` exactly in real arithmetic and to ~1 × 10⁻¹² in `float64`. It does *not* survive independent 6-decimal rounding, for the same reason I5 does not. Claim exactness in the core; claim a tolerance at the boundary. Asserting exactness where it does not hold produces a flaky test that gets deleted.

---

### P2 — Schema, determinism, bi-temporality (3 days)

**Goal:** lay a physical foundation whose numbers do not drift.

**Deliverables**

1. Migrations as **Prisma Migrate files with hand-written SQL** (`prisma migrate dev --create-only`, then edit): `learner_concept_state`, `state_transition` (range-partitioned monthly on `recorded_at`), `processed_event`, `learner_misconception_state`, `model_config` (architecture §10.3). Run as `ls_owner`. Partitioned tables are mapped read-only in `schema.prisma` or not mapped at all. *(v0.4.3)*
2. `α`, `β` and the priors as **`NUMERIC(12,6)`**, with the `precision_capped` CHECK bounding `α + β ≤ 1000`.
3. Bi-temporality: `occurred_at` (valid time) and `recorded_at` (transaction time), both indexed.
4. **The quantisation boundary** — the repository mapper rounds to exactly 6 decimal places, emits a decimal string, and nothing downstream re-rounds. *(Moved from P1; see change 1.)*
5. The encrypted-column layout for future crypto-shredding, with a dev key. Columns now, KMS at P8. The columns are named in architecture v0.5 §9.4: `state_transition.item_id`, `state_transition.evidence_signature`, `processed_event.deferred_payload` as `BYTEA`, plus the `learner_key` table. *(v0.4.2)*
6. `exposure_event` (range-partitioned on `recorded_at`) and `learner_concept_exposure` (architecture v0.5 §5.2). *(v0.4.2)*

#### Exit criteria

> **Change 4 — the v0.4 criterion tested the read path, not the claim.** "A read returns priors for unobserved tuples and decayed state for observed ones" is worth testing, but it passes with `DOUBLE PRECISION` columns and a driver that hands back floats. P2's headline claim is determinism, and §5.6 rule 2 is that *exactly one party rounds*.

1. **Round-trip is byte-identical.** Write a value through the mapper, read it back, assert the returned **string** equals the written string. Not approximate equality — string equality.
2. **`NUMERIC` never reaches the mapper as a JS `number`.** Through Prisma it arrives as `Prisma.Decimal`; the mapper converts it with `.toFixed(6)` and nowhere else *(v0.4.3)*. Asserted explicitly, because this is the surprise that gets "fixed" by an eager `parseFloat` in a mapper six weeks later.
3. **Nothing downstream re-rounds.** A value whose 6th decimal is a half-way case survives the round trip unchanged — `toFixed` and Postgres's `NUMERIC` cast disagree at exactly those points.
4. A read returns computed priors for unobserved tuples and decayed state for observed ones *(retained from v0.4)*.
5. Partition routing verified: an insert with `recorded_at` in month *n* lands in partition *n*.
6. **`prisma migrate diff` against the live schema is empty**, and no runtime role owns a table — the hand-written SQL is the schema, not a drift from it. *(v0.4.3)*

---

### P3 — The write path (6 days)

**Goal:** the atomic transaction engine and the zero-trust gate. This is the phase where a mistake is silent.

**Deliverables**

1. **Signature verification** — Ed25519 over the canonical bytes, **no pre-hash**, dev keypair, verified *before any state is touched*.
2. **Transaction pipeline**, all inside **one interactive `prisma.$transaction(async tx => …)`** with every statement as `tx.$executeRaw` / `tx.$queryRaw` (tagged templates only) and an explicit `timeout` *(v0.4.3)*, in this order: idempotency claim → fetch graph neighbourhood (**outside** the lock) → `pg_advisory_xact_lock(hashtextextended(learner_id, 0))` → decay → update → quantise → `outcome_digest` → persist → commit.
3. The idempotency insert and the state mutation in **one** transaction.
4. **Exposure ingest** — `POST /internal/exposure`, same signature check and idempotency ledger; appends `exposure_event`, upserts `learner_concept_exposure`, never touches `α`/`β`. *(v0.4.2, architecture §6.1a)*

#### Exit criteria

1. **Tampered or unsigned payloads are rejected before any state is touched**, and raise a security alert. Never "accept and flag" — an unverified event is not evidence.
2. **100 duplicate deliveries of one event produce exactly one effect**: one ledger row, one transition set, one stable `outcome_digest`.
3. **Chain continuity holds over the transition log.** *(replaces the timestamp assertion)*

> **Change 5 — timestamps in a scratch table are a stopwatch, not a proof.** v0.4 change #13 committed to a proof; writing `clock_timestamp()` at lock acquisition and before commit, then asserting the intervals don't overlap, demonstrates that *those twenty events on that run* did not overlap. It also instruments a lock that `pg_advisory_xact_lock` does not expose, and it goes stale the moment the test stops running.
>
> The proof is already in the data you persist. Every transition carries `alpha_before` and `alpha_after`. A lost update breaks the arithmetic chain, and that is checkable with one query:
>
> ```sql
> WITH chained AS (
>   SELECT learner_id, concept_id, cognitive_level, recorded_at,
>          alpha_before, alpha_after,
>          LAG(alpha_after) OVER (
>            PARTITION BY learner_id, concept_id, cognitive_level
>            ORDER BY recorded_at, transition_id
>          ) AS prev_alpha_after
>   FROM state_transition
> )
> SELECT * FROM chained
> WHERE prev_alpha_after IS NOT NULL
>   AND alpha_before IS DISTINCT FROM prev_alpha_after;
> -- must return zero rows
> ```
>
> Three properties the stopwatch version does not have. It **fails deterministically** rather than flakily. It requires no instrumentation the design does not already carry. And it is a **permanent invariant over production data**, not a test that passed once — it can be run as a nightly assertion for the life of the system.
>
> Note the dependency: `IS DISTINCT FROM` on `NUMERIC` is an exact comparison, which is only meaningful because P2 quantised. **The determinism decision is what makes the concurrency proof checkable at all** — two phases whose connection is easy to miss and expensive to sever.

4. **20 concurrent events for one learner produce the state of their sequential application in `occurred_at` order** — for fixtures whose lateness is within `late_bound` (architecture v0.5 §6.5). *(v0.4.2 — reverses Change 6 below.)*
5. **Late evidence:** a fixture in which one event arrives after later-occurring ones yields the same final state as the in-order fixture; an event later than `late_bound` leaves state untouched and is recorded `DEFERRED_LATE`.
6. **Exposure never moves mastery:** for any sequence of `ExposureEvent`s, `α`, `β` and every `MasteryLabel` are bit-identical to the same learner with no exposure events. *(v0.4.2)*
7. **One connection per event.** With a deliberately small pool (2 connections) and 20 concurrent events, chain continuity still holds and no advisory lock is ever taken outside the transaction that claimed the event — the failure a top-level `prisma.$executeRaw` would cause. *(v0.4.3)*

> **Change 6 — `occurred_at` → `recorded_at`.** *Superseded in v0.4.2: architecture v0.5 replaced strategy B with exact re-folding, so the premise below no longer holds and criterion 4 is back to `occurred_at` order.* Asserting equality with sequential application in `occurred_at` order contradicts §6.5, which chose **strategy B** for late arrivals: append with reduced weight, state monotone in `recorded_at`, deliberately *not* reordered. As written, the criterion asserts a property the design explicitly declined to provide, so it fails on any test fixture that includes a late event — and the likely "fix" is to change the design rather than the test. If you want the fixture to exercise `occurred_at` ordering too, generate the 20 events with `occurred_at` monotone in arrival order and say so.

---

### P4 — Diagnosis APIs and row-level security (4 days)

**Goal:** replace the mock with real queries, behind real authorization.

**Deliverables**

1. `getState`, `getGaps`, `getMostUncertain`, `getReadiness` (with `minEdgeStrength`), `getMisconceptions` against real state, decay applied on read; `exposure` populated on every `ConceptStateView`. *(v0.4.3)*
2. `PostgresDomainGraph` behind `IDomainGraph` — recursive CTE over a co-located `concept_edge` table.
3. **Row-level security** on every learner-scoped table — `learner_concept_state`, `state_transition`, `learner_misconception_state`, `processed_event`, `exposure_event`, `learner_concept_exposure` — `ENABLE` + `FORCE`, keyed to a **transaction-local** variable; runtime roles `ls_api` / `ls_ingest`, neither owner nor `BYPASSRLS` (architecture v0.5 §9.3.1). *(Moved from P8; scope widened in v0.4.2.)*
4. `retrievability` on `ConceptStateView` (P0 contract addition).
5. **Two Prisma clients**, `ls_api` (reads) and `ls_ingest` (write path), each connecting as its own non-owner role; every read sets `app.learner_id` with `set_config(…, true)` as the first statement of its interactive transaction. *(v0.4.3)*

> **Change 7 — RLS moves from P8 to P4.** It is not hardening; it is a correctness property on T2, the highest-impact threat after evidence poisoning, and **P4 is the phase where real learner data first leaves the service**. Shipping three phases of endpoints and then adding row-level security means every query written in between was written without it, and retrofitting RLS onto queries that assume they can see everything is where the missed `WHERE` clause survives.
>
> Architecture §9.3 also specifies RLS as *defence in depth* behind the application guard. Depth you add later is not depth; it is a patch on a system that already shipped without it.

#### Exit criteria

1. The Diagnosis Engine runs end-to-end against real state, no mock in the path.
2. **RLS blocks cross-learner reads with the application guard deliberately disabled** — on all six learner-scoped tables, `getHistory` included. This is the test that proves it is defence in depth rather than decoration, and it must be run against a real Postgres — a mocked database makes it meaningless.
3. Unobserved tuples are returned as priors, never omitted.
4. `getReadiness` uses the credible bound `P(θ > θ*) ≥ 0.80`, not the mean, and ignores prerequisites whose edge strength is below `minEdgeStrength`. *(v0.4.3: second clause)* *(The Adaptive Engine's prerequisite gate is built directly on this; gating on the mean lets a learner past on three lucky answers.)*
5. **The service cannot bypass RLS.** Connected as `ls_api`, a query for another learner's rows returns zero rows on all six tables. A CI check asserts that no runtime role owns a learner-scoped table or holds `BYPASSRLS`. *(v0.4.2)*
6. **No leakage across a pooled connection.** Two consecutive requests by different learners on the **same** connection: the second sees none of the first's rows, and a request that never sets the variable sees no rows at all. *(v0.4.2)*

---

### P4.5 — Ontology replication seam (2 days)

**Goal:** remove the synchronous cross-service call from the ingest path before it exists.

**Deliverables:** local `concept_edge` read-model table, `OntologyChanged` consumer interface, monotonic version-gap detection triggering full resync, nightly reconciliation comparing version and checksum.

**Exit criteria:** a simulated `OntologyChanged` event updates the replica; an injected version gap triggers a resync; reconciliation detects a silent divergence introduced by hand. **Never rely on the event stream alone for convergence** — the reconciliation job is the deliverable, not the nice-to-have.

*Droppable under schedule pressure.* In the prototype the ontology is co-located, so `PostgresDomainGraph` **is** the degenerate case of this design with zero lag. What is lost is the demonstration, not the capability.

---

### P5 — Bounded propagation (3 days)

**Deliverables:** cognitive downward propagation (`γ_c = 0.5`), prerequisite propagation (`γ_p = 0.3`), depth cap enforced by database `CHECK`, ε-threshold gate at 0.02.

**Exit criteria:** depth ≤ 2 enforced by the constraint, not by convention; a `PROPAGATED` transition provably never triggers further propagation (assert over a graph containing a deliberate cycle); an update moving the mean by less than ε produces exactly one row.

The cycle test is the one to insist on. Without rule 3 belief circulates and the system becomes confident on the basis of its own inferences — and a graph without a cycle in the fixture will never show it.

---

### P6 — Misconception tracking (3 days)

**Deliverables:** `learner_misconception_state` with `h_m = 180 d`, distractor → misconception mapping via the Task module, clearing gated on discriminating evidence only.

**Exit criteria:** selecting a mapped distractor drives a `MISCONCEPTION` label end-to-end; **answering an unrelated item correctly does not reduce activation.** The second is the real test — without it the system quietly declares misconceptions resolved because the learner stopped encountering them.

*Droppable under schedule pressure*, at the cost of one hypothesis in the Diagnosis Engine.

---

### P7 — History and replay tooling (3 days)

**Goal:** make AP-1 a demonstrated property rather than an architectural aspiration.

**Deliverables:** `getHistory`, `getTrajectory`, replay of the evidence log into a shadow table under a new `model_config_version`, then swap.

**Exit criteria:** replaying a fixed log twice yields **byte-identical `outcome_digest` values**; replaying under a *changed* config yields a digest that differs, and differs only where expected. Both directions matter — a digest that never changes is not evidence of determinism, it is evidence the digest is not sensitive to what it is supposed to detect.

**Not droppable.** P7 is what earns the reproducibility claim, the strategy-comparison capability the Evaluation layer depends on, and the "poisoned evidence can be surgically removed" recovery story in §8.5.

---

### P8 — KMS, crypto-shredding, cache, scale (3 days)

**Deliverables:** KMS integration with rotation windows against the P2 column layout; crypto-shredding (per-learner DEK wrapped by a KMS master key, erasure destroys the DEK); Redis read-through cache of the **undecayed** state; load testing.

**Exit criteria:** an erasure request renders the encrypted columns unrecoverable, hard-deletes the learner's snapshot rows, purges the cache, and leaves the log byte-for-byte immutable with the pseudonymous statistical residue still queryable (architecture v0.5 §9.4); cache hit rate above 80% on a simulated diagnosis cycle with decay still exactly correct on every response; p95 latency targets met under load.

The cache criterion is the subtle one. Caching the *response* is the natural implementation and it is wrong — the response depends on `now()` through decay, so it is stale the moment it is written. Cache the time-invariant `(α, β, last_evidence_at)` and apply `DecayFunction` after the read (§8.3).

---

## Part 3 — What this roadmap does not decide

Five items are unresolved and are recorded here so they are not mistaken for settled.

1. **`interventionId` requires the Adaptive team's agreement, in P0.** It is the one contract change in this document that becomes materially more expensive after the phase it belongs to. If it is going to be refused, it should be refused this week.

2. **Whether the sensitivity study gates anything.** §11.2 says the parameter sweep runs offline and gates nothing. That is the right call for the schedule, but it means the paper reports a stability metric that no phase was required to achieve. Decide whether a τ below some threshold is a finding or a defect — before you see the number, not after.

3. **The 33-day total against the actual calendar** *(v0.4.3)*. At ~2.5 days a week that is ~13–14 weeks of build. Nothing above accounts for integration with the other modules, and P0's whole purpose is to create parallel integrations — on a team of three, "the other teams" are the same three people.

4. **Retention.** §8.2 says "keep everything forever is not a plan" but no phase sets a retention policy, and the transition table is the fastest-growing object in the system. This is also entangled with the study's ethics approval, which has its own lead time.

5. **Platform questions from the team architecture document** *(v0.4.3)*. Which of the six services hosts this module (Learning Data Service is the natural fit); whether evidence arrives over Kafka from day one (then partition by `learner_id`); who owns evidence weighting (listed under both Evidence and Evaluation — architecture §11.3 #3); what the Python Model Inference Service's "ATDOT" is (a neural knowledge-tracing model would conflict with architecture §3.1); and whether S3 holds learner content that erasure (§9.4) must reach. None blocks P0–P1; the first must be settled before P2.

---

## Appendix — Corrections at a glance

| # | Phase | Was | Now | Cost if left |
|---|---|---|---|---|
| 1 | P1 → P2 | Quantise in the core-building phase | Quantise in the repository mapper | Rounds 4× per event; breaks `n`-conservation |
| 2 | P1 | "Decay never raises the mean" | `\|μ − μ₀\|` non-increasing | Property test fails, or is deleted, on the first below-prior learner |
| 3 | P1 | "Precision cap preserves the mean exactly" | Exact in the core; tolerance at the boundary | Flaky test, then a deleted test |
| 4 | P2 | Read returns priors and decayed state | Byte-identical string round-trip | Determinism claim untested in the phase that introduces it |
| 5 | P3 | `[locked_at, released_at]` non-overlap | Chain continuity over `state_transition` | A stopwatch presented as a proof |
| 6 | P3 | Sequential in `occurred_at` order | Sequential in `recorded_at` order | Contradicts §6.5; fails on any late-arriving fixture — **superseded in v0.4.2** (architecture v0.5 §6.5): back to `occurred_at`, within `late_bound` |
| 7 | P8 → P4 | RLS as hardening | RLS with the first real endpoints | Three phases of queries written without it |
| 8 | — | Estimates absent | 32 days, stated — 33 since v0.4.2 | Discovery in week five |
| 9 | P2–P4 | Kysely/Slonik, raw SQL migrations | Prisma with raw SQL on `tx`; Prisma Migrate with hand-written SQL *(v0.4.3)* | RLS or the lock silently bypassed by a pooled top-level call |
