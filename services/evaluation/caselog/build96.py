"""Cases of the SCRUM-96 run: one (learner, concept) followed from the treatment end to the
study end; the FINAL version is the one compared with the truth (as in validate96).
The chain: truth -> answers (counted into a dimension / excluded / never delivered) ->
acquisition (= the SCRUM-94 verdict over time) -> retention / transfer / error repetition
-> outcome table -> labels."""
from pathlib import Path

from harness import adapter94 as A
from harness import adapter96 as A6
from harness.validate96 import MAIN, truth_outcome
from outcome import engine as E
from outcome.misconception import AnswerBuiltMisconceptions, carries, chose, option_map
from simulator.concepts import CONCEPTS

from . import spec as S
from .build94 import load_trace
from .common import false_claims, finish_dim, label, row

FAM = {E.ACQ: "ACQUISITION", E.RET: "RETENTION", E.TRF: "TRANSFER"}


def build(root=".", details=None):
    cfg = S.RUNS["R96"]
    run_dir, calib_dir = Path(root) / cfg["run"], Path(root) / cfg["calib"]
    calib = A.load_calibration(calib_dir / "calibration.json")
    run = A6.load_run96(run_dir, calib)
    items = A6.load_items(run_dir)
    imap = option_map(items)
    cm = A6.concept_misconceptions(items, {c.source_id: c.concept_id for c in CONCEPTS})
    mr = AnswerBuiltMisconceptions(cm, imap)
    ls = A6.standin_for96(run)
    truth = A6.load_truth96(run_dir)
    trace = load_trace(run_dir)
    cases = []
    for lid in sorted(run):
        L, T = run[lid], trace[lid]
        for cid in sorted(L["interventions"]):
            case_id = f"R96-{lid[:8]}-{cid[:8]}"
            if details is not None and case_id not in details:
                continue
            c = E.Case(L["interventions"][cid], ls, mr, L["answers"], [], L["meta"], imap,
                       L["horizon"], **MAIN)
            r = E.run_case(c)
            f = r.final
            t = truth[(lid, cid)]
            vrow = {"never_checked": L["never_checked"],
                    "main": {"n": {d: x["n"] for d, x in f["dimensions"].items()},
                             "checks": {k["dimension"]: k["state"] for k in f["checks"]}}}
            to = truth_outcome(t, vrow)
            by_id = {a.record_id: a for a in L["all_answers"]}
            obs = {rid: d for rid, _, d in r.observations}
            rows = []
            for a in sorted(L["all_answers"], key=lambda a: (a.occurred_at, a.record_id)):
                if a.concept_id != cid:
                    continue
                meta = L["meta"][a.record_id]
                tr = T["rows"].get(a.record_id)
                if a.record_id not in obs:
                    rows.append(row(a, meta, tr, "NOT_DELIVERED",
                                    "ALE stand-in: the delayed check never happened", None))
                    continue
                d = obs[a.record_id]
                if d in (E.ACQ, E.RET, E.TRF, E.EXP):
                    rows.append(row(a, meta, tr, "COUNTED", None, d))
                else:
                    rows.append(row(a, meta, tr, "EXCLUDED", d, None))
            ctx = {"check_withheld": L["never_checked"]}
            dims = []
            for d in (E.ACQ, E.RET, E.TRF):
                x = f["dimensions"][d]
                used = [w for w in rows if w["dimension"] == d]
                if d == E.ACQ:
                    late = any(w["phase"] == "DELAYED_TEST" for w in used)
                    tv = (S.NOT_SCORABLE if late and t["known_imm"] != t["known_del"]
                          else t["known_imm"])
                elif d == E.RET:
                    tv = t["known_del"]
                else:
                    idea_i = t["known_imm"] and t["depth_imm"] == "IDEA"
                    idea_d = t["known_del"] and t["depth_del"] == "IDEA"
                    late = any(w["phase"] == "DELAYED_TEST" for w in used)
                    tv = S.NOT_SCORABLE if late and idea_i != idea_d else idea_i
                dims.append(finish_dim({"name": FAM[d], "family": FAM[d], "round": None,
                                        "output": x["status"], "truth": tv, "n": x["n"],
                                        "p": x["p"], "bayes_factor": x["bayes_factor"]},
                                       used, ctx))
            if f["error_repetition_status"] != E.NA:
                reps = f["error_repetition"]
                wins = set(next(iter(reps.values()))["windows"]) if reps else set()
                st = f["error_repetition_status"]
                # the misconception(s) that decided the status (SUPPORTED: any one suffices)
                dec = sorted(m for m, v in reps.items() if v["status"] == st) or sorted(reps)
                used = [w for w in rows if w["dimension"] in wins and w["activity_type"] is None
                        and any(carries(imap, w["item_id"], m) for m in dec)]
                for w in used:
                    w["mis_pick"] = any(chose(imap, w["item_id"], w["chosen_option"], m)
                                        for m in dec)
                n = len(used)
                dims.append(finish_dim({"name": "ERROR_REPETITION", "family": "ERROR_REPETITION",
                                        "round": None, "output": f["error_repetition_status"],
                                        "truth": to["held"], "n": n, "deciding": dec,
                                        "misconceptions": {m: {"n": v["n"], "picks": v["picks"],
                                                               "status": v["status"]}
                                                           for m, v in sorted(reps.items())}},
                                       used, ctx))
            k1, k2, obsd = t["known_imm"], t["known_del"], to["observed"]
            facts = {"shown": bool(k1 or (obsd and k2)), "not_shown": not (k1 or (obsd and k2)),
                     "lost": bool(k1 and obsd and not k2), "retained": bool(obsd and k2),
                     "misconception": to["held"], "pattern": to["pattern"]}
            fc = (false_claims(f["outcome"], facts) if f["outcome"] in S.OUTCOME_CLAIMS else [])
            wins = {w for c_ in fc for w in S.CLAIM_WINDOWS[c_]} or {E.ACQ, E.RET, E.TRF}
            used = [w for w in rows if w["dimension"] in wins]
            dims.append(finish_dim({"name": "OUTCOME", "family": "OUTCOME", "round": None,
                                    "output": f["outcome"],
                                    "truth": {"outcome": to["outcome"], "facts": facts},
                                    "n": len(used), "rule": str(f["rule"]),
                                    "confidence": f["confidence"]}, used,
                                   dict(ctx, sub_dims=list(dims))))
            case = {
                "format": S.FORMAT, "case_id": case_id, "run": "R96",
                "learner_id": lid, "concept_id": cid, "population": t["population"],
                "truth": {"knows_at_post_test": t["known_imm"], "depth_at_post_test": t["depth_imm"],
                          "misconception_at_post_test": t["mis_imm"],
                          "knows_at_delayed_test": t["known_del"],
                          "depth_at_delayed_test": t["depth_del"],
                          "misconception_at_delayed_test": t["mis_del"],
                          "retention_check_happened": to["observed"],
                          "misconception_at_delivery": t["mis_start"],
                          "learned_due_to_intervention": t["learned"],
                          "known_before_intervention": t["known_at_start"],
                          "outcome": to["outcome"]},
                "stages": {
                    "learner_state": {"status": "STAND_IN"},
                    "verdict": {"as": "ACQUISITION dimension of the final version",
                                "status": f["dimensions"][E.ACQ]["status"],
                                "n": f["dimensions"][E.ACQ]["n"]},
                    "outcome96": {"outcome": f["outcome"], "rule": str(f["rule"]),
                                  "confidence": f["confidence"], "versions": len(r.versions),
                                  "version_outcomes": [v["outcome"] for v in r.versions],
                                  "t_end": r.t_end, "t_r": r.t_r, "overdue_at": r.overdue_at,
                                  "checks": vrow["main"]["checks"],
                                  "known_misconceptions": r.known_misconceptions,
                                  "explanation": f["explanation"]},
                    "gap95": S.NOT_RUN,
                    "adaptation": {"status": "ALE_STAND_IN", "delayed_check_never_happened":
                                   L["never_checked"]},
                    "diagnosis": S.NOT_BUILT},
                "dimensions": dims,
            }
            if details is not None and any(d["label"] == S.WRONG for d in dims):
                # counterfactual (robustness check of the attribution, never a label): the same
                # case with the delayed-test answers that fell BEFORE t_R removed - the window
                # replay of the INTERACTION "state changed inside the window" trigger
                early = {a.record_id for a in L["answers"] if a.concept_id == cid
                         and L["meta"][a.record_id]["phase"] == "DELAYED_TEST"
                         and a.occurred_at < r.t_r}
                cf = None
                if early:
                    c2 = E.Case(L["interventions"][cid], ls, mr,
                                [a for a in L["answers"] if a.record_id not in early], [],
                                L["meta"], imap, L["horizon"], **MAIN)
                    cf = E.run_case(c2).final
                for d in dims:
                    if d["label"] != S.WRONG:
                        continue
                    if cf is None:
                        d["counterfactual"] = {"window_replay": "NOT_AVAILABLE (no early answer)"}
                        continue
                    if d["family"] == "OUTCOME":
                        out2, n2 = cf["outcome"], d["n"]
                    elif d["family"] == "ERROR_REPETITION":
                        out2 = cf["error_repetition_status"]
                        n2 = sum(v["n"] for v in cf["error_repetition"].values())
                    else:
                        k = {v: k for k, v in FAM.items()}[d["family"]]
                        out2, n2 = cf["dimensions"][k]["status"], cf["dimensions"][k]["n"]
                    d["counterfactual"] = {"window_replay": {
                        "removed_early_delayed_answers": len(early), "output": out2,
                        "label": label(d["family"], out2, d["truth"], n2)}}
            if details is not None:
                case["answers"] = [w for w in rows if w["phase"] != "PRACTICE"
                                   or w["disposition"] == "COUNTED"]
                case["practice_answers"] = sum(1 for w in rows if w["phase"] == "PRACTICE")
                case["intervention_delivered_at"] = L["interventions"][cid].delivered_at
            cases.append(case)
    return cases
