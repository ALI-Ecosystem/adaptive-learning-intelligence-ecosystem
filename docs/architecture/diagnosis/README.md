# Diagnosis Architecture

This folder is the repository-local architecture source for implementation work on the ALI Diagnosis Engine.

## Documents

- `diagnosis-engine.md` — accepted high-level Diagnosis Engine architecture.
- `diagnosis-contracts-v0.md` — accepted SCRUM-6 Diagnosis contract design decisions.

## Source

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
