"""SCRUM-94 validation: the verdict against the simulator's truth and against the baselines.

    python -m harness.validate94 --runs runs --out runs/scrum94

Reads (made by scrum94.sh):
  runs/calib-9400/                 calibration run (its own seed), + calibration.json
  runs/seed-93/                    the SCRUM-93 run (3 post-test items), unchanged
  runs/seed-93-L{5,8,12,16}/       the same learners with a longer post-test

Writes runs/scrum94/results.json (every number) and results.md (generated tables), and a
manifest with the SHA-256 of every input and of the code. Nothing here is typed by hand.

Unit: one (learner, concept) case, judged at the end of its immediate post-test.
Truth (scoring only): KNOWS = the learner knows the concept when the post-test begins
(the verdict's question: does he now perform at the target unaided?); LEARNED = knows AND
his twin without the intervention does not (the causal question a per-learner verdict
cannot answer - reported to show exactly that).
"""
import argparse
import hashlib
import json
import math
import multiprocessing
import os
import random
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from harness import adapter94 as A
from harness import baselines94 as B
from harness.contaminate import EXPECTED, FRESH_B, FRESH_SE, contaminate
from simulator.populations import BY_NAME
from verdict import engine, model
from verdict.contracts import Exclusion
from verdict.standin import FixedBaselineReader

Z = 1.959963984540054
LENGTHS = (3, 5, 8, 12, 16)
DEM, NOT, INS = "DEMONSTRATED", "NOT_YET_DEMONSTRATED", "INSUFFICIENT_EVIDENCE"
PERTURB = {   # mis-estimated baselines: (alpha, beta) -> mu0, n
    "UNDER_WEAK": (0.4, 3.6), "UNDER_STRONG": (3.0, 27.0),
    "OVER_WEAK": (2.6, 1.4), "OVER_STRONG": (19.5, 10.5)}
STRONG_N = 30.0


# ---- statistics ---------------------------------------------------------------------------

def wilson(k, n):
    if n == 0:
        return None
    p = k / n
    den = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / den
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return {"k": k, "n": n, "p": p, "lo": max(0.0, c - h), "hi": min(1.0, c + h)}


def cluster_ci(pairs, b=500, seed=94):
    """pairs: [(learner_id, hit 0/1)] in a fixed order -> 95% bootstrap CI of the rate,
    resampling LEARNERS (a learner's three concepts are not independent)."""
    per = defaultdict(lambda: [0, 0])
    for lid, hit in pairs:
        per[lid][0] += hit
        per[lid][1] += 1
    vals = [tuple(per[k]) for k in sorted(per)]
    if not vals:
        return None
    rng = random.Random(seed)
    ks = [v[0] for v in vals]
    ns = [v[1] for v in vals]
    idx = range(len(vals))
    stats = []
    for _ in range(b):
        pick = rng.choices(idx, k=len(vals))
        n = sum(ns[i] for i in pick)
        stats.append(sum(ks[i] for i in pick) / n if n else 0.0)
    stats.sort()
    return [stats[round(0.025 * (b - 1))], stats[round(0.975 * (b - 1))]]


def rates(cases, decide, truth_key="known", cluster=False):
    """decide(case) -> DEM / NOT / INS (binary methods return DEM or NOT)."""
    neg = [c for c in cases if not c[truth_key]]
    pos = [c for c in cases if c[truth_key]]
    d_neg = [decide(c) for c in neg]
    d_pos = [decide(c) for c in pos]
    out = {"n": len(cases), "positives": len(pos),
           "false_demonstrated": wilson(sum(d == DEM for d in d_neg), len(neg)),
           "miss": wilson(sum(d != DEM for d in d_pos), len(pos)),
           "wrong_not_yet": wilson(sum(d == NOT for d in d_pos), len(pos)),
           "insufficient": wilson(sum(d == INS for d in d_neg + d_pos), len(cases)),
           "correct_not_yet": wilson(sum(d == NOT for d in d_neg), len(neg)),
           "decided": wilson(sum(d != INS for d in d_neg + d_pos), len(cases)),
           "wrong_decisions": wilson(sum(d == DEM for d in d_neg) + sum(d == NOT for d in d_pos),
                                     len(cases)),
           "error_among_decided": wilson(
               sum(d == DEM for d in d_neg) + sum(d == NOT for d in d_pos),
               sum(d != INS for d in d_neg + d_pos))}
    if cluster:
        out["false_demonstrated_cluster"] = cluster_ci(
            [(c["learner_id"], int(d == DEM)) for c, d in zip(neg, d_neg)])
        out["miss_cluster"] = cluster_ci(
            [(c["learner_id"], int(d != DEM)) for c, d in zip(pos, d_pos)])
    return out


# ---- per-case evaluation --------------------------------------------------------------------

def bkt_steps(L, cid, iv, as_of, mode, oracle=None, judged=None):
    """The knowledge-tracing input for one case. mode ALL observes every answer; INDEP
    observes only answers that are unaided, first attempts, unseen, and not produced by the
    intervention, and uses the others as learning opportunities only."""
    steps, exposed = [], False
    indep_ok = set()
    for a, r in judged or []:
        # counted by the verdict, or an unaided first attempt from before the treatment
        # (the pre-test): independent evidence, though not evidence AFTER the intervention
        if r is None or (r == Exclusion.BEFORE_TREATMENT_END and not a.help_before_answer
                         and a.attempt_number == 1):
            indep_ok.add(a.record_id)
    for a in L["answers"]:
        if a.concept_id != cid or a.occurred_at > as_of:
            continue
        if not exposed and a.occurred_at > iv.delivered_at:
            exposed = True
            steps.append(("EXPOSURE", None) if oracle is None else
                         ("EXPOSURE", None, oracle["T_int"]))
        ph = L["phase"][a.record_id]
        t = None
        if oracle is not None:
            t = oracle["T"] if ph == "PRACTICE" else 0.0
        observe = mode == "ALL" or a.record_id in indep_ok
        kind = "OBS" if observe else "OPP"
        steps.append((kind, a.credit) if t is None else (kind, a.credit, t))
    if not exposed:
        steps.append(("EXPOSURE", None) if oracle is None else ("EXPOSURE", None, oracle["T_int"]))
    return steps


def measure(ev, trace=False):
    """The selected verdict and the alternatives considered, on the SAME counted answers and
    the same prior; with trace, the status after each answer (sequential view)."""
    pp, tt, cfg = ev["prior"], ev["theta_t"], ev["cfg"]
    post = model.Posterior(pp["theta0"], pp["sd"])
    flat = model.Posterior(None, None)
    steps = []
    for a in ev["counted"]:
        post.add(a.credit, a.item_b, a.item_b_se, a.guess_rate, cfg["slip"],
                 a.w_correct, a.w_incorrect)
        flat.add(a.credit, a.item_b, a.item_b_se, a.guess_rate, cfg["slip"],
                 a.w_correct, a.w_incorrect)
        if trace:
            p_, bf_, _ = post.read(tt)
            steps.append((post.n, model.status_from(p_, bf_, post.n)))
    n = post.n
    p, bf, _ = post.read(tt)
    p0, _, _ = post.read(pp["theta0"])
    pf, _, _ = flat.read(tt)

    def three(x_dem, x_not):
        if n == 0:
            return INS
        return DEM if x_dem else (NOT if x_not else INS)
    cred = model.CREDIBILITY
    sel = {model.SUPPORTED: DEM, model.NOT_SUPPORTED: NOT,
           model.INSUFFICIENT: INS}[model.status_from(p, bf, n)]
    ap = {"selected": sel,
          "posterior_only": three(p >= cred, p <= 1 - cred),
          "bf_only": three(bf >= model.BF_THRESHOLD, bf <= 1 / model.BF_THRESHOLD),
          "fixed_target_no_prior": three(pf >= cred, pf <= 1 - cred),
          "pre_post": three(p0 >= cred, p0 <= 1 - cred)}
    first_k = first_status = None
    for k, st in steps:
        if st != model.INSUFFICIENT:
            first_k, first_status = k, st
            break
    return {"outcome": sel, "p": p if n else None, "bf": bf if n else None, "n_counted": n,
            "mu0": ev["baseline"].mean, "n0": ev["baseline"].n, "k": ev["k"],
            "approaches": ap, "first_k": first_k, "first_status": first_status,
            "ever_dem": any(st == model.SUPPORTED for _, st in steps)}


def evaluate_run(run_dir, calib, fitted, truth_needed=True, extra_readers=None,
                 do_bkt=True, contaminated=None):
    run = A.load_run(run_dir, calib)
    ls = A.standin_for(run)
    truth = A.load_truth(run_dir) if truth_needed else {}
    strong = FixedBaselineReader(STRONG_N / 2, STRONG_N / 2, inner=ls, keep_mean_of_inner=True)
    readers = {"standin": ls, "strong": strong}
    for name, (a, b) in (extra_readers or {}).items():
        readers[name] = FixedBaselineReader(a, b)
    cases = []
    for lid in sorted(run):
        L = run[lid]
        answers, shown = L["answers"], []
        for cid in sorted(L["interventions"]):
            iv = L["interventions"][cid]
            as_of = L["as_of"][cid]
            t = truth.get((lid, cid), {})
            c = {"learner_id": lid, "concept_id": cid, "population": t.get("population"),
                 "known": t.get("known"), "learned": t.get("learned_due_to_intervention"),
                 "known_at_start": t.get("known_at_start")}
            for rname, reader in readers.items():
                ev = engine.prepare(iv, reader, answers, shown, as_of)
                res = measure(ev, trace=rname in ("standin", "strong"))
                c[rname] = res
                if rname == "standin":
                    v = engine.decide(ev, iv, answers, shown, as_of)
                    assert (v.outcome.value, v.p_target, v.bayes_factor) == (
                        res["outcome"], res["p"], res["bf"]), "harness disagrees with engine"
                    c["exclusions"] = dict(Counter(j.exclusion or "COUNTED" for j in v.answers))
                    c["sha"] = v.inputs_sha256
                    judged = ev["judged"]
            credits = [a.credit for a in answers if a.concept_id == cid and a.occurred_at <= as_of]
            c["naive"] = DEM if B.naive_three_of_last_four(credits) else NOT
            if do_bkt:
                pop = c["population"]
                orc = B.oracle_params(asdict(BY_NAME[pop].params)) if pop else None
                for mode in ("ALL", "INDEP"):
                    st = bkt_steps(L, cid, iv, as_of, mode, judged=judged)
                    f = fitted[mode]
                    pl = B.bkt_trace(st, f["L0"], f["T"], f["G"], f["S"])
                    c[f"bkt_fitted_{mode}"] = DEM if pl >= B.MASTERY else NOT
                    c[f"bkt_fitted_{mode}_3way"] = (DEM if pl >= B.MASTERY else
                                                    NOT if pl <= 1 - B.MASTERY else INS)
                    c[f"bkt_fitted_{mode}_pL"] = pl
                    if orc:
                        so = bkt_steps(L, cid, iv, as_of, mode, oracle=orc, judged=judged)
                        po = B.bkt_trace(so, orc["L0"], orc["T"], orc["G"], orc["S"])
                        c[f"bkt_oracle_{mode}"] = DEM if po >= B.MASTERY else NOT
                for rname in readers:
                    if rname in ("standin", "strong"):
                        continue
                    mu0 = c[rname]["mu0"]
                    st = bkt_steps(L, cid, iv, as_of, "INDEP", judged=judged)
                    # seeded AT THE EXPOSURE: the baseline already stands for everything
                    # before delivery, so the pre-test is not observed a second time
                    st = st[next(i for i, x in enumerate(st) if x[0] == "EXPOSURE"):]
                    f = fitted["INDEP"]
                    pl = B.bkt_trace(st, mu0, f["T"], f["G"], f["S"])
                    c[rname]["bkt_seeded"] = DEM if pl >= B.MASTERY else NOT
            cases.append(c)
    return run, ls, cases


def fit_on_calibration(calib_dir, calib):
    run = A.load_run(calib_dir, calib)
    seqs = {"ALL": [], "INDEP": []}
    for lid in sorted(run):
        L = run[lid]
        for cid in sorted(L["interventions"]):
            iv = L["interventions"][cid]
            ev = engine.prepare(iv, A.standin_for({lid: L}), L["answers"], [], L["as_of"][cid])
            for mode in seqs:
                seqs[mode].append(bkt_steps(L, cid, iv, L["as_of"][cid], mode,
                                            judged=ev["judged"]))
    return {mode: B.fit_bkt(s) for mode, s in seqs.items()}


# ---- the experiments ----------------------------------------------------------------------

METHODS_BASE = ["naive", "bkt_oracle_ALL", "bkt_oracle_INDEP", "bkt_fitted_ALL",
                "bkt_fitted_INDEP", "bkt_fitted_ALL_3way", "bkt_fitted_INDEP_3way"]
APPROACHES = ["selected", "posterior_only", "bf_only", "fixed_target_no_prior", "pre_post"]


def decider(name, reader="standin"):
    if name in APPROACHES:
        return lambda c: c[reader]["approaches"][name]
    return lambda c: c[name]


def table_main(cases):
    pops = sorted({c["population"] for c in cases})
    out = {}
    for target in ("known", "learned"):
        out[target] = {}
        for m in APPROACHES + METHODS_BASE:
            out[target][m] = {"ALL": rates(cases, decider(m), target, cluster=True)}
            for p in pops:
                out[target][m][p] = rates([c for c in cases if c["population"] == p],
                                          decider(m), target)
    return out


def table_evidence(cases_by_L):
    out = {}
    for L, cases in sorted(cases_by_L.items()):
        row = {}
        for rname in ("standin", "strong"):
            r = rates(cases, lambda c: c[rname]["outcome"], "known", cluster=True)
            fk = defaultdict(list)
            ever_neg = [c for c in cases if not c["known"]]
            for c in cases:
                if c[rname]["first_k"] is not None:
                    fk[(c["known"], c[rname]["first_status"])].append(c[rname]["first_k"])
            def summ(v):
                v = sorted(v)
                return None if not v else {"n": len(v), "median": v[len(v) // 2],
                                           "p90": v[min(len(v) - 1, int(0.9 * len(v)))]}
            row[rname] = {
                "rates": r,
                "decided": wilson(sum(c[rname]["outcome"] != INS for c in cases), len(cases)),
                "first_k_to_DEMONSTRATED_knows": summ(fk[(True, model.SUPPORTED)]),
                "first_k_to_NOT_YET_not_knows": summ(fk[(False, model.NOT_SUPPORTED)]),
                "ever_demonstrated_not_knows": wilson(sum(c[rname]["ever_dem"] for c in ever_neg),
                                                      len(ever_neg)),
                "baseline_n_median": sorted(c[rname]["n0"] for c in cases)[len(cases) // 2],
            }
        for m in ("naive", "bkt_fitted_ALL", "bkt_fitted_INDEP", "bkt_oracle_INDEP",
                  "bkt_fitted_INDEP_3way"):
            row[m] = rates(cases, decider(m), "known", cluster=True)
        out[L] = row
    return out


def table_misestimated(cases_by_L):
    out = {}
    for L, cases in sorted(cases_by_L.items()):
        out[L] = {}
        nothing = [c for c in cases if not c["known"] and not c["known_at_start"]]
        below = [c for c in cases if not c["known"]]
        knows = [c for c in cases if c["known"]]
        for pname in PERTURB:
            r = {}
            for m in ("selected", "pre_post", "posterior_only", "bf_only"):
                r[m] = {
                    "false_dem_learned_nothing": wilson(
                        sum(c[pname]["approaches"][m] == DEM for c in nothing), len(nothing)),
                    "false_dem_below_target": wilson(
                        sum(c[pname]["approaches"][m] == DEM for c in below), len(below)),
                    "miss_knows": wilson(
                        sum(c[pname]["approaches"][m] != DEM for c in knows), len(knows))}
            r["bkt_seeded"] = {
                "false_dem_learned_nothing": wilson(
                    sum(c[pname]["bkt_seeded"] == DEM for c in nothing), len(nothing)),
                "false_dem_below_target": wilson(
                    sum(c[pname]["bkt_seeded"] == DEM for c in below), len(below)),
                "miss_knows": wilson(sum(c[pname]["bkt_seeded"] != DEM for c in knows), len(knows))}
            a, b = PERTURB[pname]
            r["baseline"] = {"alpha": a, "beta": b, "mu0": a / (a + b), "n": a + b}
            out[L][pname] = r
    return out


def contaminated_verdicts(run_dir, calib):
    """Every case evaluated again on streams with five injected answers per case."""
    run = A.load_run(run_dir, calib)
    ls = A.standin_for(run)       # Learner State sees the clean stream; the verdict sees all
    out = {}
    for variant, credit in (("tempting_correct", 1.0), ("damning_wrong", 0.0)):
        rows = []
        for lid in sorted(run):
            L = run[lid]
            answers, shown, injected = contaminate(L, credit)
            for cid in sorted(L["interventions"]):
                iv = L["interventions"][cid]
                as_of = L["as_of"][cid]
                v = engine.evaluate(iv, ls, answers, shown, as_of)
                inj = [(injected[j.record_id], j.exclusion) for j in v.answers
                       if j.record_id in injected]
                credits = [a.credit for a in answers
                           if a.concept_id == cid and a.occurred_at <= as_of]
                rows.append({"key": (lid, cid), "outcome": v.outcome.value, "p": v.p_target,
                             "bf": v.bayes_factor, "injected": inj,
                             "naive": DEM if B.naive_three_of_last_four(credits) else NOT})
        out[variant] = rows
    return out


def table_contamination(contam, clean_cases):
    clean = {(c["learner_id"], c["concept_id"]): c for c in clean_cases}
    out = {}
    for variant, rows in contam.items():
        same = 0
        reasons, flips = Counter(), Counter()
        wrong_reason = 0
        for r in rows:
            c = clean[tuple(r["key"])]
            same += (r["outcome"] == c["standin"]["outcome"] and r["p"] == c["standin"]["p"]
                     and r["bf"] == c["standin"]["bf"])
            for kind, excl in r["injected"]:
                reasons[(kind, excl)] += 1
                wrong_reason += excl != EXPECTED[kind]
            flips[(c["naive"], r["naive"])] += 1
        out[variant] = {"cases": len(rows), "verdict_identical": same,
                        "injected_reasons": {f"{k[0]}->{k[1]}": v for k, v in sorted(reasons.items())},
                        "injected_with_unexpected_reason": wrong_reason,
                        "naive_rule_clean_to_contaminated": {f"{a}->{b}": n for (a, b), n
                                                             in sorted(flips.items())}}
    return out


def _job(job):
    kind, L, run_dir, calib, fitted = job
    if kind == "run":
        return evaluate_run(Path(run_dir), calib, fitted,
                            extra_readers=PERTURB if L in (3, 8) else None)[2]
    return contaminated_verdicts(Path(run_dir), calib)


def baseline_summary(cases):
    by = defaultdict(list)
    for c in cases:
        by[c["population"]].append(c["standin"]["mu0"])
    return {p: {"n": len(v), "mu0_median": sorted(v)[len(v) // 2],
                "mu0_min": min(v), "mu0_max": max(v)} for p, v in sorted(by.items())}


def exclusion_counts(cases):
    tot = Counter()
    for c in cases:
        tot.update(c["exclusions"])
    return dict(sorted(tot.items()))


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_digest():
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for p in sorted(list((root / "verdict").glob("*.py")) + list((root / "harness").glob("*.py"))
                    + list((root / "simulator").glob("*.py"))):
        h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="runs/scrum94")
    ap.add_argument("--calib", default="calib-9400")
    a = ap.parse_args()
    runs, out = Path(a.runs), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    calib_dir = runs / a.calib
    calib = A.load_calibration(calib_dir / "calibration.json")
    fitted = fit_on_calibration(calib_dir, calib)
    print("fitted BKT:", {m: {k: round(v, 4) for k, v in f.items()} for m, f in fitted.items()})

    dirs = {L: runs / ("seed-93" if L == 3 else f"seed-93-L{L}") for L in LENGTHS}
    jobs = [("run", L, str(dirs[L]), calib, fitted) for L in LENGTHS]

    # calibration entries for the injected fresh items (so only the intended rule excludes)
    cal_inj = dict(calib)
    run3 = A.load_run(dirs[3], calib)
    for L_ in run3.values():
        for cid in L_["interventions"]:
            for kind in ("HELP", "SHOWN", "NOSRC"):
                cal_inj[f"FRESH-{kind}-{cid[:8]}"] = (FRESH_B, FRESH_SE)
    jobs += [("contaminate", L, str(dirs[L]), cal_inj, fitted) for L in (3, 8)]
    workers = max(1, min(len(jobs), os.cpu_count() or 1))
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        done = pool.map(_job, jobs, chunksize=1)        # results come back in job order
    cases_by_L = {L: r for (kind, L, *_), r in zip(jobs, done) if kind == "run"}
    contam = {L: r for (kind, L, *_), r in zip(jobs, done) if kind == "contaminate"}
    for L in LENGTHS:
        print(f"L={L}: {len(cases_by_L[L])} cases evaluated")

    results = {
        "about": "SCRUM-94 validation - SIMULATION RESULT, generated by harness/validate94.py",
        "fitted_bkt": fitted,
        "main_L3": table_main(cases_by_L[3]),
        "main_L8": table_main(cases_by_L[8]),
        "exclusions_L3": exclusion_counts(cases_by_L[3]),
        "evidence_needed": table_evidence(cases_by_L),
        "misestimated": table_misestimated({3: cases_by_L[3], 8: cases_by_L[8]}),
        "baseline_summary_L3": baseline_summary(cases_by_L[3]),
        "contamination_L3": table_contamination(contam[3], cases_by_L[3]),
        "contamination_L8": table_contamination(contam[8], cases_by_L[8]),
        "determinism": {"verdict_input_sha_L3": hashlib.sha256(
            "".join(c["sha"] for c in cases_by_L[3]).encode()).hexdigest()},
    }
    # The cross-machine digest covers the DECISIONS: outcome and number of counted answers
    # per case. P and BF agree across machines only to ~1e-15 (C math libraries differ in
    # their last bits - measured between the cloud workspace and a Mac), so any digest of
    # them, even rounded, can flip on a value that sits on a rounding boundary.
    verdicts = hashlib.sha256(json.dumps(
        [(L, c["learner_id"], c["concept_id"], c["standin"]["outcome"],
          c["standin"]["n_counted"]) for L in LENGTHS for c in cases_by_L[L]]).encode()).hexdigest()
    results["determinism"]["verdicts_sha"] = verdicts
    manifest = {"inputs": {str(d): sha_file(d / "answers.jsonl") for d in dirs.values()},
                "calibration": sha_file(calib_dir / "calibration.json"),
                "code_sha256": code_digest(), "verdicts_sha256": verdicts}
    results["manifest"] = manifest
    (out / "results.json").write_text(json.dumps(results, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
    with open(out / "cases_L3.jsonl", "w", encoding="utf-8") as f:
        for c in cases_by_L[3]:
            f.write(json.dumps(c, sort_keys=True) + "\n")
    from harness.report94 import render
    (out / "results.md").write_text(render(results), encoding="utf-8")
    print(f"verdicts sha256 {verdicts[:16]}...  -> {out}/results.md")


if __name__ == "__main__":
    main()
