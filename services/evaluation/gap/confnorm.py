"""Empirical confidence norm (decision C1 option C): what each confidence level means.

    norm[c] = share correct among UNAIDED TEST answers rated c, in a SEPARATE calibration
              cohort (its own seed, never the run being evaluated)

Like the item-difficulty calibration of SCRUM-94, the norm replaces an invented mapping
(5 -> 100%) with an observed one, so a rating is never read as more than it means in the
cohort. Read from answers.jsonl only - the truth is never used.

What it measures, said plainly: a learner's gap against this norm is "his ratings predict
more success than the same ratings predict for the cohort" - overconfidence RELATIVE TO THE
COHORT, not against an absolute truth. If the cohort itself is overconfident, the norm
absorbs part of it (decision C2: the main result uses a realistic, contaminated cohort; a
cohort of calibrated learners only is the sensitivity check).

Each level's share is the posterior mean of Beta(k + 1, n - k + 1) (uniform prior), so a
level with few ratings is pulled toward 0.5 rather than to 0 or 1.

    python -m gap.confnorm runs/confnorm-9510 runs/confnorm-9510/norm.json
"""
import json
import sys
from pathlib import Path

TEST_PHASES = ("PRE_TEST", "POST_TEST", "DELAYED_TEST")
LEVELS = (1, 2, 3, 4, 5)


def build(run_dir) -> dict:
    k = {c: 0 for c in LEVELS}
    n = {c: 0 for c in LEVELS}
    with open(Path(run_dir) / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            b = json.loads(line)
            if b["operation"] != "ADD_EVIDENCE":
                continue
            p = b["record"]["payload"]
            if p["activity"] not in TEST_PHASES or p.get("had_help") or p.get("confidence") is None:
                continue
            n[p["confidence"]] += 1
            k[p["confidence"]] += bool(p["correct"])
    man = json.loads((Path(run_dir) / "manifest.json").read_text())
    return {"method": "share correct per confidence level, unaided test answers, Beta(1,1) prior",
            "calibration_seed": man["seed"], "populations": man["populations"],
            "answers_sha256": man["sha256"]["answers.jsonl"],
            "levels": {str(c): {"k": k[c], "n": n[c], "norm": (k[c] + 1) / (n[c] + 2)}
                       for c in LEVELS}}


def load(path) -> dict:
    d = json.loads(Path(path).read_text())
    return {int(c): v["norm"] for c, v in d["levels"].items()}


if __name__ == "__main__":
    run_dir, out = sys.argv[1], sys.argv[2]
    d = build(run_dir)
    Path(out).write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(" ".join(f"{c}:{v['norm']:.3f}(n={v['n']})" for c, v in d["levels"].items()), "->", out)
