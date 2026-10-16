"""The SCRUM-90 test set: known-correct, deliberately wrong and duplicate proposals whose
label comes from the graph structure, not from a model's opinion.

Base: the SCRUM-89 test concepts whose source parent was ALSO judged "correct" by the
blind judge (two independent sources agree). Each base concept is hidden, as in SCRUM-89,
and proposed again under five parents:

    correct       the source parent                                   expected: accept
    too_broad     the parent's own parent (grandparent)               expected: not accept
    too_specific  a sibling: another child of the parent, the one     expected: not accept
                  most similar to the concept (the hardest one)
    wrong_near    an uncle: another child of the grandparent, the     expected: not accept
                  most similar to the concept (plausible but wrong;
                  may sometimes be a fair second parent - reported apart)
    wrong_far     a concept of the same level in another top-level    expected: reject
                  field, the most similar one there (a wrong-domain error)

Plus duplicates, which must never be accepted:
    dup_exact     the base concept proposed again while it is NOT hidden, name in other case
    dup_synonym   the SCRUM-89 "already exists" answers the judge rated "same": the concept is
                  hidden and proposed under its source parent, but a synonym exists in the graph

Usage: python -m validation.testset   ->  runs/scrum90-testset/cases.jsonl  (free)
"""
import json
import random

import numpy as np

from placement import config
from placement.embedder import concept_text
from placement.graph import Graph, connect

from .calibrate_semantic import DEFAULT_RUN
from .neo4j_view import Neo4jSemanticView

OUT = config.RUNS_DIR / "scrum90-testset"
SEED = 90


def _most_similar(vec, ids, view):
    embs = view.embeddings(ids)
    best = max(embs, key=lambda i: float(vec @ embs[i]), default=None)
    return best


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    items = {json.loads(l)["id"]: json.loads(l) for l in open(DEFAULT_RUN / "results.jsonl")}
    judged = {j["key"]: j for j in map(json.loads, open(DEFAULT_RUN / "judge.jsonl"))}
    graph = Graph(connect())
    rng = random.Random(SEED)
    cases = []

    def add(kind, item, parent, expected, hidden=True, name=None, note=""):
        cases.append({"case": f"{kind}:{item['id']}", "kind": kind, "expected": expected,
                      "hide": [item["id"]] if hidden else [], "item": item["id"],
                      "name": name or item["name"], "description": item["description"] or "",
                      "parent_id": parent, "note": note})

    fields_cache = {}

    def field(g, cid):
        if cid not in fields_cache:
            p = g.path_to_root(cid)
            fields_cache[cid] = p[-1]["id"] if p else None
        return fields_cache[cid]

    base = [items[k.split(":", 1)[1]] for k, j in judged.items()
            if k.startswith("parent:") and j["verdicts"].get(items[k.split(":", 1)[1]]["parent_id"]) == "correct"]
    for item in base:
        g = graph.with_hidden({item["id"]})
        view = Neo4jSemanticView(g)
        vec = view.embed_text(concept_text(item["name"], item["description"]))
        parent = item["parent_id"]
        add("correct", item, parent, "accept")

        up = g.path_to_root(parent)
        grand = up[1]["id"] if len(up) > 1 else None
        if grand:
            add("too_broad", item, grand, "not_accept")
        sibs = [k["id"] for k in g.children(parent, 300)]
        sib = _most_similar(vec, sibs, view)
        if sib:
            add("too_specific", item, sib, "not_accept")
        if grand:
            uncles = [k["id"] for k in g.children(grand, 300) if k["id"] != parent]
            uncle = _most_similar(vec, uncles, view)
            if uncle:
                add("wrong_near", item, uncle, "not_accept")
        my_field, level = field(g, parent), g.concept(parent)["level"]
        hits = [h for h in view.neighbours(vec, 200) if h["id"] != parent]
        far = next((h["id"] for h in hits
                    if g.concept(h["id"])["level"] == level and field(g, h["id"]) not in (my_field, None)),
                   None)
        if far:
            add("wrong_far", item, far, "reject")
        if rng.random() < 0.5:     # half of them, enough for the check
            add("dup_exact", item, parent, "reject", hidden=False, name=item["name"].upper(),
                note="the concept itself is visible")
        print(f"\r{len(cases)} cases", end="", flush=True)

    for k, j in judged.items():
        if k.startswith("dup:") and j["verdict"] == "same":
            item = items[k.split(":", 1)[1]]
            add("dup_synonym", item, item["parent_id"], "reject",
                note=f"synonym in graph: {item['agent']['said_exists']}")
    print()
    with open(OUT / "cases.jsonl", "w") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    from collections import Counter
    print(json.dumps(dict(Counter(c["kind"] for c in cases)), indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
