# Learner State — Working Guide

**Read this first, every session.** It tells you where everything is, which rules govern edits, what has been decided, and what comes next. It does **not** restate the design: the design lives in one place only.

| | |
|---|---|
| **Owner** | Kody (architecture and implementation, solo) |
| **Team** | 3 people on the whole ALI final project |
| **Deadline** | working prototype by end of academic year (2026–27) |
| **Capacity** | ~2–3 focused days per week |
| **Last updated** | 2026-10-07 — v0.5 incl. exposure layer (#21–#22) and Prisma (#23); team architecture doc reviewed; implementation not started |

---

## 1. Source-of-truth hierarchy

| Rank | File | Role |
|---|---|---|
| 1 | `learner-state-architecture.md` **v0.5** | **The design.** Where anything disagrees with it, it wins |
| 2 | `learner-state-implementation-roadmap.md` **v0.4.3** | Sequences the design into phases P0–P8 with exit criteria. Adds nothing to it |
| 3 | `verify_mastery_model.py` | Numerical oracle. Every number in Appendix B and every §12 invariant is checked here |
| 4 | **this guide** | Navigation, conventions, status. Never the place a design decision is recorded |
| — | `learner-state-team-overview.docx` | Hebrew summary for the team. Derived; regenerate it when the design changes materially |

Project-level progress log (claude.ai project): `claude/learner-state-review-progress.md`.

## 2. Working conventions

**How we work together**
- Kody has no ML background. Explain with numbers and small examples, never with jargon first.
- **Guided format:** short explanation → one guiding question → Kody answers → then confirm/correct → decide *keep* or *change*. Do not skip to the answer.
- Reply in **Hebrew** when he writes Hebrew. Code, specs and commit messages stay English.
- Present trade-offs and alternatives; push back with arithmetic when an answer would break the model (the partial-credit decision is the template: simulate both options, show the table, recommend, let him decide).
- Stay on Learner State. When something affects another module (ALE, Diagnosis…), **log a follow-up** here — do not edit that module's spec.

**How the spec is edited**
1. **Single file.** No companion documents. A decision is applied **in place** in the section it affects.
2. Every change gets a numbered entry in the spec header ("Changes in v0.5", currently #14–#23). Next free number: **#24**.
3. A closed open question is struck through in §11.3 and points to where it was resolved.
4. A request to another module is an **LS-CR-nnn** entry in §11.4. Next free id: **LS-CR-003**.
5. Before editing: copy the file to a backup outside the project folder. Edit with an exact-match script (assert the old text occurs once), never by retyping.
6. After editing anything numerical: run `python3 verify_mastery_model.py` — all checks must pass. Add a check for every new numerical claim.
7. When a change contradicts the roadmap, fix the roadmap in the same session and note it in its header.
8. If he asks to wrap up with git: write the commit message; he runs git himself (multi-line messages as a heredoc file + `git commit -F`).

## 3. Map of the spec (v0.5)

| § | Holds | Look here when… |
|---|---|---|
| 1 | Scope, in/out, the boundary rule, pipeline diagram | deciding whether something belongs in this module |
| 2 | AP-1…AP-5 | any change touching storage, concurrency, decay timing, DB choice |
| 3.1–3.3 | Model choice, state unit `(learner, concept, level) → Beta(α,β)`, prior | |
| **3.4** | **Evidence update, steps 1–6** incl. partial-credit mixture | implementing `MasteryUpdater` |
| 3.5 | Decay + spacing effect | `DecayFunction` |
| 3.6 | Derived quantities, confidence vs credible interval, **label order** | `LabelClassifier` |
| 3.7 / 3.8 | Cognitive-level coupling / misconceptions | P5 / P6 |
| 3.9 | **Parameter table** (all defaults, incl. `late_bound`) | any constant |
| **3.10** | **Exposure layer** — what was taught vs what is known | exposure ingest, `ConceptStateView.exposure` |
| 4 | Functional core vs shell, component list | code structure |
| **5.2** | **Full Postgres schema** | migrations (P2) |
| 5.1 | Conceptual model; **Personal KG = logical overlay**; learner input never changes structure | questions about "a graph per learner" |
| 5.3–5.6 | Decay only in app layer; `IDomainGraph`; ontology replica; NUMERIC quantisation | |
| 6.1–6.3 | Input contract, idempotency + lock in one transaction, processing sequence | write path (P3) |
| 6.1a | `ExposureEvent` input and its short processing path | P0 field list, P3 ingest |
| 6.4 | Bounded propagation, direction table | P5 |
| **6.5** | Bi-temporality; **late-evidence policy (C ≤ 7 d, defer beyond)** | P3 |
| 6.6 | Ontology migration (split/merge), precondition LS-CR-001 | |
| **7.2–7.4** | **Types, service interface, REST surface** | the P0 contract |
| 8 | Workload, sizing, caching, bottlenecks, failure modes | P8 |
| 9.1–9.2 | Threat model; evidence poisoning; Ed25519 signing | P3 |
| **9.3.1** | **RLS: 6 tables, FORCE, non-owner roles, transaction-local variable** | P4 |
| **9.4** | **Erasure column by column**, `learner_key`, stated limitations | P2 (columns), P8 (KMS) |
| 10 | Implementation plan, testing strategy, Definition of Done | |
| 11.3 / 11.4 | Open questions / cross-team contract requests | |
| A / B | Reference TypeScript core / verified test vectors | P1 fixtures |
| 12 | Verification, what it changed | |
| C | Technology decisions with rejected alternatives | |

## 4. Decision log (v0.5 — guided review, 2026-10-06/07)

| # | Decision | Where |
|---|---|---|
| 14 | Concept-id stability is a contract (**LS-CR-001**): ids immutable, never deleted; split/merge/deprecate/re-identify arrive as explicit operations with old→new mapping | §11.4, §6.6 |
| 15 | Late evidence: ≤ 7 d → exact re-fold in `occurred_at` order (one `REORDER` transition per tuple keeps the chain proof); > 7 d → `DEFERRED_LATE`, applied only explicitly. Strategy B removed | §6.5, §5.2, §3.9 |
| 16 | `getReadiness`: `ready` defined via the §3.6 MASTERED test; new `minEdgeStrength` param; `readinessScore` removed | §7.3, §7.4 |
| 17 | RLS on all learner tables (6 since #21), `ENABLE`+`FORCE`, roles `ls_api`/`ls_ingest`, `set_config(…, true)`, fail closed | §9.3.1 |
| 18 | Erasure: `item_id`, `evidence_signature`, `deferred_payload` → DEK-encrypted `BYTEA`; snapshots hard-deleted; cache purged; 3 stated limitations | §9.4, §5.2 |
| 19 | Partial credit = credit-weighted mixture of correct/incorrect responsibilities (v0.4 rule took 20×10% answers to 0.734; now 0.146) | §3.4 step 3, App. A, verify script |
| 20 | Single-tenant prototype; `tenantId` stays in the signed envelope, no column | §11.3 #4 |
| 21 | **Exposure layer** (team proposal): `ExposureEvent`, `exposure_event` + `learner_concept_exposure`, `exposure` on `ConceptStateView`; never moves `α`/`β`; no decay, no propagation; labels unchanged; **LS-CR-002** to Evidence | §3.10, §6.1a, §5.2, §7.2, §11.4 |
| 22 | "Personal Knowledge Graph" = logical overlay of the shared ontology; ontology stored once; learner input never changes structure | §5.1 |
| 23 | **Prisma** (team standard) replaces Kysely/Slonik; write path + RLS-scoped reads = raw SQL on `tx` inside one interactive `$transaction`; Prisma Migrate with hand-written SQL; two clients (`ls_api`, `ls_ingest`) | App. C.2 + rules |
| 24 | `outcome_digest`: the claim inserts `'PENDING'`; the persist step sets the real digest in the same transaction (the digest is only known after the update). DDL unchanged | §6.2 |

Reviewed and **kept unchanged**: the whole of §3 except partial credit, AP-1…AP-5, NUMERIC quantisation, idempotency design, bounded propagation, API rules, caching of undecayed state, evidence-poisoning controls.

## 5. Invariants — never break these without a recorded decision

- State is a projection of an append-only log; transitions are never updated or deleted (erasure = key destruction).
- Idempotency claim and state mutation commit in **one** transaction; the lock is transaction-scoped in the same transaction.
- Decay exists in exactly one place: `DecayFunction` in the TypeScript core. No SQL decay view.
- The core computes in full float64; rounding to 6 dp happens **once**, in the repository mapper.
- Decay is applied before update (§3.4 step 1). Label order: `MISCONCEPTION` → `DECAYED` → `UNKNOWN` → `MASTERED` → `DEVELOPING` → `NOT_MASTERED`.
- Propagation depth ≤ 2 (DB `CHECK`); derived evidence never re-propagates.
- No method that decides what to do (`recommendNext()` = boundary violation).
- No public write of mastery; overrides only via the audited instructor endpoint.
- Every read returns uncertainty alongside the value.
- Write path and RLS-scoped reads never use Prisma's generated query API — raw SQL on `tx` inside one interactive `$transaction` (App. C.2 rules).
- Only `IDomainGraph` talks to the ontology; this module stores concept ids, never concept content.
- Learner input (evidence or exposure) never creates, deletes or re-links ontology nodes/edges.
- Exposure never moves `α`/`β`; only assessed evidence does.

## 6. Open items

**Need other module owners (team of 3 — decide together):**

| Item | Blocks | Status |
|---|---|---|
| §11.3 #2 — Bloom-level tag on every item | P3 (cognitive levels collapse without it) | open |
| §11.3 #3 — who computes evidence weight `w` | P3 | open |
| LS-CR-001 agreement (Domain Knowledge) | P2 | requested, not agreed |
| LS-CR-002 exposure events (Evidence) | P0 field list, P3 ingest | requested, not agreed |
| Which service hosts Learner State (team doc lists 6 services, LS in none; Learning Data Service is the natural fit) | P0 | open |
| Kafka from day one (team doc): partition key **must** be `learner_id` (AP-2) | P3 | open — confirm with team |
| "Weighting" appears in both Evidence and Evaluation (Evidence Weighting Service) — who owns `w`? (= §11.3 #3) | P3 | open |
| What is "ATDOT" in the Python Model Inference Service? If a neural knowledge-tracing model, it conflicts with §3.1 | — | open |
| S3 in the team stack: if learner transcripts land there, erasure (§9.4) must cover them | P8 | open |
| Ownership of Domain Knowledge / Task / Evidence modules | everything upstream; without a signed Evidence stream this module receives nothing | **flagged as project risk**, unresolved |

**Follow-ups in other modules (do not edit them from here):**
- ALE G3 must pass `σ_min` as `minEdgeStrength` to `getReadiness`.
- ALE spec still cites Learner State v0.4 as companion.

## 7. Implementation status

| Phase | Deliverable | Est. days | Status |
|---|---|---|---|
| P0 | Contract: types + OpenAPI (incl. `minEdgeStrength`, `exposure`), evidence + exposure field lists | 3 | not started — **next** |
| P1 | Functional core (TS) + fast-check invariants + Appendix B fixtures | 3 | not started |
| P2 | Migrations (incl. exposure tables), NUMERIC, bi-temporality, encrypted columns, `learner_key` | 3 | not started |
| P3 | Write path: signature, idempotency, lock, late-evidence re-fold, exposure ingest | 6 | not started |
| P4 | Read APIs + RLS (§9.3.1 tests) | 4 | not started |
| P4.5 | Ontology replication seam (droppable) | 2 | not started |
| P5 | Bounded propagation | 3 | not started |
| P6 | Misconceptions | 3 | not started |
| P7 | History + replay tooling | 3 | not started |
| P8 | KMS, crypto-shredding, cache, load | 3 | not started |

≈36 working days ≈ 14–15 weeks at 2.5 days/week. Integration with the other modules and the paper are **not** in this estimate.

**Next session:** start Part 7 — walk the roadmap, then build P0. Pending question to Kody: *why does the roadmap start with the contract (P0) before any logic?* (Answer to draw out: three other modules are blocked on the API shape; a frozen contract lets them build against a mock in parallel.)

## 8. Glossary (Hebrew ↔ spec terms)

| עברית | Spec term |
|---|---|
| שני מונים | Beta posterior `(α, β)` |
| ניחוש / מעידה | guess `g` / slip `s` |
| ציון חלקי | `PARTIAL`, `partialCredit` |
| תקרה | precision cap `n_max` |
| שכחה, זמן מחצית | decay, half-life `h` |
| חזרה מרווחת | spacing effect, `reinforcement_count` |
| תפיסה שגויה | misconception, activation |
| חשיפה / מה למד | exposure, `ExposureEvent` |
| גרף אישי | logical overlay (Personal Knowledge Graph) |
| ודאות | confidence `1 − n₀/n`; credible interval |
| לוג / מטמון | `state_transition` / `learner_concept_state` |
| הרצה מחדש | replay |
| תשובה באיחור | late-arriving evidence |
| הרעלת ראיות | evidence poisoning (T1) |
| מחיקה קריפטוגרפית | crypto-shredding |
