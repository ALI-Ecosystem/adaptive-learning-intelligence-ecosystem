# Domain Knowledge Graph — baseline (SCRUM-88)

A local, queryable baseline of the Domain Knowledge Graph, built from an existing source rather than from scratch.

- **Nodes:** OpenAlex Concepts snapshot (2026-09-23) — 64,130 concepts, 19 top fields, levels 0–5, each with a Wikidata id.
- **CHILD_OF (113,619):** parent–child links from the Microsoft Academic Graph 2020-01-23 release (same ids as OpenAlex). Every link carries `similarity`, `primary` (the most similar parent per concept) and `flags` (`PARENT_FANIN_OUTLIER`, `CHILD_TOO_MANY_PARENTS`, `LEVEL_INVERSION`). Nothing is deleted.
- **RELATED_TO (784,511):** MAG related-concept links (`general`, plus typed medical links).

The research report (candidates, comparison, measured noise, limitations) is shared separately as a doc. `research/scrum88-edge-sample-100.csv` is the labelled 100-link sample behind the ~30% wrong-parent estimate.

## Run it

Requires Docker and Python 3.11+.

```bash
./download-raw.sh                     # ~75 MB into raw/
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py             # writes import/
./start-neo4j.sh                      # Neo4j 5.26 on localhost:7474, creates neo4j.env
./load-graph.sh                       # loads the graph, runs demo.cypher
```

`raw/`, `import/` and `neo4j.env` are git-ignored. Neo4j listens on 127.0.0.1 only.

## Demo queries (demo.cypher)

1. Search a concept (full-text index on name + description)
2. Parents of a concept, primary first
3. Children of a concept
4. Related concepts
5. Relationship types
6. Navigate to the root through primary parents

## Sources and licenses

- OpenAlex Concepts (deprecated, frozen): https://help.openalex.org/data/concepts/
- Microsoft Academic Graph 2020-01-23, ODC-BY: https://archive.org/details/mag-2020-01-23

---

## Concept placement prototype (SCRUM-89)

Given a learner conversation, a Claude agent finds the main concept, checks it is not
already in the graph, explores the graph through read-only tools and picks the most
direct parent. The concept is written as a `:ProposedConcept` with a
`PROPOSED_CHILD_OF` edge carrying the confidence and reasoning. It is **not** a
`:Concept` and is not returned by search until the validation gate (SCRUM-90)
promotes it.

```
conversation -> agent (Claude + tools: search_concepts, get_concept, get_children,
                get_path_to_root) -> submit_placement -> code validates -> ProposedConcept
```

### Run it

Requires the SCRUM-88 graph loaded in the `ali-kg` container, `neo4j.env` (Neo4j
password) and `.env` with `ANTHROPIC_API_KEY=...` in this folder. Both are git-ignored.

```bash
./scrum89.sh setup        # deps + vector index on :Concept(embedding) + smoke tests, free
./scrum89.sh demo         # Hebrew conversation about tail recursion, dry run
./scrum89.sh add          # same, writes the proposal
./scrum89.sh eval-quick   # 8 hidden concepts, all three methods
./scrum89.sh eval         # 200 hidden concepts, all three methods
```

### Validation: hide and replace

`placement/evaluate.py` samples 50 concepts per level (2-5, seed 89) whose correct
parent is a plain fact of the source: exactly one parent, unflagged link, no children,
not a disambiguation page (18,419 eligible). Multi-parent concepts are excluded because
their "primary" parent was chosen by the same embeddings the search tool uses. The input is a short synthetic learner message built from the
concept name and its definition. Each test concept is hidden from every query (node, embedding, edges) and placed again by:

| method | what it is |
|---|---|
| `baseline` | no LLM: 20 nearest neighbours vote for themselves and their parents |
| `agent` | Claude navigating the graph with the tools above |
| `llm_only` | Claude with no graph access, from memory: measures leakage |

Outputs go to `runs/eval-*/`: `results.jsonl`, `summary.json`, a `review.csv` of
misses for a person to judge, and one trace per agent run (every tool call and result).

### Files

- `placement/graph.py` - read-only graph views with hiding, and the one write (`write_proposal`)
- `placement/build_index.py` - embeddings on every concept + Neo4j vector index
- `placement/agent.py` - system prompt, tool schemas, tool-use loop, decision checks
- `placement/place.py` - CLI for one conversation
- `placement/baseline.py`, `placement/llm_only.py` - comparison methods
- `placement/evaluate.py` - hide-and-replace evaluation
- `tests/` - smoke tests with a scripted fake Claude client (no API key needed)

### Security notes

- The conversation is untrusted text. The agent only has read tools; the single write
  happens in code after checking the parent exists, with length limits on every field.
- Conversations are kept only in local traces under `runs/` (git-ignored); the graph
  stores the decision and reasoning, not the conversation.
- Neo4j listens on 127.0.0.1 only; secrets live in git-ignored env files.

## SCRUM-90: validation gate for additions

A proposed concept (and each proposed prerequisite link) becomes part of the trusted graph
only through `validation/`. Nothing existing is changed or deleted (append-only).

```
proposal -> 1 structural -> 2 semantic -> 3 Wikidata -> 4 blind validator -> 5 decision
                                                         ACCEPT_PROVISIONAL | NEEDS_REVIEW | REJECT
```

- Layers run cheapest first and stop as soon as one decides (`validation/gate.py`).
- Decision rules: `validation/decision.py` (concept), `validation/prereq.py` (each link).
- Writes: `validation/store.py` - new `Concept {trust:'provisional'}` + `CHILD_OF` + accepted
  `PREREQUISITE_OF`; every run stored as a `ValidationRun` node; rejected proposals stay
  with status `rejected`. Trust: provisional -> trusted (teacher/audit) or flagged.
- Teacher queue and audit: `validation/teacher.py`.
- Public ids: every concept has `concept_id` (UUID, `placement/ids.py`), the id Learner
  State stores; `id` stays the internal source key.

Entry point: `./scrum90.sh` (run without arguments for the command list). Unit tests:
`./scrum90.sh test` (no Neo4j, no API key). Calibration and evaluation scripts write to
`runs/scrum90-*` (git-ignored); Wikidata and Wikipedia answers are cached in
`runs/wikidata-cache.json` and `runs/wikipedia-cache.json`.

Results (2026-10-16): on the 170 real SCRUM-89 agent placements, wrong placements in the
graph fell from 4.1% to 1.3% with 10% of proposals sent to the teacher; on LectureBank
prerequisite links 2.6% of wrong links were accepted, 7.9% went to the teacher.

## SCRUM-91: scoped Course Material Graph

`CREATE MATERIAL GRAPH`: given one course or set of learning material, build a small graph of
just that material, made of the global graph's own concepts and edges. This component does not
decide whether ALI should build one; it performs the request.

```
material -> 1 ingest (units) -> 2 extract (concepts + role + evidence) -> 3 link (canonical concept)
         -> 4 missing concepts: SCRUM-89 agent -> SCRUM-90 gate -> 5 scope -> 6 store (overlay)
```

- **Roles.** Every concept is `taught` in a unit or only used there as a `prerequisite`. A concept
  that is needed but never taught in the material is the course's prior knowledge.
- **Linking.** Hybrid search gives candidates (with their path to the root); Claude picks the one
  with the same meaning in the course, or none. Ids not offered are never accepted.
- **Missing concepts** are not invented locally: they go through the SCRUM-89 placement agent and
  the SCRUM-90 gate. Accepted -> linked; teacher review -> kept as a pending link; rejected as a
  duplicate -> linked to the existing concept.
- **Scope.** From each taught concept, climb the existing `CHILD_OF` edges. At each step the parent
  must fit the course (checked by Claude in one batched call per level); candidates are the
  node's existing parents only (already in scope first, then primary). If none fits, the climb
  stops: no edge is invented and the global graph is not changed. Prerequisite concepts are
  attached under an in-scope parent but never climbed. Context concepts above the first
  branching point are trimmed. Other existing edges between kept concepts (`CHILD_OF`,
  `PREREQUISITE_OF`, `RELATED_TO` between material concepts) are reused as they are.
- **Storage** (`material/store.py`): `:MaterialGraph`, `:MaterialUnit` and relationships
  `HAS_UNIT`, `COVERS` (unit -> concept, role, evidence), `INCLUDES` (graph -> concept, role,
  `scoped_parent` = one of the concept's existing parents) and `INCLUDES_PENDING` (-> a proposal
  waiting for the teacher). Nothing is copied; nothing global is written. Same material + same
  settings -> the existing graph is returned; `--new-version` supersedes it.
- **Public ids.** `export` returns concept UUIDs (`concept_id`), the ids Learner State stores.

### Run it

```bash
./scrum91.sh setup      # deps, the two sample courses into materials/ (git-ignored), tests
./scrum91.sh offline    # both courses with no LLM (lexical baseline), free
./scrum91.sh enlp       # English NLP course, Georgetown COSC-572 (LectureBank), with Claude
./scrum91.sh hebrew     # Hebrew data-structures course (Hebrew Wikibooks, TAU 0512-2510)
./scrum91.sh eval runs/scrum91-<run> --judge     # gold-file recall + blind Opus judges
./scrum91.sh list | show ID | export ID | q ID order | q ID unit N | q ID concept NAME | q ID prior
```

Gold files (`material/samples/gold-*.tsv`) give 1-3 accepted canonical concepts (or a concept the
graph lacks, `new:Name`) for the main topic of each unit. They were written from the unit titles
and contents before any run. Claude answers are cached in `runs/scrum91-llm-cache.json`, so a
re-run of the same material costs nothing.

## SCRUM-92: incremental Learner Graph updates

`UPDATE LEARNER GRAPH (existing learner graph, explicit requested change)`. Other ALI components send signed requests; this component stores and shows them. It never decides what the learner knows: the payload is opaque, and there is no mastery, diagnosis or LLM on the write path.

- **Source of truth:** an append-only log in Postgres (`learner_graph/schema.sql`). **View:** a Neo4j projection over the Domain Knowledge Graph — `(:Learner)-[:HAS_CONCEPT]->(:LearnerConcept)-[:INSTANCE_OF]->(:Concept)` and `-[:HAS_RECORD]->(:LearnerRecord:Evidence|:Exposure)`. The view is rebuilt from the log on demand (`rebuild`) and checked against it (`verify`).
- **Write path** (`learner_graph/service.py`): shape → registered sender → Ed25519 signature → operation allowed → one transaction per learner (advisory lock): idempotency key, operation rules, log rows + outbox row. The projector (`learner_graph/projector.py`) re-syncs only the (learner, concept) part an outbox row names.
- **Operations:** `ADD_EVIDENCE`, `ADD_EXPOSURE`, `RETRACT`, `SUPERSEDE`. Corrections never delete: they add a row, and the old record stays with `valid = false`. Only the original sender, or a sender with `can_correct_others` (e.g. the teacher console), may correct a record.
- **Duplicates:** `(sender, request_id)` — same content → `DUPLICATE`, other content → `CONFLICT`; `(sender, source_record_id)` — same record in a new request → `NO_OP`, other content → `CONFLICT`.
- **Concepts:** identity is the DKG `concept_id` (UUID). A concept the DKG does not have is named instead; the record waits (`PENDING_CONCEPT`) on a ticket that `resolve` sends through SCRUM-89 placement + SCRUM-90 gate, then appears under the accepted (or duplicate-of) concept. A rejected concept's records stay in the log and are never shown.

```bash
./scrum92.sh setup      # deps, Postgres on 127.0.0.1:5433 (creates postgres.env), schema, tests
./scrum92.sh demo       # the Jira example on the real graph (needs Neo4j); rerun = all DUPLICATE
./scrum92.sh project && ./scrum92.sh show
./scrum92.sh log <learner> | ./scrum92.sh audit | ./scrum92.sh verify | ./scrum92.sh rebuild
./scrum92.sh resolve    # concepts missing from the DKG -> SCRUM-89/90 (Claude)
```
