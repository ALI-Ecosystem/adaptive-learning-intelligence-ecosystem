"""Hide-and-replace evaluation.

Takes concepts whose correct parent is a plain fact of the source (exactly one parent,
unflagged link, no children), hides each one from every tool, asks each method to
place it again and compares with the real parent.

Usage:
  python -m placement.evaluate --methods baseline                 (free, no API key)
  python -m placement.evaluate --methods baseline,agent,llm_only  (full run, ~200 concepts)
  python -m placement.evaluate --n-per-level 5 --methods agent    (quick smoke test)
  python -m placement.evaluate --resume runs/eval-YYYYmmdd-HHMMSS (continue a run)
"""
import argparse
import json
import random
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import config
from .baseline import place_baseline
from .graph import Graph, connect
from .traces import save_trace

METHODS = ("baseline", "agent", "llm_only")


def conversation_for(name: str, description: str | None) -> str:
    """Stand-in for a real learner conversation: the concept name plus its definition."""
    said = f" The slides described it as: {description}." if description else ""
    return (f"Student: In today's lesson we got to {name} and I didn't really get it.{said}\n"
            f"Can you explain what it is and how it connects to what I already know?")


def sample(graph: Graph, levels, n_per_level: int, seed: int):
    by_level = defaultdict(list)
    for c in graph.eligible_test_concepts():
        by_level[c["level"]].append(c)
    rng = random.Random(seed)
    picked = []
    for lv in levels:
        pool = by_level.get(lv, [])
        picked += rng.sample(pool, min(n_per_level, len(pool)))
    return picked, {lv: len(v) for lv, v in sorted(by_level.items())}


def outcome(graph: Graph, pred: str | None, truth: str) -> str:
    if pred is None:
        return "none"
    if pred == truth:
        return "exact"
    if pred in {p["id"] for p in graph.path_to_root(truth)[1:]}:
        return "too_general"       # an ancestor of the right parent
    if pred in {k["id"] for k in graph.children(truth, 500)}:
        return "too_specific"      # a sibling of the hidden concept
    return "wrong"


def evaluate_one(graph: Graph, item: dict, methods, client, model, trace_dir):
    g = graph.with_hidden({item["id"]})
    row = {k: item[k] for k in ("id", "name", "description", "level", "parent_id", "parent_name")}
    path = g.path_to_root(item["parent_id"])
    row["field"] = path[-1]["name"] if path else ""
    if "baseline" in methods:
        b = place_baseline(g, item["name"], item["description"])
        row["baseline"] = {"pred": b and b["parent_id"], "reasoning": b and b["reasoning"]}
    if "llm_only" in methods:
        from .llm_only import place_llm_only
        r = place_llm_only(g, client, item["name"], item["description"], model)
        row["llm_only"] = {"pred": r["parent_id"], "answer": r["answer"],
                           "stop_reason": r["stop_reason"], "blocks": r["blocks"],
                           "tokens": r["input_tokens"] + r["output_tokens"]}
    if "agent" in methods:
        from .agent import run_agent
        res = run_agent(conversation_for(item["name"], item["description"]), g, client, model)
        save_trace(res, {"eval_item": row["id"], "truth": item["parent_id"]}, trace_dir)
        d = res.decision or {}
        row["agent"] = {"pred": d.get("parent_id") if d.get("decision") == "new" else None,
                        "decision": d.get("decision"), "said_exists": d.get("existing_id"),
                        "confidence": d.get("confidence"), "reasoning": d.get("reasoning"),
                        "error": res.error, "steps": res.steps, "trace_id": res.trace_id,
                        "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                        "seconds": round(res.seconds, 1)}
    for m in methods:
        pred = row[m]["pred"]
        row[m]["outcome"] = outcome(g, pred, item["parent_id"])
        row[m]["pred_name"] = (g.concept(pred) or {}).get("name") if pred else None
    return row


def summarize(rows, methods, pool_sizes, args) -> dict:
    s = {"n": len(rows), "eligible_pool_by_level": pool_sizes, "model": args.model,
         "seed": args.seed, "methods": {}}
    for m in methods:
        rs = [r for r in rows if m in r]
        if not rs:
            continue
        oc = Counter(r[m]["outcome"] for r in rs)
        per_level = defaultdict(lambda: [0, 0])
        per_field = defaultdict(lambda: [0, 0])
        for r in rs:
            hit = r[m]["outcome"] == "exact"
            per_level[r["level"]][0] += hit; per_level[r["level"]][1] += 1
            per_field[r["field"]][0] += hit; per_field[r["field"]][1] += 1
        ms = {"accuracy": round(oc["exact"] / len(rs), 3), "n": len(rs), "outcomes": dict(oc),
              "accuracy_by_level": {k: f"{a}/{n}" for k, (a, n) in sorted(per_level.items())},
              "accuracy_by_field": {k: f"{a}/{n}" for k, (a, n) in
                                    sorted(per_field.items(), key=lambda kv: -kv[1][1])}}
        if m == "agent":
            ms["avg_steps"] = round(sum(r[m]["steps"] for r in rs) / len(rs), 1)
            ms["input_tokens"] = sum(r[m]["input_tokens"] for r in rs)
            ms["output_tokens"] = sum(r[m]["output_tokens"] for r in rs)
            ms["avg_seconds"] = round(sum(r[m]["seconds"] for r in rs) / len(rs), 1)
            ms["errors"] = sum(1 for r in rs if r[m]["error"])
            ms["said_already_exists"] = sum(1 for r in rs if r[m]["decision"] == "already_exists")
            hi = [r for r in rs if (r[m]["confidence"] or 0) >= 0.8]
            lo = [r for r in rs if (r[m]["confidence"] or 0) < 0.8]
            ms["accuracy_conf_ge_0.8"] = (f"{sum(r[m]['outcome'] == 'exact' for r in hi)}/{len(hi)}")
            ms["accuracy_conf_lt_0.8"] = (f"{sum(r[m]['outcome'] == 'exact' for r in lo)}/{len(lo)}")
        if m == "llm_only":
            ms["answer_not_a_graph_name"] = sum(1 for r in rs if r[m]["pred"] is None)
            ms["tokens"] = sum(r[m]["tokens"] for r in rs)
        s["methods"][m] = ms
    return s


def write_review_sheet(rows, method: str, path: Path):
    """Misses for a person to judge: the source's 'correct' parent is itself noisy
    (~30% wrong links in SCRUM-88), so some misses are better than the truth."""
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "concept", "description", "true_parent", "predicted_parent",
                    "outcome", "reasoning", "reviewer_verdict (better/equal/worse)"])
        for r in rows:
            m = r.get(method) or {}
            if m.get("outcome") != "exact":
                w.writerow([r["id"], r["name"], r["description"], r["parent_name"],
                            m.get("pred_name"), m.get("outcome"), m.get("reasoning"), ""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="baseline,agent,llm_only")
    ap.add_argument("--levels", default="2,3,4,5")
    ap.add_argument("--n-per-level", type=int, default=50)
    ap.add_argument("--seed", type=int, default=89)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model", default=config.CLAUDE_MODEL)
    ap.add_argument("--resume", type=Path)
    a = ap.parse_args()
    methods = [m.strip() for m in a.methods.split(",") if m.strip()]
    bad = set(methods) - set(METHODS)
    if bad:
        raise SystemExit(f"unknown methods {bad}; choose from {METHODS}")

    out = a.resume or config.RUNS_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "results.jsonl"
    done = {}
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            r = json.loads(line)
            done[r["id"]] = r

    graph = Graph(connect())
    items, pool = sample(graph, [int(x) for x in a.levels.split(",")], a.n_per_level, a.seed)
    todo = [i for i in items if i["id"] not in done]
    client = None
    if {"agent", "llm_only"} & set(methods):
        from .agent import make_client
        client = make_client()
    print(f"{len(items)} test concepts ({len(done)} already done), methods={methods}, "
          f"model={a.model}, output={out}")

    lock, t0 = threading.Lock(), time.time()
    rows = list(done.values())
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex, open(results_path, "a") as f:
        futs = {ex.submit(evaluate_one, graph, i, methods, client, a.model, out / "traces"): i
                for i in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            item = futs[fut]
            try:
                row = fut.result()
            except Exception as e:
                print(f"  ! {item['name']}: {e}")
                continue
            with lock:
                rows.append(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
            marks = " ".join(f"{m}={row[m]['outcome']}" for m in methods)
            print(f"  [{n}/{len(todo)}] {item['name']} -> {item['parent_name']}: {marks}")

    by_id = {r["id"]: r for r in rows}
    rows = [by_id[i["id"]] for i in items if i["id"] in by_id]
    summary = summarize(rows, methods, pool, a)
    summary["seconds"] = round(time.time() - t0)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    write_review_sheet(rows, "agent" if "agent" in methods else methods[0], out / "review.csv")
    print(json.dumps({m: {k: v for k, v in s.items() if k != "accuracy_by_field"}
                      for m, s in summary["methods"].items()}, indent=1))
    print(f"results: {out}")
    graph.driver.close()


if __name__ == "__main__":
    main()
