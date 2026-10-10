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
