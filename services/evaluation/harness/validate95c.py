"""SCRUM-95 validation, part 2: the perceived-versus-demonstrated (confidence) gap.

    python -m harness.validate95c --run runs/seed-95 --calib runs/calib-9500 --out runs/scrum95

Norms (decision C2): MAIN from runs/confnorm-9510 (all ten populations, confidence missing not
at random - realistic, contaminated by overconfident learners); CLEAN from
runs/confnorm-9511-clean (calibrated populations only, every answer reported) - the
sensitivity check. Both are separate seeds; the run being evaluated is never used.

Truth (scoring only, decision C5 option B - "by design"): per round, over ALL the round's
unaided post-test answers (reported or not - the truth describes the learner):
    true inflation = mean CLEAN-norm[true rating] - mean CLEAN-norm[rating without inflation]
    where "without inflation" is the same rating with conf_bias and the help boost removed
    ABOVE if > 0.2, BELOW if < -0.2 (none by design), else NONE
    true reduction = |inflation r1| - |inflation r3| > 0.1
A first truth (clean-norm rating minus expected correctness) labelled half the calibrated-
by-design DOES_NOT_LEARN cases as overconfident: noisy ratings regress toward the norm, so
weak learners look overconfident and strong ones underconfident (the regression artifact
known from critiques of the Dunning-Kruger effect). The measure flagged only 2.5% of them;
the truth was wrong, not the measure. Scoring is therefore against what actually inflated
the ratings.

Naive baseline (from the task): PERCEIVED_ABOVE if the last reported unaided answer of the
round has confidence >= 4 and is wrong, else NO_CREDIBLE_GAP.

Writes results_confidence.json and results_confidence.md; caches the gate's round inputs in
inputs.pkl (shared with validate95).
"""
import argparse
import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path

from gap import confidence as C
from gap.assisted import INSUFFICIENT, NOT_REDUCED, REDUCED
from gap.confnorm import load as load_norm
from harness import adapter95 as A5
from harness.validate94 import cluster_ci, wilson

TH = C.GAP_THRESHOLD


def truth_class(g):
    return C.ABOVE if g > TH else C.BELOW if g < -TH else C.NONE


def naive(pairs):
    rep = [(k, c) for k, c in pairs if c is not None]
    if not rep:
        return INSUFFICIENT
    k, c = rep[-1]
    return C.ABOVE if c >= 4 and k == 0 else C.NONE


def score(cases, key):
    out = {"n": len(cases)}
    for cls in (C.ABOVE, C.BELOW):
        pos = [c for c in cases if c["truth"] == cls]
        neg = [c for c in cases if c["truth"] != cls]
        out[f"found_{cls}"] = wilson(sum(c[key] == cls for c in pos), len(pos))
        out[f"false_{cls}"] = wilson(sum(c[key] == cls for c in neg), len(neg))
        out[f"false_{cls}_cluster"] = cluster_ci([(c["learner_id"], int(c[key] == cls)) for c in neg])
    none = [c for c in cases if c["truth"] == C.NONE]
    out["found_NONE"] = wilson(sum(c[key] == C.NONE for c in none), len(none))
    out["insufficient"] = wilson(sum(c[key] == INSUFFICIENT for c in cases), len(cases))
    dec = [c for c in cases if c[key] != INSUFFICIENT]
    out["error_among_decided"] = wilson(sum(c[key] != c["truth"] for c in dec), len(dec))
    out["confusion"] = {t: dict(Counter(c[key] for c in cases if c["truth"] == t))
                        for t in (C.ABOVE, C.NONE, C.BELOW)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/seed-95")
    ap.add_argument("--calib", default="runs/calib-9500")
    ap.add_argument("--norm", default="runs/confnorm-9510/norm.json")
    ap.add_argument("--clean-norm", default="runs/confnorm-9511-clean/norm.json")
    ap.add_argument("--out", default="runs/scrum95")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "inputs.pkl"
    if cache.exists():
        inputs = pickle.loads(cache.read_bytes())
    else:
        from harness.validate95 import compute_inputs
        inputs = compute_inputs(a.run, str(Path(a.calib) / "calibration.json"), 1)
        cache.write_bytes(pickle.dumps(inputs))
    from harness import adapter94 as A
    run = A5.load_run95(a.run, A.load_calibration(str(Path(a.calib) / "calibration.json")))
    truth = A5.load_truth95(a.run)
    norm, clean = load_norm(a.norm), load_norm(a.clean_norm)

    variants = {"main": (norm, C.PRIOR_WEIGHT), "clean_norm": (clean, C.PRIOR_WEIGHT),
                "prior_n0_2": (norm, 2.0)}
    cases = {v: [] for v in variants}
    red = {v: [] for v in variants}
    nsr = []                                    # NO_SELF_REPORT check
    detect = defaultdict(list)
    lines = []
    for lid, cid, ris in inputs:
        tr = truth[(lid, cid)]
        pop = tr["population"]
        conf = run[lid]["confidence"]
        crs = [C.ConfRound(r.round, tuple((cr, conf[rid]) for cr, rid in zip(r.unaided, r.unaided_records)))
               for r in sorted(ris, key=lambda r: r.round)]
        tg = {r: sum(clean[c] - clean[u] for c, _, u in v["confidence_rows"]) / len(v["confidence_rows"])
              for r, v in tr["rounds"].items()}
        for name, (nm, n0) in variants.items():
            m = C.measure(lid, cid, crs, nm, n0=n0)
            if name == "main":
                lines.append(json.dumps(m, sort_keys=True, separators=(",", ":")))
                nsr.append({"never": tr["never_reports"], "status": m["status"], "learner_id": lid})
            if m["status"] == C.NO_SELF_REPORT:
                continue
            for cr, mr in zip(crs, m["rounds"]):
                cases[name].append({"learner_id": lid, "population": pop, "round": cr.round,
                                    "true_gap": tg[cr.round], "truth": truth_class(tg[cr.round]),
                                    "measure": mr["gap"]["status"], "naive": naive(cr.answers),
                                    "discrimination": mr["discrimination"]})
            tred = abs(tg[crs[0].round]) - abs(tg[crs[-1].round])
            red[name].append({"learner_id": lid, "population": pop, "true_reduction": tred,
                              "truth": REDUCED if tred > C.REDUCTION_THRESHOLD else NOT_REDUCED,
                              "measure": m["reduction"]["status"]})
            if name == "main" and truth_class(tg[crs[0].round]) == C.ABOVE:
                detect[pop].append(C.answers_to_detect(crs[0].answers, nm, n0=n0))
    (out / "measurements_confidence.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = {"thresholds": {"gap": TH, "reduction": C.REDUCTION_THRESHOLD, "prior_weight": C.PRIOR_WEIGHT},
           "norm_main": norm, "norm_clean": clean,
           "no_self_report": {
               "never_reporters_flagged": wilson(sum(x["status"] == C.NO_SELF_REPORT for x in nsr if x["never"]),
                                                 sum(x["never"] for x in nsr)),
               "reporters_flagged": wilson(sum(x["status"] == C.NO_SELF_REPORT for x in nsr if not x["never"]),
                                           sum(not x["never"] for x in nsr))},
           "overall": {v: score(cs, "measure") for v, cs in cases.items()},
           "naive": score(cases["main"], "naive"),
           "by_population": {}, "reduction": {}, "answers_to_detect": {}}
    pops = sorted({c["population"] for c in cases["main"]})
    for p in pops:
        cs = [c for c in cases["main"] if c["population"] == p]
        sh = Counter(c["measure"] for c in cs)
        tr_ = Counter(c["truth"] for c in cs)
        disc = [c["discrimination"] for c in cs if c["discrimination"] is not None]
        res["by_population"][p] = {
            "n": len(cs), "mean_true_gap": sum(c["true_gap"] for c in cs) / len(cs),
            "truth": {k: wilson(v, len(cs)) for k, v in sorted(tr_.items())},
            "measure": {k: wilson(v, len(cs)) for k, v in sorted(sh.items())},
            "naive_above": wilson(sum(c["naive"] == C.ABOVE for c in cs), len(cs)),
            "clean_norm": {k: wilson(v, len(cs)) for k, v in sorted(Counter(
                c["measure"] for c in cases["clean_norm"] if c["population"] == p).items())},
            "mean_discrimination": sum(disc) / len(disc) if disc else None}
        rc = [c for c in red["main"] if c["population"] == p]
        res["reduction"][p] = {"mean_true": sum(c["true_reduction"] for c in rc) / len(rc),
                               "measure": {k: wilson(v, len(rc)) for k, v in
                                           sorted(Counter(c["measure"] for c in rc).items())}}
    for p, xs in sorted(detect.items()):
        found = sorted(x for x in xs if x is not None)
        res["answers_to_detect"][p] = {"cases": len(xs), "found_in_round1": wilson(len(found), len(xs)),
                                       "median": found[len(found) // 2] if found else None,
                                       "distribution": dict(sorted(Counter(found).items()))}
    res["reduction_overall"] = {v: {
        "found": wilson(sum(c["measure"] == REDUCED for c in rs if c["truth"] == REDUCED),
                        sum(c["truth"] == REDUCED for c in rs)),
        "false_reduced": wilson(sum(c["measure"] == REDUCED for c in rs if c["truth"] != REDUCED),
                                sum(c["truth"] != REDUCED for c in rs)),
        "insufficient": wilson(sum(c["measure"] == INSUFFICIENT for c in rs), len(rs))}
        for v, rs in red.items()}
    (out / "results_confidence.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n",
                                                 encoding="utf-8")
    from harness.report95 import render_confidence
    (out / "results_confidence.md").write_text(render_confidence(res), encoding="utf-8")
    print(f"{len(cases['main'])} round cases -> {out}/results_confidence.md")


if __name__ == "__main__":
    main()
