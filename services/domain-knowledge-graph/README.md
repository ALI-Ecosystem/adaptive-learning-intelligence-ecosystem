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
