# Repository Agent Instructions

## Diagnosis Engine

For work under `src/ali_diagnosis/`:

1. Read `docs/architecture/diagnosis/README.md` before implementation.
2. Read the architecture documents relevant to the task.
3. Treat those documents as architectural constraints.
4. Prefer the simplest implementation that satisfies the current requirement; follow YAGNI.
5. Do not introduce new Diagnosis domain concepts, contracts, persistence models, source schemas, or abstractions unless required by the task and compatible with the accepted architecture.
6. Jira/task requirements may refine implementation scope but should not silently override accepted architecture.
7. If existing code or a task conflicts with the architecture, report the conflict before changing the architecture.
8. Keep Diagnosis domain contracts independent from agent-runtime-specific types unless the accepted architecture explicitly changes that boundary.
