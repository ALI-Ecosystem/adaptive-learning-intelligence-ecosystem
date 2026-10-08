# Learner State (LS)

Bayesian mastery projection over an append-only evidence log. Blocks 4–5 of
the ALI final project; TypeScript/NestJS, PostgreSQL (arriving in P2),
self-contained inside `services/learner-state/`.

Design and roadmap live in [`docs/`](./docs). Start with
`learner-state-working-guide.md` for navigation and the decision log.

## Status

SCRUM-31 scaffold — the NestJS service boots and answers `GET /health`.
SCRUM-33 adds the Postgres harness: Prisma, the three database roles and a
Testcontainers integration test. No tables or business logic yet. Phases P0–P8 land in later SCRUM
issues (see Jira project SCRUM, label `learner-state`).

## Prerequisites

- Node.js **22.22+** (the `engines` field in `package.json` enforces the
  supported range). Testcontainers 12 requires it; Node 20 is end-of-life.
- npm 10+.
- **Docker** running, for the integration tests (Testcontainers starts a
  throwaway Postgres 16). No local Postgres install is needed.

## Install

```bash
npm install
```

## Run

```bash
npm run start:dev          # watch mode, src/infra/main.ts
# or
npm run build && npm start # compiled, from dist/
```

Default port is `3000`; override with `PORT=…`.

### Health check

```bash
curl -s http://localhost:3000/health
# {"status":"ok"}
```

## Scripts

| Script | What it does |
|---|---|
| `npm run build` | `nest build` → `dist/` |
| `npm start` | run the compiled `dist/infra/main.js` |
| `npm run start:dev` | Nest watch mode |
| `npm run typecheck` | `tsc --noEmit` under paranoid-strict TypeScript |
| `npm run lint` | ESLint guard rails: `src/core/` must not import from `src/infra/`; Prisma rules of App. C.2 (no `*Unsafe`, no array-form or timeout-less `$transaction`, raw SQL only on `tx`, no generated query API outside `src/infra/admin/`) |
| `npm run lint:fix` | same, with autofix where applicable |
| `npm test` | unit tests (no Docker), incl. proof that each guard-rail lint rule fires |
| `npm run test:integration` | Testcontainers Postgres: creates the roles, runs `prisma migrate deploy` as `ls_owner`, checks both runtime clients and `NUMERIC` → `Prisma.Decimal` |
| `npm run prisma:generate` | regenerate the Prisma client (also runs on `npm install`) |

## Database roles

Architecture §9.3.1 / App. C.2. The service never connects as the table
owner, so row-level security always applies.

| Role | Used by | Env var |
|---|---|---|
| `ls_owner` | `prisma migrate deploy` only | `LS_OWNER_DATABASE_URL` |
| `ls_api` | read client | `LS_API_DATABASE_URL` |
| `ls_ingest` | ingest client | `LS_INGEST_DATABASE_URL` |

The roles are created once per database by an administrator with
`prisma/bootstrap/roles.

## Transactions

Every RLS-scoped read and every evidence write goes through
`src/infra/prisma/transactions.ts`:

- `withLearnerRead(ctx, learnerId, fn)`: first statement
  `set_config('app.learner_id', …, true)`; 5 s timeout.
- `withEventWrite(ctx, { evidenceEventId, learnerId }, fn)`: claims the
  event in `processed_event` (`outcome_digest = 'PENDING'`, decision #24),
  then `pg_advisory_xact_lock`; returns `DUPLICATE` without running `fn`
  for an already-processed event; 30 s timeout. `fn` must set the real
  `outcome_digest`.

Timed-out transactions are counted through `TransactionMetrics`.sql` (passwords passed as psql variables). That is
not a Prisma migration: migrations run as `ls_owner`, which cannot create
roles.

## Layout

```
src/
├── core/   pure functions, no I/O, `now` passed as an argument.
│          Must not import from src/infra/ (enforced by ESLint).
└── infra/  Prisma, HTTP, crypto, NestJS wiring.
prisma/     schema.prisma, hand-written SQL migrations, bootstrap/roles.sql.
test/integration/  Testcontainers tests against real Postgres.
```

Rationale, invariants and the full design are in
`docs/learner-state-architecture.md` (the spec; v0.5). The roadmap with
phase exit criteria is in `docs/learner-state-implementation-roadmap.md`.

## For AI assistants

Read `CLAUDE.md` and `docs/learner-state-working-guide.md` before changing
anything in this directory. The repo-root `AGENTS.md` also applies.
