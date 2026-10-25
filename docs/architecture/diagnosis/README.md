# Diagnosis Architecture

This folder is the repository-local architecture source for implementation work on the ALI Diagnosis Engine.

The Python project lives in [`services/diagnosis/`](../../../services/diagnosis/README.md).
Its package name remains `ali_diagnosis`; these central architecture documents
remain in their existing location.

## Documents

- `diagnosis-engine.md` — accepted high-level Diagnosis Engine architecture.
- `diagnosis-contracts-v0.md` — accepted SCRUM-6 Diagnosis contract design decisions.

## Source

Implementation reference: [Agentic Orchestrator (SCRUM-17)](agentic-orchestrator.md)
documents the runtime, configuration, controlled tools, tests, and live acceptance status.
It complements the accepted architecture documents without replacing their decisions.

[SCRUM-17 architecture review](scrum-17-architecture-review.md) records the comparison
with SCRUM-11, the consolidation decision, and the refactoring verification.

These files are snapshots of the accepted Google Drive design documents, synchronized on 2026-10-07.

Canonical Drive sources:
- Diagnosis Engine - Full Detailed Architecture
- SCRUM-6 - Diagnosis Contracts v0 - Design Decisions

## How to use these documents

Before implementing or modifying the Diagnosis Engine, read the relevant documents in this folder.

The high-level architecture defines ownership, boundaries, responsibilities, and major runtime concepts. The contract decision document refines concrete Diagnosis contract decisions.

Implementation details that are not specified by these documents should remain minimal. Prefer YAGNI and avoid speculative schemas or abstractions.

If a task, Jira issue, implementation idea, or existing code appears to conflict with these documents, surface the conflict before changing the architecture.

When an accepted architecture decision changes in Google Drive, synchronize the corresponding repository document before relying on it for later implementation work.
