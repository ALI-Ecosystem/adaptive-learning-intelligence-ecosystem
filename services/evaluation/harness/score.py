"""Scores the naive rules' decisions against the truth.

Unit: one (learner, concept) at one checkpoint. Truth (decision: option B):
"learned because of the intervention" = the learner knows the concept when the test
begins AND his twin, who got no intervention, does not.

For every rule x checkpoint, overall and per population:
  n, TP, FP, FN, TN
  error rate                    (FP + FN) / n
  false "learned" rate          FP / (FP + TN)   - said learned, did not learn from it
  missed learning rate          FN / (FN + TP)   - learned from it, rule said no
each with a 95% Wilson score interval. Empty cells are reported as n = 0, never hidden.

Wilson treats every (learner, concept) as independent, but the three concepts of one
learner are not (same parameters, same timeline), so for the main target the error rate
also gets a 95% CLUSTER BOOTSTRAP interval: learners are resampled with replacement
(B = 500, fixed seed). Report that one when the two differ.

"ALL" pools the seven populations in equal numbers - a choice of the simulation, not a
real class mix - so it is a summary of this run, not a headline number.

A secondary target, "knows now" (no twin), is scored the same way: it shows how much of a
rule's error comes from not separating "learned from the intervention" from "knew anyway".
"""
import json
import math
import random
from collections import defaultdict
from pathlib import Path

Z = 1.959963984540054
TARGETS = {"learned_due_to_intervention": "learned_due_to_intervention", "knows_now": "known"}


def wilson(k: int, n: int) -> tuple:
    if n == 0:
        return (None, None, None)
    p = k / n
    den = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / den
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def cluster_bootstrap(per_learner: dict, b: int = 500, seed: int = 0) -> tuple:
    """per_learner: {learner_id: (errors, n)} -> (low, high) of the pooled error rate."""
    vals = list(per_learner.values())
    if not vals:
        return (None, None)
    rng = random.Random(seed)
    stats = []
    for _ in range(b):
        e = n = 0
        for _ in vals:
            ei, ni = vals[rng.randrange(len(vals))]
            e += ei
            n += ni
        stats.append(e / n)
    stats.sort()
    return (stats[int(0.025 * b)], stats[int(0.975 * b) - 1])


def cell(rows, learners=None) -> dict:
    tp = sum(d and t for d, t in rows)
    fp = sum(d and not t for d, t in rows)
    fn = sum((not d) and t for d, t in rows)
    tn = sum((not d) and (not t) for d, t in rows)
    n = len(rows)
    out_boot = None
    if learners is not None:
        per = defaultdict(lambda: [0, 0])
        for (d, t), lid in zip(rows, learners):
            per[lid][0] += d != t
            per[lid][1] += 1
        out_boot = cluster_bootstrap({k: tuple(v) for k, v in sorted(per.items())})
    return {"n": n, "learners": len(set(learners)) if learners else None,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "positives": tp + fn,
            "error_cluster_ci": out_boot,
            "error": wilson(fp + fn, n),
            "false_learned": wilson(fp, fp + tn),
            "missed_learning": wilson(fn, fn + tp)}


def score(run_dir) -> dict:
    run_dir = Path(run_dir)
    truth, pop = {}, {}
    with open(run_dir / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            pop[t["learner_id"]] = t["population"]
            for cp, v in t["checkpoints"].items():
                for cid, s in v["concepts"].items():
                    truth[(t["learner_id"], cid, cp)] = s
    groups, owners = defaultdict(list), defaultdict(list)
    with open(run_dir / "decisions.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            s = truth[(d["learner_id"], d["concept_id"], d["checkpoint"])]
            for target, field in TARGETS.items():
                pair = (d["learned"], s[field])
                for k in ((target, d["rule"], d["checkpoint"], "ALL"),
                          (target, d["rule"], d["checkpoint"], pop[d["learner_id"]])):
                    groups[k].append(pair)
                    owners[k].append(d["learner_id"])
    result = [dict(zip(("target", "rule", "checkpoint", "population"), k),
                   **cell(v, owners[k] if k[0] == "learned_due_to_intervention" else None))
              for k, v in sorted(groups.items())]
    (run_dir / "score.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    (run_dir / "score.md").write_text(to_markdown(result), encoding="utf-8")
    return {"rows": result}


def _fmt(w) -> str:
    p, lo, hi = w
    return "n/a" if p is None else f"{p:5.1%} [{lo:.1%}, {hi:.1%}]"


def to_markdown(rows, target="learned_due_to_intervention") -> str:
    lines = [f"Target: {target}. Rates with 95% Wilson intervals. SIMULATION RESULT.", ""]
    for rule in sorted({r["rule"] for r in rows}):
        for cp in ("immediate", "delayed"):
            lines += [f"## {rule} - {cp}", "",
                      "| population | learners | n | truly learned | error | error, cluster CI | false learned | missed learning |",
                      "|---|---|---|---|---|---|---|---|"]
            sel = [r for r in rows if r["target"] == target and r["rule"] == rule
                   and r["checkpoint"] == cp]
            sel.sort(key=lambda r: (r["population"] != "ALL", r["population"]))
            for r in sel:
                lo, hi = r["error_cluster_ci"] or (None, None)
                boot = "n/a" if lo is None else f"[{lo:.1%}, {hi:.1%}]"
                lines.append(f"| {r['population']} | {r['learners']} | {r['n']} | {r['positives']} | "
                             f"{_fmt(r['error'])} | {boot} | {_fmt(r['false_learned'])} | "
                             f"{_fmt(r['missed_learning'])} |")
            lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    rd = sys.argv[1] if len(sys.argv) > 1 else "runs/seed-93"
    out = score(rd)
    print((Path(rd) / "score.md").read_text())
    alls = [r for r in out["rows"] if r["population"] == "ALL" and r["target"] == "knows_now"]
    print("Secondary target knows_now (ALL):")
    for r in alls:
        print(f"  {r['rule']:20s} {r['checkpoint']:9s} error {_fmt(r['error'])}")
