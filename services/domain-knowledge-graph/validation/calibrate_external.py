"""Test layer 3 (Wikidata) on the same 541 judged SCRUM-89 pairs as layer 2.

Every test concept really has a Wikidata id, but the layer is not told it: it searches
by name, as it must for a truly new concept. So the run also measures how often the
name search finds the right item.

Usage: python -m validation.calibrate_external [--run runs/eval-20261013-173918]
Writes runs/scrum90-external/{pairs.csv, summary.json}. Network: Wikidata, cached in
runs/wikidata-cache.json (a second run makes no calls).
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from placement import config
from placement.graph import Graph, connect

from . import wikidata
from .calibrate_semantic import DEFAULT_RUN
from .contract import Proposal
from .neo4j_view import Neo4jExternalView, ensure_indexes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=DEFAULT_RUN)
    a = ap.parse_args()
    out = config.RUNS_DIR / "scrum90-external"
    out.mkdir(parents=True, exist_ok=True)

    items = {json.loads(l)["id"]: json.loads(l) for l in open(a.run / "results.jsonl")}
    judged = [json.loads(l) for l in open(a.run / "judge.jsonl")]
    graph = Graph(connect())
    ensure_indexes(graph)
    client = wikidata.WikidataClient(config.RUNS_DIR / "wikidata-cache.json")
    full = Neo4jExternalView(graph)

    rows, resolution = [], Counter()
    try:
        for n, j in enumerate(x for x in judged if x["key"].startswith("parent:")):
            item = items[j["key"].split(":", 1)[1]]
            true_q = full.wikidata_of(item["id"])
            view = Neo4jExternalView(graph.with_hidden({item["id"]}))
            first = True
            for parent, verdict in j["verdicts"].items():
                p = Proposal(id=item["id"], name=item["name"],
                             description=item["description"] or "", parent_ids=[parent])
                checks, dup, s = wikidata.run(p, view, client)
                if first:
                    resolution["right_item" if s["resolved"] == true_q else
                               "not_found" if not s["resolved"] else "other_item"] += 1
                    first = False
                outcome = ("duplicate" if dup else "support" if s["support"] else
                           "contradict" if s["contradict"] else "no_evidence")
                rows.append({"item": item["id"], "name": item["name"], "parent": parent,
                             "verdict": verdict, "outcome": outcome,
                             "resolved": s["resolved"], "true_qid": true_q,
                             "resolved_right": s["resolved"] == true_q,
                             "support_distance": s["support"],
                             "checks": "|".join(f"{c.check}={c.result.value}" for c in checks)})
            if n % 10 == 0:
                client.save()
                print(f"\r{n + 1} concepts, {len(rows)} pairs", end="", flush=True)
    finally:
        client.save()
    print()

    with open(out / "pairs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    by = defaultdict(Counter)
    for r in rows:
        by[r["verdict"]][r["outcome"]] += 1
    summary = {"pairs": len(rows), "name_search_resolution": dict(resolution),
               "outcome_by_verdict": {v: dict(c) for v, c in sorted(by.items())}}
    for v, c in by.items():
        n = sum(c.values())
        summary.setdefault("rates", {})[v] = {k: round(x / n, 3) for k, x in c.items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
