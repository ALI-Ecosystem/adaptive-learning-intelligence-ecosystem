# Learner State module — instructions for Claude Code

This directory is the **Learner State (LS)** module of the ALI final project (blocks 4–5). It lives inside the team monorepo; other directories belong to other people. **Only edit files under this directory** unless Kody explicitly asks otherwise.

**Read the repo-root `AGENTS.md` first** — it is the team's instructions for AI agents and applies here too. Where it conflicts with this file, stop and ask Kody.

**The repo root is a Python project** (`pyproject.toml`, `src/ali_diagnosis` = Eden's Diagnosis Engine). LS is TypeScript/NestJS and must be **self-contained in this directory**: its own `package.json`, `tsconfig.json`, lockfile, lint config and `node_modules`. Never edit `pyproject.toml`, `src/`, `tests/` or other root files; if something root-level is needed (e.g. a `.gitignore` line for `node_modules`), propose it to Kody instead of doing it.

## Who you are working with
- **Kody** owns this module and builds it alone, ~2–3 days a week. Prototype due end of academic year.
- He has **no ML background**. The model is Bayesian counting (Beta counters), not neural nets. Explain with small numeric examples, not jargon.
- **Guided style:** before writing a non-trivial piece, say in 2–3 lines what you will build and why, ask one guiding question when there is a real design choice, then build. Don't dump 500 lines unannounced.
- **Language:** reply in English only. Code, comments, identifiers, docs and commit messages are English.

## Git rules (strict)
- The team uses **Git Flow**: `develop` is the integration branch; work happens on **one branch per Jira issue**, cut from `develop`, named `feature/SCRUM-<n>-<short-slug>` (e.g. `feature/SCRUM-31-ls-scaffold`). Kody creates branches himself. Never switch branches, merge, rebase, push, or touch `main` / `develop`. If the current branch name does not match the issue being worked on, say so.
- **Never run `git commit` or `git push`.** When a piece of work is done, give Kody the commit message and the commands; he runs them himself.
- Commit message format: first line `SCRUM-<n>: <imperative summary>` (the Jira key links the commit to the issue). Body: what and why, wrapped at 72.
- Kody's terminal is **zsh on macOS**. A pasted command block containing `#` comments or an unbalanced `'` breaks (`quote>` prompt). Hand over multi-line messages like this, with no `#` lines:

  ```
  cat > /tmp/msg.txt <<'MSGEOF'
  SCRUM-31: Scaffold NestJS service with strict TypeScript

  Body text here.
  MSGEOF
  git add -A services/learner-state
  git commit -F /tmp/msg.txt
  ```

## Source of truth (read before designing anything)
| File | Role |
|---|---|
| `docs/learner-state-architecture.md` (v0.5) | **The design.** Wins every disagreement. |
| `docs/learner-state-implementation-roadmap.md` (v0.4.3) | Phases P0–P8, deliverables, **exit criteria**. Sequences the design, adds nothing. |
| `docs/learner-state-working-guide.md` | Decision log, invariants, open items. |
| `docs/verify_mastery_model.py` | Numerical oracle (Python). The TS core must match it to 1e-9. |

If code you are asked to write contradicts the architecture, **stop and say so** — don't silently pick one.

## Stack (architecture App. C)
- TypeScript `strict`, NestJS. PostgreSQL 14+. **Prisma** (team standard) — with the rules below.
- fast-check for property tests, Testcontainers (real Postgres) for integration, Python + NumPy/SciPy oracle.
- **Deployment target: AWS** (team decision). Postgres = Amazon RDS/Aurora PostgreSQL; keys = AWS KMS (P8); DB credentials from AWS Secrets Manager (three URLs: owner, api, ingest). The RDS master user has `rds_superuser` — the service must never connect with it. Compute (ECS/Fargate vs Lambda vs EC2) is **undecided** (SCRUM-87); don't write code that assumes Lambda or a long-lived process until it is. Local development and tests need no AWS: Testcontainers Postgres.
- **Not in the prototype:** Redis before P8, Kafka owned by this module, a second database, any ORM-generated SQL on the write path. Redis must never become a lock manager.

## Prisma rules (App. C.2) — each one prevents a silent bug
1. One **interactive** transaction per event/request: `prisma.$transaction(async (tx) => { ... })`. Never the array form; never a bare `prisma.$executeRaw` outside it (Prisma may use a different pooled connection per top-level call).
2. First statements inside it: reads → `SELECT set_config('app.learner_id', $1, true)`; writes → idempotency `INSERT ... ON CONFLICT DO NOTHING RETURNING`, then `pg_advisory_xact_lock(hashtextextended($1, 0))`. Always `tx.$queryRaw` / `tx.$executeRaw` **tagged templates**. Never `$executeRawUnsafe` or string concatenation.
3. Two clients, two roles: reads as `ls_api`, ingest as `ls_ingest`. Neither owns tables. Migrations run as `ls_owner`.
4. Set the interactive-transaction `timeout` explicitly (default 5 s is too short for a late-evidence re-fold).
5. Migrations: `prisma migrate dev --create-only`, then hand-write the SQL. Partitioned tables, RLS policies, CHECKs and enums are SQL only; partitioned tables are read-only or unmapped in `schema.prisma`.

## Invariants — never break without a recorded decision
- State is a projection of an **append-only** log; transitions are never updated or deleted.
- Idempotency claim and state mutation commit in **one** transaction; the advisory lock is transaction-scoped in that same transaction.
- Decay exists in exactly one place: `DecayFunction` in the TS core. No SQL decay view. Decay reverts toward the **prior**, not zero.
- The core computes in full `float64`; rounding to 6 dp happens **once**, in the repository mapper. Prisma returns `NUMERIC` as `Prisma.Decimal` — convert with `.toFixed(6)` there and nowhere else. Never `parseFloat`/`Number()` on a DB numeric.
- Decay before update. Label order: `MISCONCEPTION` → `DECAYED` → `UNKNOWN` → `MASTERED` → `DEVELOPING` → `NOT_MASTERED`.
- Propagation depth ≤ 2 (DB `CHECK`); derived evidence never re-propagates.
- Exposure never moves `alpha`/`beta`; only assessed evidence does.
- Every read returns uncertainty alongside the value. No method decides what the learner should do next (that is the Adaptive Engine's job).
- Only `IDomainGraph` talks to the ontology; learner input never creates, deletes or re-links concepts/edges.
- Signatures: Ed25519 over the canonical bytes, **no pre-hash**; reject before touching any state.

## Code layout
- `src/core/` — pure functions, no I/O, `now` passed as an argument. Must not import from `src/infra/`.
- `src/infra/` — Prisma, HTTP, crypto, NestJS wiring.
- `contract/` — canonical field lists and cross-language test vectors (P0).
- `prisma/` — schema and hand-written migrations.

## Jira (project SCRUM, label `learner-state`)
Every task has a key. Put it in the commit's first line. "Done" means the issue's **Done when** list is demonstrated, not asserted.

| Epic | Phase | Issues |
|---|---|---|
| SCRUM-19 | Setup | 31 scaffold · 32 CI · 33 Postgres harness + roles · 34 Prisma helpers + lint |
| SCRUM-20 | P0 contract | 35 evidence field list · 36 exposure field list · 37 test vectors · 38 OpenAPI · 39 mock · 40 P0 exit |
| SCRUM-21 | P1 core | 41 DecayFunction · 42 MasteryUpdater · 43 PriorResolver/LabelClassifier · 44 properties I1–I9 · 45 Kendall tau |
| SCRUM-22 | P2 schema | 46 migrations · 47 quantisation mapper · 48 encrypted columns · 49 exposure tables · 50 read path |
| SCRUM-23 | P3 write path | 51 signature · 52 pipeline · 53 idempotency proof · 54 concurrency · 55 late evidence · 56 exposure ingest |
| SCRUM-24 | P4 APIs + RLS | 57 domain graph · 58 endpoints · 59 readiness · 60 RLS · 61 RLS tests · 62 Diagnosis e2e |
| SCRUM-25..29 | P4.5–P8 | 63–76 |
| SCRUM-30 | Team decisions | 77–87 (not code; some block the items above) |

Blocked items: SCRUM-35 waits on 77 (ALE-CR-004 fields); 36 on 78; 46 on 79 and 83 (which service hosts LS); 52 on 80, 81, 84; 60 and 61 on 87 (AWS compute: Lambda would need RDS Proxy checked against transaction-local RLS). P1 (41–45) is blocked by nothing — good work while decisions are pending.

## Tests
- Run the Python oracle and the TS tests before saying anything is done.
- Property tests use uniform generators (the decay-below-prior bug is only reachable that way).
- Anything touching locks, `ON CONFLICT` or RLS is tested against **real Postgres** (Testcontainers), never a mock.
