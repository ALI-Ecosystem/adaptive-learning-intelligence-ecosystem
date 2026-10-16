"""Test layer 4 (blind validator) on the SCRUM-90 test set (validation/testset.py).

Why the test set and not the 541 judged pairs: those labels came from a blind Opus judge,
and the validator is Opus too - agreement there would partly be the model agreeing with
itself. The test-set labels come from the graph structure (grandparent, sibling, uncle,
another field) on concepts where the source and the judge already agree.

Usage: python -m validation.calibrate_blind          (resumable; ~300 short Opus calls)
Writes runs/scrum90-blind/{results.jsonl, summary.json}
"""
import json
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from placement import config
from placement.agent import make_client
from placement.graph import Graph, connect

from . import blind, semantic
from .contract import Proposal
from .neo4j_view import Neo4jSemanticView
from .testset import OUT as TESTSET

OUT = config.RUNS_DIR / "scrum90-blind"


def run_case(graph, client, c):
    g = graph.with_hidden(set(c["hide"]))
    view = Neo4jSemanticView(g)
    p = Proposal(id=c["item"], name=c["name"], description=c["description"],
                 parent_ids=[c["parent_id"]])
    _, _, sig = semantic.run(p, view)
    checks, s = blind.run(p, g, view, client, sig, sig["nearest_list"])
    return {**c, "picked_role": s["picked_role"], "picked_id": s["picked_id"],
            "confidence": s["confidence"], "why": s["why"], "same_as": s["same_as"],
            "options": s["options"], "tokens": s["tokens"]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [json.loads(l) for l in open(TESTSET / "cases.jsonl")]
    done_path = OUT / "results.jsonl"
    kept = []
    if done_path.exists():                     # unreadable answers are run again
        kept = [l for l in open(done_path) if json.loads(l)["picked_role"] != "invalid"]
        done_path.write_text("".join(kept))
    done = {json.loads(l)["case"] for l in kept}
    todo = [c for c in cases if c["case"] not in done]
    print(f"{len(cases)} cases, {len(done)} done, {len(todo)} to run with {blind.MODEL}")
    graph, client, lock = Graph(connect()), make_client(), threading.Lock()
    with ThreadPoolExecutor(4) as ex, open(done_path, "a") as f:
        futs = [ex.submit(run_case, graph, client, c) for c in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result()
            except Exception as e:                 # one failed call must not lose the rest
                print(f"\n  error: {e}")
                continue
            with lock:
                f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush()
            print(f"\r{i}/{len(todo)}", end="", flush=True)
    print()

    rows = [json.loads(l) for l in open(done_path)]
    by = defaultdict(Counter)
    for r in rows:
        by[r["kind"]][r["picked_role"]] += 1
    summary = {"model": blind.MODEL, "cases": len(rows),
               "picked_by_kind": {k: dict(v) for k, v in sorted(by.items())},
               "agree_rate_by_kind": {k: round(v["proposed"] / sum(v.values()), 3)
                                      for k, v in sorted(by.items())},
               "same_as_flagged_by_kind": dict(Counter(r["kind"] for r in rows if r["same_as"])),
               "tokens": sum(r["tokens"] for r in rows)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
