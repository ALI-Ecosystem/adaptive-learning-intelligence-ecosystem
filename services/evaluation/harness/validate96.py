"""SCRUM-96 validation: retention, near transfer and error repetition on simulated learners.

    python -m harness.validate96 --run runs/seed-96 --calib runs/calib-9600 --out runs/scrum96

Unit: one (learner, concept) case, followed from the treatment end to the study end (a week
after the learner's last record). Every version is kept; the FINAL version is scored.

Truth (scoring side only, from truth.jsonl), using the same rule order as the table:
    K1, D1, M1  known / depth / misconception when the immediate post-test began
    observed    the delayed test reached the system (ALE stand-in) AND began at or after t_R
    K2, D2      known / depth when the delayed test began
    NOT_YET     not K1 and not (observed and K2)
    NOT_RETAINED  K1 and observed and not K2
    PERSISTS    shown (K1, or observed K2) and the misconception is still held then
    SHALLOW     shown and the depth is PATTERN
    RETAINED    observed and K2
    DEMONSTRATED  K1
The truth of a dimension is about what the learner IS; the evaluator sees only answers, so a
measured rate is the share of cases where the final outcome equals the truth outcome, and
the question each population asks is scored on its own (the task's validation list).

Baselines on the same answers, no uncertainty:
    naive retention   delayed test: half or more correct -> RETAINED, else NOT_RETAINED -
                      with no earlier success required (the trap of the task)
    naive repetition  the misconception's option picked twice or more in ANY answer after the
                      intervention, practice included (the other trap)

Variants:
    main      error repetition with the prior and targets chosen (decision 3d), on the
              windows where the target was shown
    oracle    the same, but WHICH misconceptions are known comes from the truth (decision 3c:
              an upper bound, never the result)
    all-windows  error repetition reading every window (shows why the scope rule exists)

Every rate has its sample size, a 95% Wilson interval and a 95% bootstrap interval over
LEARNERS (a learner's three concepts are not independent).
"""
import argparse
import hashlib
import json
import multiprocessing
import os
from collections import Counter, defaultdict
from pathlib import Path

from harness import adapter94 as A
from harness import adapter96 as A6
from harness.validate94 import cluster_ci, wilson
from outcome import engine as E
from outcome.misconception import AnswerBuiltMisconceptions, option_map
from simulator.concepts import CONCEPTS

# decision 3d option A: the prior is Learner State's misconception state at delivery, every
# known misconception is tested; decision on finding 1: only the windows where the target was
# shown. The other variants are reported for comparison, never as the result.
MAIN = {"err_scope": "SHOWN_WINDOWS", "err_prior": "STATE", "err_targets": "ALL_KNOWN"}
VARIANTS = {"main": MAIN,
            "oracle": dict(MAIN),
            "all_windows": dict(MAIN, err_scope="ALL"),
            "neutral_prior": dict(MAIN, err_prior="NEUTRAL"),
            "neutral_most_active": dict(MAIN, err_prior="NEUTRAL", err_targets="MOST_ACTIVE")}
EXPECTED = {   # the task's validation list: population -> the outcome it should reach
    "LEARNS": E.RETAINED, "CONFIDENT_RIGHT": E.RETAINED,
    "LEARNS_THEN_FORGETS": E.NOT_RETAINED, "DOES_NOT_LEARN": E.NOT_YET,
    "LEARNS_PATTERN": E.SHALLOW, "ERRORS_THEN_LEARNS": E.RETAINED,
    "CONFIDENT_WRONG": E.NOT_YET, "LEARNS_PARTIALLY": None, "HOLDS_MISCONCEPTION": None}

_W = {}


class FixedKnownMisconceptions:
    """SCORING SIDE ONLY (the upper bound of decision 3c): the same Beta from the answers,
    but WHICH misconceptions are known comes from a given set (the simulator's truth)."""
    SOURCE = "misconception-oracle(truth decides which are known)"

    def __init__(self, inner, known: dict):
        self.inner, self.known = inner, known       # {(learner_id, concept_id): {mid, ...}}

    def state(self, learner_id, concept_id, answers, as_of):
        st = self.inner.state(learner_id, concept_id, answers, as_of)
        held = self.known.get((learner_id, concept_id), set())
        return {m: (a, b, m in held) for m, (a, b, _) in st.items()}


def _init(run_dir, calib_path):
    calib = A.load_calibration(calib_path)
    run = A6.load_run96(run_dir, calib)
    items = A6.load_items(run_dir)
    imap = option_map(items)
    cm = A6.concept_misconceptions(items, {c.source_id: c.concept_id for c in CONCEPTS})
    truth = A6.load_truth96(run_dir)
    mr = AnswerBuiltMisconceptions(cm, imap)
    held = {}
    for (lid, cid), t in truth.items():
        # the oracle: the misconception held when the intervention was delivered (truth)
        held[(lid, cid)] = {t["mis_start"]} if t["mis_start"] else set()
    _W.update(run=run, ls=A6.standin_for96(run), imap=imap, mr=mr,
              oracle=FixedKnownMisconceptions(mr, held))


def _case(L, cid, variant):
    opts = VARIANTS[variant]
    mr = _W["oracle"] if variant == "oracle" else _W["mr"]
    return E.Case(L["interventions"][cid], _W["ls"], mr, L["answers"], [], L["meta"],
                  _W["imap"], L["horizon"], **opts)


def _job(lid):
    L = _W["run"][lid]
    out = []
    for cid in sorted(L["interventions"]):
        row = {"learner_id": lid, "concept_id": cid, "never_checked": L["never_checked"]}
        for v in VARIANTS:
            r = E.run_case(_case(L, cid, v))
            f = r.final
            row[v] = {"outcome": f["outcome"], "rule": str(f["rule"]),
                      "confidence": f["confidence"],
                      "dims": {d: x["status"] for d, x in f["dimensions"].items()},
                      "n": {d: x["n"] for d, x in f["dimensions"].items()},
                      "err": f["error_repetition_status"],
                      "known_misconceptions": r.known_misconceptions,
                      "checks": {c["dimension"]: c["state"] for c in f["checks"]}}
            if v == "main":
                row.update(t_end=r.t_end, t_r=r.t_r, overdue_at=r.overdue_at,
                           versions=len(r.versions),
                           explanation=f["explanation"],
                           version_outcomes=[x["outcome"] for x in r.versions],
                           not_retained_ok=_not_retained_ok(r),
                           naive=_naive(L, cid, r))
        out.append(row)
    return out


def _not_retained_ok(r) -> bool:
    """Acceptance: NOT_RETAINED only after an EARLIER demonstrated success. Checked on the
    data, not only on the status (independent review: a status-only check cannot fail): in
    every version that says NOT_RETAINED, ACQUISITION is SUPPORTED, it rests on at least one
    observation, and every acquisition observation it used lies strictly before every
    retention observation, and before the retention point."""
    for v in r.versions:
        if v["outcome"] != E.NOT_RETAINED:
            continue
        if v["dimensions"][E.ACQ]["status"] != E.SUP or not v["dimensions"][E.ACQ]["n"]:
            return False
        acq = [t for _, t, d in r.observations if d == E.ACQ and t <= v["as_of"]]
        ret = [t for _, t, d in r.observations if d == E.RET and t <= v["as_of"]]
        if not acq or not ret or max(acq) >= min(ret) or max(acq) >= r.t_r:
            return False
    return True


def _naive(L, cid, r) -> dict:
    meta, imap = L["meta"], _W["imap"]
    mine = [a for a in L["answers"] if a.concept_id == cid]
    delayed = [a for a in mine if meta[a.record_id]["phase"] == "DELAYED_TEST"
               and meta[a.record_id].get("activity_type") is None]
    ret = None
    if delayed:
        ret = E.RETAINED if 2 * sum(a.credit for a in delayed) >= len(delayed) else E.NOT_RETAINED
    iv = L["interventions"][cid]
    picks = Counter()
    for a in mine:
        if a.occurred_at > iv.delivered_at and a.chosen_option:
            m = (imap.get(a.item_id) or {}).get(a.chosen_option)
            if m:
                picks[m] += 1
    return {"retention": ret, "repetition": any(v >= 2 for v in picks.values())}


# ---- truth ------------------------------------------------------------------------------------

def truth_outcome(t: dict, row: dict) -> dict:
    # "observed" = the retention check happened: the delayed test reached the system and
    # gave at least one counted answer at or after t_R (a test that straddles t_R counts -
    # independent review). The learner's state is the truth at the start of that test.
    observed = (not row["never_checked"]) and row["main"]["n"][E.RET] > 0
    k1, k2 = t["known_imm"], (t["known_del"] if observed else None)
    shown = k1 or bool(k2)
    if shown:
        mis = t["mis_imm"] if k1 else t["mis_del"]
        depth = t["depth_imm"] if k1 else t["depth_del"]
    else:
        mis, depth = None, None
    if not k1 and not (observed and k2):
        out = E.NOT_YET
    elif k1 and observed and not k2:
        out = E.NOT_RETAINED
    elif mis:
        out = E.PERSISTS
    elif depth == "PATTERN":
        out = E.SHALLOW
    elif observed and k2:
        out = E.RETAINED
    else:
        out = E.DEMONSTRATED
    return {"outcome": out, "observed": observed, "held": bool(mis), "pattern": depth == "PATTERN",
            "early": (not row["never_checked"]) and not observed,
            "late": observed and row["main"]["checks"][E.RET] == "RESOLVED_LATE"}


# ---- tables -----------------------------------------------------------------------------------

def rate(pairs) -> dict:
    """pairs: [(learner_id, hit)] -> Wilson + cluster bootstrap."""
    k, n = sum(h for _, h in pairs), len(pairs)
    w = wilson(k, n)
    if w is None:
        return {"k": 0, "n": 0}
    w["cluster"] = cluster_ci(pairs)
    return w


def fmt(r) -> str:
    if not r or not r.get("n"):
        return "n = 0"
    cl = r.get("cluster")
    cl_s = f"; learners [{cl[0]:.1%}, {cl[1]:.1%}]" if cl else ""
    return f"{r['p']:.1%} ({r['k']}/{r['n']}; 95% [{r['lo']:.1%}, {r['hi']:.1%}]{cl_s})"


def build(rows, truth) -> dict:
    res = {"populations": {}, "questions": {}, "coverage": {}, "variants": {}, "naive": {}}
    for row in rows:
        row["truth"] = truth_outcome(truth[(row["learner_id"], row["concept_id"])], row)
        row["population"] = truth[(row["learner_id"], row["concept_id"])]["population"]
    pops = sorted({r["population"] for r in rows})
    # outcome distribution per population (main)
    for p in pops:
        rs = [r for r in rows if r["population"] == p]
        dist = Counter(r["main"]["outcome"] for r in rs)
        res["populations"][p] = {
            "n": len(rs), "outcomes": dict(sorted(dist.items())),
            "expected": EXPECTED.get(p),
            "reaches_expected": rate([(r["learner_id"], int(r["main"]["outcome"] == EXPECTED[p]))
                                      for r in rs]) if EXPECTED.get(p) else None,
            "matches_truth": rate([(r["learner_id"], int(r["main"]["outcome"] == r["truth"]["outcome"]))
                                   for r in rs]),
            "truth_outcomes": dict(sorted(Counter(r["truth"]["outcome"] for r in rs).items()))}
    Q = res["questions"]
    sel = lambda f: [r for r in rows if f(r)]
    lid = lambda r: r["learner_id"]
    # retains / forgets, among cases whose retention check happened
    for p, want in (("LEARNS", E.RETAINED), ("CONFIDENT_RIGHT", E.RETAINED),
                    ("LEARNS_THEN_FORGETS", E.NOT_RETAINED)):
        rs = sel(lambda r: r["population"] == p and r["truth"]["observed"])
        Q[f"{p}: {want} (retention check happened)"] = rate([(lid(r), int(r["main"]["outcome"] == want)) for r in rs])
    rs = sel(lambda r: r["truth"]["observed"] and r["truth"]["outcome"] == E.NOT_RETAINED)
    Q["truly NOT_RETAINED -> NOT_RETAINED"] = rate([(lid(r), int(r["main"]["outcome"] == E.NOT_RETAINED)) for r in rs])
    rs = sel(lambda r: not truth[(r["learner_id"], r["concept_id"])]["known_imm"])
    Q["never learned (not known at the post-test) -> NOT_RETAINED (must be ~0)"] = rate(
        [(lid(r), int(r["main"]["outcome"] == E.NOT_RETAINED)) for r in rs])
    Q["  same, naive retention rule"] = rate(
        [(lid(r), int(r["naive"]["retention"] == E.NOT_RETAINED)) for r in rs])
    rs = sel(lambda r: r["population"] == "DOES_NOT_LEARN")
    Q["DOES_NOT_LEARN -> NOT_RETAINED"] = rate([(lid(r), int(r["main"]["outcome"] == E.NOT_RETAINED)) for r in rs])
    Q["  same, naive retention rule (delayed test reached)"] = rate(
        [(lid(r), int(r["naive"]["retention"] == E.NOT_RETAINED)) for r in rs if r["naive"]["retention"]])
    Q["NOT_RETAINED versions without an earlier SUPPORTED acquisition (must be 0)"] = {
        "k": sum(not r["not_retained_ok"] for r in rows), "n": len(rows)}
    # shallow
    rs = sel(lambda r: r["population"] == "LEARNS_PATTERN")
    Q["LEARNS_PATTERN -> SHALLOW"] = rate([(lid(r), int(r["main"]["outcome"] == E.SHALLOW)) for r in rs])
    rs = sel(lambda r: r["truth"]["outcome"] == E.SHALLOW)
    Q["truly SHALLOW -> SHALLOW"] = rate([(lid(r), int(r["main"]["outcome"] == E.SHALLOW)) for r in rs])
    rs = sel(lambda r: r["truth"]["outcome"] in (E.RETAINED, E.DEMONSTRATED))
    Q["truly the idea (RETAINED/DEMONSTRATED) -> SHALLOW (false)"] = rate(
        [(lid(r), int(r["main"]["outcome"] == E.SHALLOW)) for r in rs])
    # misconception
    for v in VARIANTS:
        V = res["variants"].setdefault(v, {})
        shown = lambda r: E.SUP in (r[v]["dims"][E.ACQ], r[v]["dims"][E.RET])
        rs = sel(lambda r: r["population"] == "HOLDS_MISCONCEPTION" and shown(r) and r["truth"]["held"])
        V["HOLDS_MISCONCEPTION, still held -> PERSISTS"] = rate([(lid(r), int(r[v]["outcome"] == E.PERSISTS)) for r in rs])
        rs = sel(lambda r: r["population"] == "HOLDS_MISCONCEPTION" and shown(r) and not r["truth"]["held"])
        V["HOLDS_MISCONCEPTION, repaired -> PERSISTS (false)"] = rate([(lid(r), int(r[v]["outcome"] == E.PERSISTS)) for r in rs])
        V["HOLDS_MISCONCEPTION, repaired -> repetition NOT_SUPPORTED"] = rate([(lid(r), int(r[v]["err"] == E.NOT)) for r in rs])
        rs = sel(lambda r: r["population"] == "ERRORS_THEN_LEARNS" and shown(r) and not r["truth"]["held"])
        V["ERRORS_THEN_LEARNS, learned -> PERSISTS (false)"] = rate([(lid(r), int(r[v]["outcome"] == E.PERSISTS)) for r in rs])
        rs = sel(lambda r: shown(r) and not r["truth"]["held"])
        V["all shown, not held -> PERSISTS (false)"] = rate([(lid(r), int(r[v]["outcome"] == E.PERSISTS)) for r in rs])
        rs = sel(lambda r: shown(r) and r["truth"]["held"])
        V["all shown, held -> PERSISTS"] = rate([(lid(r), int(r[v]["outcome"] == E.PERSISTS)) for r in rs])
    N = res["naive"]
    rs = sel(lambda r: r["population"] == "ERRORS_THEN_LEARNS" and not r["truth"]["held"]
             and r["truth"]["outcome"] != E.NOT_YET)
    N["ERRORS_THEN_LEARNS, learned -> naive repetition flag (false)"] = rate([(lid(r), int(r["naive"]["repetition"])) for r in rs])
    N["  same, main -> PERSISTS (false)"] = rate([(lid(r), int(r["main"]["outcome"] == E.PERSISTS)) for r in rs])
    rs = sel(lambda r: r["population"] == "HOLDS_MISCONCEPTION" and r["truth"]["held"])
    N["HOLDS_MISCONCEPTION, held -> naive repetition flag"] = rate([(lid(r), int(r["naive"]["repetition"])) for r in rs])
    # coverage
    C = res["coverage"]
    for d in (E.ACQ, E.RET, E.TRF, E.ERR):
        states = Counter(r["main"]["checks"].get(d, "NOT_APPLICABLE") for r in rows)
        C[d] = {s: rate([(lid(r), int(r["main"]["checks"].get(d, "NOT_APPLICABLE") == s)) for r in rows])
                for s in sorted(states)}
    C["delayed check: never (ALE stand-in)"] = rate([(lid(r), int(r["never_checked"])) for r in rows])
    C["delayed check: before t_R (counted as acquisition)"] = rate([(lid(r), int(r["truth"]["early"])) for r in rows])
    C["delayed check: on time (t_R .. 2 t_R)"] = rate(
        [(lid(r), int(r["truth"]["observed"] and not r["truth"]["late"])) for r in rows])
    C["delayed check: late (after 2 t_R)"] = rate([(lid(r), int(r["truth"]["late"])) for r in rows])
    rs = sel(lambda r: r["never_checked"])
    C["never checked -> outcome with RETENTION (must be 0)"] = rate(
        [(lid(r), int(r["main"]["outcome"] in (E.RETAINED, E.NOT_RETAINED))) for r in rs])
    C["never checked -> RETENTION check OVERDUE at the study end"] = rate(
        [(lid(r), int(r["main"]["checks"][E.RET] == E.OVERDUE)) for r in rs])
    # explanation (reported only)
    ex = defaultdict(list)
    for r in rows:
        g = r["explanation"]["mean_grade"]
        if g is not None:
            ex[r["truth"]["outcome"]].append(g)
    res["explanation"] = {k: {"n": len(v), "mean_grade": round(sum(v) / len(v), 3)}
                          for k, v in sorted(ex.items())}
    vs = [r["versions"] for r in rows]
    res["versions"] = {"cases": len(rows), "mean": round(sum(vs) / len(vs), 2),
                       "min": min(vs), "max": max(vs),
                       "outcome_changes_mean": round(sum(
                           sum(1 for a, b in zip(r["version_outcomes"], r["version_outcomes"][1:]) if a != b)
                           for r in rows) / len(rows), 2)}
    return res


def write_md(res, path, meta):
    L = ["# SCRUM-96 results (generated - do not edit)", "",
         f"Run `{meta['run']}`, calibration `{meta['calib']}`; {meta['cases']} cases "
         f"({meta['learners']} learners x 3 concepts). Simulation only.", "",
         "## Outcome per population (main)", "",
         "| population | n | expected | reaches expected | final = truth | outcomes |",
         "|---|---|---|---|---|---|"]
    for p, x in res["populations"].items():
        L.append(f"| {p} | {x['n']} | {x['expected'] or '-'} | "
                 f"{fmt(x['reaches_expected']) if x['reaches_expected'] else '-'} | "
                 f"{fmt(x['matches_truth'])} | "
                 + ", ".join(f"{k} {v}" for k, v in x["outcomes"].items()) + " |")
    for title, key in (("The task's questions", "questions"), ("Naive baselines", "naive")):
        L += ["", f"## {title}", "", "| question | rate |", "|---|---|"]
        for q, r in res[key].items():
            L.append(f"| {q} | {fmt(r) if 'p' in (r or {}) or not r.get('n') else str(r['k']) + '/' + str(r['n'])} |")
    L += ["", "## Error repetition: variants", ""]
    names = list(res["variants"])
    L.append("| question | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for q in res["variants"]["main"]:
        L.append(f"| {q} | " + " | ".join(fmt(res["variants"][v][q]) for v in names) + " |")
    L += ["", "## Coverage", "", "| check | state | share |", "|---|---|---|"]
    for d, x in res["coverage"].items():
        if isinstance(x, dict) and "p" not in x and "n" not in x:
            for s, r in x.items():
                L.append(f"| {d} | {s} | {fmt(r)} |")
        else:
            L.append(f"| {d} | | {fmt(x)} |")
    L += ["", "## Explanation grade by true outcome (reported only)", "",
          "| true outcome | n | mean grade |", "|---|---|---|"]
    for k, v in res["explanation"].items():
        L.append(f"| {k} | {v['n']} | {v['mean_grade']} |")
    v = res["versions"]
    L += ["", f"Versions: {v['cases']} cases, mean {v['mean']} versions (min {v['min']}, "
          f"max {v['max']}); the outcome changed {v['outcome_changes_mean']} times on average. "
          "Every version is kept.", ""]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def code_digest() -> str:
    h = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for d in ("outcome", "verdict", "harness", "simulator"):
        for p in sorted((root / d).glob("*.py")):
            h.update(f"{d}/{p.name}".encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/seed-96")
    ap.add_argument("--calib", default="runs/calib-9600")
    ap.add_argument("--out", default="runs/scrum96")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    calib_path = str(Path(a.calib) / "calibration.json")
    _init(a.run, calib_path)
    lids = sorted(_W["run"])
    with multiprocessing.get_context("spawn").Pool(
            a.workers, initializer=_init, initargs=(a.run, calib_path)) as pool:
        rows = [r for part in pool.map(_job, lids, chunksize=8) for r in part]
    truth = A6.load_truth96(a.run)
    res = build(rows, truth)
    meta = {"run": a.run, "calib": a.calib, "cases": len(rows), "learners": len(lids),
            "variants": VARIANTS, "never_share": A6.NEVER_SHARE,
            "inputs_sha256": {"answers.jsonl": sha_file(Path(a.run) / "answers.jsonl"),
                              "calibration.json": sha_file(calib_path)},
            "code_sha256": code_digest()}
    res["meta"] = meta
    (out / "results.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n",
                                      encoding="utf-8")
    with open(out / "cases.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    write_md(res, out / "results.md", meta)
    print(f"{len(rows)} cases -> {out}/results.md")


if __name__ == "__main__":
    main()
