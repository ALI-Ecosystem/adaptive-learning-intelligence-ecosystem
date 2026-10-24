"""SCRUM-95 validation of the assisted-versus-unaided gap (part 1: the assisted gap).

    python -m harness.validate95 --run runs/seed-95 --calib runs/calib-9500 --out runs/scrum95

Unit: one (learner, concept, round) for the gap; one (learner, concept) for the reduction.
Truth (scoring side only, from truth.jsonl): the EXPECTED share correct of each answered
item given the learner's true state at that moment (knows / misconception / help), averaged
over the round's unaided and assisted post-test items:

    true gap       = E[assisted share] - E[unaided share];   GAP if true gap > 0.2
    true reduction = true gap (round 1) - true gap (round 3); REDUCED if > 0.1

Baselines (same answers, no uncertainty):
    point      CREDIBLE_GAP if raw assisted share - raw unaided share > 0.2, else NO
    last       CREDIBLE_GAP if the last assisted answer is right and the last unaided wrong
    point-red  REDUCED if the raw gap fell by more than 0.1 from round 1 to round 3

Group level (check asked after the first results): the same raw gaps averaged over a
cohort (here: one population = 200 learners x 3 concepts), with a bootstrap over learners.
A cohort measure answers "did this intervention shrink the gap for the group?" - an offline
evaluation question, not a statement about any one learner.

Every rate is reported with its sample size, a 95% Wilson interval and a 95% interval from
a bootstrap over LEARNERS (a learner's concepts and rounds are not independent).
Writes results.json (every number), results.md (generated tables), measurements.jsonl.
"""
import argparse
import hashlib
import json
import multiprocessing
import os
from collections import defaultdict
from pathlib import Path

from gap import assisted as G
from harness import adapter94 as A
from harness import adapter95 as A5
from harness.validate94 import cluster_ci, wilson

GAP_THRESHOLDS = (0.1, 0.2, 0.3)
RED_THRESHOLDS = (0.0, 0.1, 0.2)
TASK_POPS = {"CONFIDENT_RIGHT": "no credible gap expected",
             "HELP_DEPENDENT": "the gap should be found",
             "HELP_INFLATED": "the gap should be found",
             "LEARNS_FROM_HELP": "the gap should shrink"}

_RUN = {}


def _init(run_dir, calib_path):
    calib = A.load_calibration(calib_path)
    run = A5.load_run95(run_dir, calib)
    _RUN.update(run=run, ls=A.standin_for(run))


def _job(lid):
    L = _RUN["run"][lid]
    return [(lid, cid, A5.round_inputs(L, cid, _RUN["ls"])) for cid in sorted(L["rounds"])]


def compute_inputs(run_dir, calib_path, procs=None):
    _init(run_dir, calib_path)
    lids = sorted(_RUN["run"])
    procs = procs or min(8, os.cpu_count() or 1)
    if procs > 1:
        with multiprocessing.get_context("fork").Pool(procs, _init, (run_dir, calib_path)) as pool:
            parts = pool.map(_job, lids, chunksize=20)
    else:
        parts = [_job(l) for l in lids]
    return [x for p in parts for x in p]


# ---- baselines --------------------------------------------------------------------------------

def raw(cs):
    return sum(cs) / len(cs) if cs else None


def point(ri, thr=G.GAP_THRESHOLD):
    if not ri.unaided or not ri.assisted:
        return G.INSUFFICIENT
    return G.CREDIBLE_GAP if raw(ri.assisted) - raw(ri.unaided) > thr else G.NO_CREDIBLE_GAP


def last(ri):
    if not ri.unaided or not ri.assisted:
        return G.INSUFFICIENT
    return G.CREDIBLE_GAP if ri.assisted[-1] == 1 and ri.unaided[-1] == 0 else G.NO_CREDIBLE_GAP


def point_red(r1, r3, thr=G.REDUCTION_THRESHOLD):
    if not (r1.unaided and r1.assisted and r3.unaided and r3.assisted):
        return G.INSUFFICIENT
    g1 = raw(r1.assisted) - raw(r1.unaided)
    g3 = raw(r3.assisted) - raw(r3.unaided)
    return G.REDUCED if g1 - g3 > thr else G.NOT_REDUCED


# ---- scoring ----------------------------------------------------------------------------------

def group_level(gap_cases, red_cases, b=1000, seed=95):
    """Per population: mean raw gap per round and mean raw reduction, each with a 95%
    bootstrap interval over learners; reduction status by the same 0.8 rule."""
    import random
    out = {}
    for pop in sorted({c["population"] for c in red_cases}):
        rc = [c for c in red_cases if c["population"] == pop and c["raw_reduction"] is not None]
        by_l = defaultdict(list)
        for c in rc:
            by_l[c["learner_id"]].append(c)
        lids = sorted(by_l)
        rounds = sorted({c["round"] for c in gap_cases})
        gl = defaultdict(lambda: defaultdict(list))
        for c in gap_cases:
            if c["population"] == pop and c["raw_gap"] is not None:
                gl[c["learner_id"]][c["round"]].append(c["raw_gap"])
        rng = random.Random(seed)
        boot_red, boot_gap = [], {r: [] for r in rounds}
        for _ in range(b):
            pick = [lids[rng.randrange(len(lids))] for _ in lids]
            xs = [c["raw_reduction"] for l in pick for c in by_l[l]]
            boot_red.append(sum(xs) / len(xs))
            for r in rounds:
                ys = [g for l in pick for g in gl[l][r]]
                boot_gap[r].append(sum(ys) / len(ys))
        q = lambda v: [sorted(v)[int(0.025 * (len(v) - 1))], sorted(v)[int(0.975 * (len(v) - 1))]]
        mean_red = sum(c["raw_reduction"] for c in rc) / len(rc)
        p_red = sum(x > G.REDUCTION_THRESHOLD for x in boot_red) / b
        p_not = sum(x < G.REDUCTION_THRESHOLD for x in boot_red) / b
        true_red = sum(c["true_reduction"] for c in rc) / len(rc)
        out[pop] = {"learners": len(lids), "units": len(rc),
                    "mean_gap_by_round": {r: {"mean": sum(boot_gap[r]) / b, "ci95": q(boot_gap[r])}
                                          for r in rounds},
                    "reduction": {"mean": mean_red, "ci95": q(boot_red), "p_reduced": p_red,
                                  "status": G.three_way(p_red, p_not, G.REDUCED, G.NOT_REDUCED)},
                    "true_mean_reduction": true_red,
                    "true_status": G.REDUCED if true_red > G.REDUCTION_THRESHOLD else G.NOT_REDUCED}
    return out


def score(cases, key, yes, no):
    """cases: dicts with 'truth' (bool), key -> status, 'learner_id'."""
    pos = [c for c in cases if c["truth"]]
    neg = [c for c in cases if not c["truth"]]
    st = lambda cs, v: [int(c[key] == v) for c in cs]
    out = {"n": len(cases), "true_positive_cases": len(pos),
           "found": wilson(sum(st(pos, yes)), len(pos)),
           "false_yes": wilson(sum(st(neg, yes)), len(neg)),
           "wrong_no": wilson(sum(st(pos, no)), len(pos)),
           "correct_no": wilson(sum(st(neg, no)), len(neg)),
           "insufficient": wilson(sum(int(c[key] == G.INSUFFICIENT) for c in cases), len(cases))}
    dec = [c for c in cases if c[key] != G.INSUFFICIENT]
    wrong = [c for c in dec if (c[key] == yes) != c["truth"]]
    out["error_among_decided"] = wilson(len(wrong), len(dec))
    out["false_yes_cluster"] = cluster_ci([(c["learner_id"], int(c[key] == yes)) for c in neg])
    out["wrong_no_cluster"] = cluster_ci([(c["learner_id"], int(c[key] == no)) for c in pos])
    return out


def shares(cases, key):
    n = len(cases)
    cnt = defaultdict(int)
    for c in cases:
        cnt[c[key]] += 1
    return {k: wilson(v, n) for k, v in sorted(cnt.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/seed-95")
    ap.add_argument("--calib", default="runs/calib-9500")
    ap.add_argument("--out", default="runs/scrum95")
    ap.add_argument("--procs", type=int, default=1, help="worker processes (a fork pool hung in the Linux VM; 1 takes ~2 minutes)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    calib_path = str(Path(a.calib) / "calibration.json")

    inputs = compute_inputs(a.run, calib_path, a.procs)
    truth = A5.load_truth95(a.run)

    gap_cases, red_cases, lines = [], [], []
    sens_gap = {t: [] for t in GAP_THRESHOLDS}
    sens_red = {t: [] for t in RED_THRESHOLDS}
    for lid, cid, ris in inputs:
        tr = truth[(lid, cid)]
        pop = tr["population"]
        m = G.measure(lid, cid, ris)
        lines.append(json.dumps(m, sort_keys=True, separators=(",", ":")))
        for ri, mr in zip(sorted(ris, key=lambda r: r.round), m["rounds"]):
            t = tr["rounds"][ri.round]
            base = {"learner_id": lid, "concept_id": cid, "population": pop, "round": ri.round,
                    "true_gap": t["true_gap"], "known": t["known"]}
            base["raw_gap"] = (raw(ri.assisted) - raw(ri.unaided)
                               if ri.assisted and ri.unaided else None)
            gap_cases.append(dict(base, truth=t["true_gap"] > G.GAP_THRESHOLD,
                                  measure=mr["gap"]["status"], point=point(ri), last=last(ri),
                                  verdict=ri.verdict))
            for thr in GAP_THRESHOLDS:
                s = G.round_gap(ri, thr)["gap"]["status"]
                sens_gap[thr].append(dict(base, truth=t["true_gap"] > thr, measure=s))
        r1, r3 = sorted(ris, key=lambda r: r.round)[0], sorted(ris, key=lambda r: r.round)[-1]
        true_red = tr["rounds"][r1.round]["true_gap"] - tr["rounds"][r3.round]["true_gap"]
        ok = r1.unaided and r1.assisted and r3.unaided and r3.assisted
        base = {"learner_id": lid, "concept_id": cid, "population": pop, "true_reduction": true_red,
                "raw_reduction": ((raw(r1.assisted) - raw(r1.unaided))
                                  - (raw(r3.assisted) - raw(r3.unaided))) if ok else None}
        red_cases.append(dict(base, truth=true_red > G.REDUCTION_THRESHOLD,
                              measure=m["reduction"]["status"], point=point_red(r1, r3),
                              path="→".join(s.split("_")[0] for s in m["reduction"]["status_path"])))
        for thr in RED_THRESHOLDS:
            rs = [G.round_gap(r) for r in sorted(ris, key=lambda r: r.round)]
            s = G.reduction(rs[0], rs[-1], thr)["status"]
            sens_red[thr].append(dict(base, truth=true_red > thr, measure=s))

    (out / "measurements.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    pops = sorted({c["population"] for c in gap_cases})
    rounds = sorted({c["round"] for c in gap_cases})
    res = {"thresholds": {"gap": G.GAP_THRESHOLD, "reduction": G.REDUCTION_THRESHOLD,
                          "credibility": G.CREDIBILITY},
           "n_cases_gap": len(gap_cases), "n_cases_reduction": len(red_cases),
           "gap_overall": {k: score(gap_cases, k, G.CREDIBLE_GAP, G.NO_CREDIBLE_GAP)
                           for k in ("measure", "point", "last")},
           "gap_by_round": {r: score([c for c in gap_cases if c["round"] == r], "measure",
                                     G.CREDIBLE_GAP, G.NO_CREDIBLE_GAP) for r in rounds},
           "gap_by_population": {}, "reduction_by_population": {},
           "reduction_overall": {k: score(red_cases, k, G.REDUCED, G.NOT_REDUCED)
                                 for k in ("measure", "point")},
           "sensitivity_gap": {str(t): score(v, "measure", G.CREDIBLE_GAP, G.NO_CREDIBLE_GAP)
                               for t, v in sens_gap.items()},
           "sensitivity_reduction": {str(t): score(v, "measure", G.REDUCED, G.NOT_REDUCED)
                                     for t, v in sens_red.items()},
           "group_level": group_level(gap_cases, red_cases)}
    for p in pops:
        cs = [c for c in gap_cases if c["population"] == p]
        res["gap_by_population"][p] = {
            "true_gap_share": wilson(sum(c["truth"] for c in cs), len(cs)),
            "mean_true_gap_by_round": {r: sum(c["true_gap"] for c in cs if c["round"] == r)
                                       / sum(1 for c in cs if c["round"] == r) for r in rounds},
            "measure_by_round": {r: shares([c for c in cs if c["round"] == r], "measure")
                                 for r in rounds},
            "measure": score(cs, "measure", G.CREDIBLE_GAP, G.NO_CREDIBLE_GAP),
            "point": score(cs, "point", G.CREDIBLE_GAP, G.NO_CREDIBLE_GAP),
            "last": score(cs, "last", G.CREDIBLE_GAP, G.NO_CREDIBLE_GAP)}
        rc = [c for c in red_cases if c["population"] == p]
        paths = defaultdict(int)
        for c in rc:
            paths[c["path"]] += 1
        res["reduction_by_population"][p] = {
            "mean_true_reduction": sum(c["true_reduction"] for c in rc) / len(rc),
            "true_reduced_share": wilson(sum(c["truth"] for c in rc), len(rc)),
            "measure": shares(rc, "measure"), "point": shares(rc, "point"),
            "score": score(rc, "measure", G.REDUCED, G.NOT_REDUCED),
            "top_paths": sorted(paths.items(), key=lambda kv: -kv[1])[:4]}
    man = json.loads((Path(a.run) / "manifest.json").read_text())
    res["inputs"] = {"run": a.run, "run_answers_sha256": man["sha256"]["answers.jsonl"],
                     "calibration_sha256": hashlib.sha256(Path(calib_path).read_bytes()).hexdigest()}
    (out / "results.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
    from harness.report95 import render
    (out / "results.md").write_text(render(res), encoding="utf-8")
    print(f"{len(gap_cases)} round cases, {len(red_cases)} reduction cases -> {out}/results.md")


if __name__ == "__main__":
    main()
