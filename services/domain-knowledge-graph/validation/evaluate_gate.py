"""Evaluate the whole gate (layers 1-5).

Two sets:
  --set testset  the SCRUM-90 test set (labels from graph structure). Layer 4 answers are
                 reused from calibrate_blind (same proposals, same options): no new cost.
  --set agent    the realistic stream: every parent the SCRUM-89 agent actually proposed
                 in hide-and-replace (170 concepts), labelled by the blind judge. Used for
                 the teacher-queue rate, which needs no labels; the correctness numbers carry
                 the judge's same-family caveat. One Opus call each (cached, resumable).

Usage: python -m validation.evaluate_gate --set testset
       python -m validation.evaluate_gate --set agent
Writes runs/scrum90-gate/<set>.jsonl and <set>-summary.json
"""
import argparse
import json
from collections import Counter, defaultdict

from placement import config
from placement.graph import Graph, connect

from . import wikidata
from .calibrate_blind import OUT as BLIND_OUT
from .calibrate_semantic import DEFAULT_RUN
from .contract import Proposal
from .gate import validate
from .neo4j_view import ensure_indexes
from .testset import OUT as TESTSET

OUT = config.RUNS_DIR / "scrum90-gate"
GOOD = {"accept"}


def testset_cases():
    blind = {json.loads(l)["case"]: json.loads(l) for l in open(BLIND_OUT / "results.jsonl")}
    for c in map(json.loads, open(TESTSET / "cases.jsonl")):
        yield c, blind.get(c["case"])


def agent_cases():
    items = {json.loads(l)["id"]: json.loads(l) for l in open(DEFAULT_RUN / "results.jsonl")}
    judged = {j["key"]: j for j in map(json.loads, open(DEFAULT_RUN / "judge.jsonl"))}
    for iid, it in items.items():
        a = it.get("agent") or {}
        if a.get("decision") == "already_exists" or not a.get("pred"):
            continue
        verdict = judged.get(f"parent:{iid}", {}).get("verdicts", {}).get(a["pred"])
        yield ({"case": f"agent:{iid}", "kind": f"agent_{verdict}", "hide": [iid], "item": iid,
                "name": it["name"], "description": it["description"] or "",
                "parent_id": a["pred"], "confidence": a.get("confidence"),
                "expected": "accept" if verdict in ("correct", "reasonable") else "not_accept"},
               None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=("testset", "agent"), default="testset")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{a.set}.jsonl"
    # Every run re-decides every case with the current rules. Validator answers stored by an
    # earlier run are reused (no new cost); unreadable ones are asked again.
    cached = {}
    if path.exists():
        for l in open(path):
            r = json.loads(l)
            if (r.get("blind") or {}).get("picked_role") not in (None, "invalid"):
                cached[r["case"]] = r["blind"]
        path.unlink()
    done = {}

    graph = Graph(connect())
    ensure_indexes(graph)
    wd = wikidata.WikidataClient(config.RUNS_DIR / "wikidata-cache.json")
    llm = None
    if a.set == "agent":
        from placement.agent import make_client
        llm = make_client()
    cases = list(testset_cases() if a.set == "testset" else agent_cases())
    cases = [(c, b or cached.get(c["case"])) for c, b in cases]
    with open(path, "a") as f:
        for i, (c, cached_blind) in enumerate(cases, 1):
            if c["case"] in done:
                continue
            g = graph.with_hidden(set(c["hide"]))
            p = Proposal(id=c["item"], name=c["name"], description=c["description"],
                         parent_ids=[c["parent_id"]], confidence=c.get("confidence"))
            res = validate(p, g, llm, wd, blind_override=cached_blind)
            row = {**c, "decision": res.decision.value, "rule": res.rule,
                   "duplicate_of": res.duplicate_of, "suggested_parent": res.suggested_parent,
                   "blind_role": (res.signals.get("blind") or {}).get("picked_role"),
                   "wikidata_support": (res.signals.get("external") or {}).get("support"),
                   "blind": res.signals.get("blind")}     # kept so a rerun costs nothing
            f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
            done[c["case"]] = row
            if i % 10 == 0:
                wd.save()
                print(f"\r{i}/{len(cases)}", end="", flush=True)
    wd.save()
    print()

    rows = list(done.values())
    by_kind = defaultdict(Counter)
    for r in rows:
        by_kind[r["kind"]][r["decision"]] += 1
    n = len(rows)
    good = [r for r in rows if r["expected"] in GOOD]
    bad = [r for r in rows if r["expected"] not in GOOD]
    acc = lambda rs, d: sum(r["decision"] == d for r in rs)
    summary = {
        "set": a.set, "cases": n,
        "decision_by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
        "teacher_rate": round(acc(rows, "NEEDS_REVIEW") / n, 3),
        "good": {"n": len(good), "accepted": acc(good, "ACCEPT_PROVISIONAL"),
                 "rejected": acc(good, "REJECT"), "to_teacher": acc(good, "NEEDS_REVIEW")},
        "bad": {"n": len(bad), "accepted_by_mistake": acc(bad, "ACCEPT_PROVISIONAL"),
                "rejected": acc(bad, "REJECT"), "to_teacher": acc(bad, "NEEDS_REVIEW")},
        "false_accept_rate": round(acc(bad, "ACCEPT_PROVISIONAL") / max(len(bad), 1), 3),
        "false_reject_rate": round(acc(good, "REJECT") / max(len(good), 1), 3),
        "rules": dict(Counter(r["rule"] for r in rows)),
    }
    (OUT / f"{a.set}-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    graph.driver.close()


if __name__ == "__main__":
    main()
