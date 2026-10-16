# Learner State (LS)

Bayesian mastery projection over an append-only evidence log. Blocks 4–5 of
the ALI final project; TypeScript/NestJS, PostgreSQL (arriving in P2),
self-contained inside `services/learner-state/`.

Design and roadmap live in [`docs/`](./docs). Start with
`learner-state-working-guide.md` for navigation and the decision log.

## Status

SCRUM-31 scaffold — the NestJS service boots and answers `GET /health`.
No persistence, no business logic yet. Phases P0–P8 land in later SCRUM
issues (see Jira project SCRUM, label `learner-state`).

## Prerequisites

- Node.js **20.11+** (the `engines` field in `package.json` enforces the
  supported range; tested on Node 20.x and 22.x).
- npm 10+.
- No Postgres yet. The Testcontainers-backed test harness arrives in
  SCRUM-33.

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
| `npm run lint` | ESLint — enforces the architectural rule required by SCRUM-31: files under `src/core/` must not import from `src/infra/` |
| `npm run lint:fix` | same, with autofix where applicable |

## Layout

```
src/
├── core/   pure functions, no I/O, `now` passed as an argument.
│          Must not import from src/infra/ (enforced by ESLint).
└── infra/  Prisma, HTTP, crypto, NestJS wiring.
```

Rationale, invariants and the full design are in
`docs/learner-state-architecture.md` (the spec; v0.5). The roadmap with
phase exit criteria is in `docs/learner-state-implementation-roadmap.md`.

## For AI assistants

Read `CLAUDE.md` and `docs/learner-state-working-guide.md` before changing
anything in this directory. The repo-root `AGENTS.md` also applies.
