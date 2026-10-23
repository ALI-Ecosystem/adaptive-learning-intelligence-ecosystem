"""Item difficulty calibration, on a SEPARATE simulator run (decision A, option 3).

The simulator's items have no difficulty; the evaluator's item model needs one. In the real
system the Task block calibrates b from earlier learners' answers. Here: a calibration run
with its own seed (never the seed being evaluated), and an empirical, centred estimate
(the ALE's "empirical" calibration level, SE_EMPIRICAL):

    x_i  = (p_i - g) / (1 - g - s)          p_i = share correct among unaided answers
    b_raw = -logit(clamp(x_i))
    b_i  = b_raw - mean(b_raw over the bank)   identification: the average item has b = 0
    se_i = |d b / d p| * sqrt(p_i (1 - p_i) / n_i)       delta method

The centring is a CONVENTION: it anchors the item scale at the average item, so a learner
exactly at the target mastery 0.70 answers an average item correctly with probability
g + (1 - g - s) * 0.70. The generator's answer model (knows / does not know) is not used.

    python -m harness.calibrate runs/calib-9400 runs/calib-9400/calibration.json
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

G, S = 0.25, 0.10
CLAMP = (0.02, 0.98)


def calibrate(run_dir) -> dict:
    k, n = defaultdict(int), defaultdict(int)
    with open(Path(run_dir) / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            body = json.loads(line)
            if body["operation"] != "ADD_EVIDENCE":
                continue
            p = body["record"]["payload"]
            if p.get("had_help") or p.get("attempt_number", 1) != 1:
                continue
            n[p["item_id"]] += 1
            k[p["item_id"]] += bool(p["correct"])
    rows = []
    for item in sorted(n):
        p = k[item] / n[item]
        x = min(max((p - G) / (1 - G - S), CLAMP[0]), CLAMP[1])
        b_raw = -math.log(x / (1 - x))
        dbdp = 1.0 / (x * (1 - x) * (1 - G - S))
        se = dbdp * math.sqrt(max(p * (1 - p), 1e-9) / n[item])
        rows.append({"item_id": item, "n": n[item], "p_correct": p, "b_raw": b_raw, "se": se})
    centre = math.fsum(r["b_raw"] for r in rows) / len(rows)
    for r in rows:
        r["b"] = r["b_raw"] - centre
    with open(Path(run_dir) / "manifest.json", encoding="utf-8") as f:
        man = json.load(f)
    return {"method": "empirical, centred (mean b = 0), delta-method se",
            "calibration_seed": man["seed"], "calibration_learners": man["learners"],
            "answers_sha256": man["sha256"]["answers.jsonl"], "centre": centre,
            "guess": G, "slip": S, "items": rows}


if __name__ == "__main__":
    run_dir, out = sys.argv[1], sys.argv[2]
    cal = calibrate(run_dir)
    Path(out).write_text(json.dumps(cal, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    bs = [r["b"] for r in cal["items"]]
    print(f"{len(bs)} items calibrated on seed {cal['calibration_seed']}: "
          f"b in [{min(bs):+.3f}, {max(bs):+.3f}], median se "
          f"{sorted(r['se'] for r in cal['items'])[len(bs) // 2]:.3f} -> {out}")
