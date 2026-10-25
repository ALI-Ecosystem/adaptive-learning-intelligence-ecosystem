# Adaptive Learning Intelligence Ecosystem

An adaptive AI learning intelligence layer that captures AI-assisted learning interactions, models learner understanding, and generates personalized knowledge graphs, diagnoses, and learning paths.

## Project Overview

This project is developed as a final Software Engineering project at Shenkar.

The system aims to transform fragmented learning interactions from AI tools such as ChatGPT, Claude, Cursor, and IDE-based assistants into structured, persistent, and adaptive learning memory.

Instead of treating each AI conversation as isolated, the system builds a continuous learner model that helps identify conceptual gaps, repeated mistakes, prerequisite weaknesses, and personalized learning needs.

## Core Idea

The system acts as an intelligence layer above existing AI tools.

The main goal is not to replace AI assistants, but to add a personalized learning layer that helps users understand what they learned, what they misunderstood, and what they should practice next.

## Main Goals

- Capture meaningful learning signals from AI-assisted conversations and development workflows
- Organize extracted knowledge into a personal knowledge graph
- Model the learner’s understanding over time
- Diagnose conceptual weaknesses and root causes of misunderstanding
- Generate adaptive learning paths and dynamic practice
- Support long-term learning continuity across different tools and conversations

## Initial Planned System Flow

This flow represents the current high-level direction of the system and may change as the architecture, MVP scope, and implementation details are refined.

```text
AI Conversations / IDE Work / Learning Sources
        ↓
Capture & Context Layer
        ↓
AI Processing + Learner Modeling
        ↓
Personal Knowledge Graph
        ↓
Learning Diagnosis Engine
        ↓
Adaptive Learning Path + Dynamic Practice
```

## Repository components

Each component owns its dependencies and execution commands. The repository root
does not provide a combined Python installation or whole-repository test command.

| Component | Location and instructions |
| --- | --- |
| Diagnosis Engine (Python) | [services/diagnosis](services/diagnosis/README.md) |
| Domain Knowledge Graph (Python) | [services/domain-knowledge-graph](services/domain-knowledge-graph/README.md) |
| Evaluation tooling (Python) | [services/evaluation](services/evaluation/README.md) |
| Learner State (TypeScript/NestJS) | [services/learner-state](services/learner-state/README.md) |

Run installation, build, and test commands from the relevant component directory.
Diagnosis's package remains `ali_diagnosis`; its `pyproject.toml`, `src/`, and
`tests/` now live together in `services/diagnosis/`. Central architecture documents
remain under [docs/architecture/diagnosis](docs/architecture/diagnosis/README.md).
