"""Calibrate and test layer 2 on placements whose correctness is already judged.

Ground truth: the SCRUM-89 hide-and-replace run. For every hidden concept the blind
Opus judge labelled each candidate parent (the source parent and every method's
answer) as correct / reasonable / wrong - 541 labelled (concept, parent) pairs - and
labelled the agent's 30 "already exists" answers as same / close.

For every pair the concept is hidden again (as in SCRUM-89) and layer 2 runs as if the
pair were a new proposal. Free: no model calls.

Usage: python -m validation.calibrate_semantic [--run runs/eval-20261013-173918]
Writes runs/scrum90-semantic/{pairs.csv, duplicates.csv, summary.json}
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from placement import config
from placement.embedder import concept_text
from placement.graph import Graph, connect

from . import semantic
from .contract import Proposal
from .neo4j_view import Neo4jSemanticView

DEFAULT_RUN = config.RUNS_DIR / "eval-20261013-173918"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=DEFAULT_RUN)
    a = ap.parse_args()
    out = config.RUNS_DIR / "scrum90-semantic"
    out.mkdir(parents=True, exist_ok=True)

    items = {json.loads(l)["id"]: json.loads(l) for l in open(a.run / "results.jsonl")}
    judged = [json.loads(l) for l in open(a.run / "judge.jsonl")]
    graph = Graph(connect())

    pairs = []
    for j in judged:
        if not j["key"].startswith("parent:"):
            continue
        item = items[j["key"].split(":", 1)[1]]
        view = Neo4jSemanticView(graph.with_hidden({item["id"]}))
        for parent, verdict in j["verdicts"].items():
            p = Proposal(id=item["id"], name=item["name"], description=item["description"] or "",
                         parent_ids=[parent])
            checks, reject, s = semantic.run(p, view)
            warns = [c.check for c in checks if c.result.value == "warn"]
            pairs.append({"item": item["id"], "name": item["name"], "parent": parent,
                          "is_source_parent": parent == item["parent_id"], "verdict": verdict,
                          "reject": reject, "warns": "|".join(warns),
                          **{k: v for k, v in s.items()
                             if k not in ("nearest", "nearest_list", "alternatives")}})
        print(f"\r{len(pairs)} pairs", end="", flush=True)
    print()

    dups = []
    for j in judged:
        if not j["key"].startswith("dup:"):
            continue
        item = items[j["key"].split(":", 1)[1]]
        other = item["agent"]["said_exists"]
        view = Neo4jSemanticView(graph.with_hidden({item["id"]}))
        vec = view.embed_text(concept_text(item["name"], item["description"]))
        e = view.embeddings([other]).get(other)
        nearest = view.neighbours(vec, 1)
        dups.append({"item": item["id"], "name": item["name"], "existing": other,
                     "verdict": j["verdict"],
                     "sim": None if e is None else round(float(vec @ e), 4),
                     "nearest_is_it": bool(nearest and nearest[0]["id"] == other)})

    for name, rows in (("pairs.csv", pairs), ("duplicates.csv", dups)):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)

    by = defaultdict(list)
    for r in pairs:
        by[r["verdict"]].append(r)
    summary = {"pairs": len(pairs), "by_verdict": {}}
    for v, rows in sorted(by.items()):
        n = len(rows)
        warn_counts = Counter(w for r in rows for w in r["warns"].split("|") if w)
        summary["by_verdict"][v] = {
            "n": n,
            "rejected": sum(r["reject"] for r in rows),
            "rejected_rate": round(sum(r["reject"] for r in rows) / n, 3),
            "any_warning_rate": round(sum(bool(r["warns"]) for r in rows) / n, 3),
            "warnings": dict(warn_counts),
            "median_parent_sim_pct": float(np.median([r["parent_sim_pct"] for r in rows
                                                      if r["parent_sim_pct"] is not None])),
        }
    # who proposed the parent matters: the baseline's answers come from the same vote
    # that parent_rank checks (circular), and the agent's errors are the realistic case
    def proposers(r):
        it = items[r["item"]]
        out = ["source"] if r["parent"] == it["parent_id"] else []
        return out + [m for m in ("agent", "baseline") if (it.get(m) or {}).get("pred") == r["parent"]]
    summary["by_proposer"] = {}
    for who in ("agent", "baseline", "source"):
        rows = [r for r in pairs if who in proposers(r)]
        summary["by_proposer"][who] = {
            v: {"n": sum(r["verdict"] == v for r in rows),
                "rejected": sum(r["reject"] for r in rows if r["verdict"] == v),
                "parent_rank_warn": sum("parent_rank" in r["warns"] for r in rows if r["verdict"] == v)}
            for v in ("correct", "reasonable", "wrong")}

    sweep = {}
    for t in (0.80, 0.85, 0.90, 0.95):
        sweep[str(t)] = {v: sum(1 for d in dups if d["verdict"] == v and d["sim"] and d["sim"] >= t)
                         for v in ("same", "close")}
    summary["duplicates"] = {"n": len(dups), "by_verdict": dict(Counter(d["verdict"] for d in dups)),
                             "flagged_at_threshold": sweep,
                             "current_threshold": semantic.DUPLICATE_SIM}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
