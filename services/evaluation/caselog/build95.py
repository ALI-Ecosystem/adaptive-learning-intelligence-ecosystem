"""Cases of the SCRUM-95 run: one (learner, concept) over three rounds. The chain: truth ->
answers per round (unaided / assisted / excluded) -> each round's verdict -> assisted gap
and its reduction -> confidence gap and its reduction -> labels."""
from pathlib import Path

from gap import assisted as G
from gap import confidence as C
from gap.confnorm import load as load_norm
from harness import adapter94 as A
from harness import adapter95 as A5
from harness.validate95c import truth_class
from verdict import engine
from verdict.contracts import Exclusion

from . import spec as S
from .build94 import load_trace
from .common import finish_dim, label, row


def dispositions(L: dict, cid: str, reader) -> dict:
    """record_id -> (round, disposition, reason): the same sorting as adapter95.round_inputs,
    kept per record so the case can show every answer (checked against it in build())."""
    answers = L["answers"]
    by_id = {a.record_id: a for a in answers}
    first = {}
    for a in answers:
        first.setdefault(a.item_id, (a.occurred_at, a.record_id))
    out = {}
    for rd in L["rounds"][cid]:
        iv, as_of = rd["iv"], rd["as_of"]
        v = engine.evaluate(iv, reader, answers, [], as_of)
        t_end = engine.treatment_end(iv, answers, as_of)
        for j in v.answers:
            if j.counted:
                out[j.record_id] = (rd["round"], "COUNTED", None)
                continue
            if not (t_end < j.occurred_at <= as_of):
                out.setdefault(j.record_id, (None, "EXCLUDED", j.exclusion))
                continue
            a = by_id[j.record_id]
            if j.exclusion == Exclusion.ASSISTED.value:
                also = [n for n, bad in (
                    (Exclusion.NOT_FIRST_ATTEMPT.value, a.attempt_number != 1),
                    (Exclusion.ITEM_SEEN_BEFORE.value,
                     first[a.item_id] < (a.occurred_at, a.record_id)),
                    (Exclusion.ITEM_FLAGGED.value, a.item_flagged)) if bad]
                out[j.record_id] = ((rd["round"], "EXCLUDED", "ASSISTED+" + "+".join(also))
                                    if also else (rd["round"], "ASSISTED", None))
            else:
                out[j.record_id] = (rd["round"], "EXCLUDED", j.exclusion)
    return out


def build(root=".", details=None):
    cfg = S.RUNS["R95"]
    run_dir, calib_dir = Path(root) / cfg["run"], Path(root) / cfg["calib"]
    calib = A.load_calibration(calib_dir / "calibration.json")
    run = A5.load_run95(run_dir, calib)
    ls = A.standin_for(run)
    truth = A5.load_truth95(run_dir)
    norm, clean = load_norm(Path(root) / cfg["norm"]), load_norm(Path(root) / cfg["clean_norm"])
    trace = load_trace(run_dir)
    cases = []
    for lid in sorted(run):
        L, T = run[lid], trace[lid]
        for cid in sorted(L["rounds"]):
            case_id = f"R95-{lid[:8]}-{cid[:8]}"
            if details is not None and case_id not in details:
                continue
            tr = truth[(lid, cid)]
            ris = sorted(A5.round_inputs(L, cid, ls), key=lambda r: r.round)
            disp = dispositions(L, cid, ls)
            by_id = {a.record_id: a for a in L["answers"]}
            rows = []
            for a in L["answers"]:
                if a.concept_id != cid or a.record_id not in disp:
                    continue
                rnd, dsp, why = disp[a.record_id]
                t_row = T["rows"].get(a.record_id) or {}
                meta = {"phase": L["phase"][a.record_id],
                        "round": t_row.get("round") if rnd is None else rnd,
                        "confidence": L["confidence"].get(a.record_id)}
                rows.append(row(a, meta, t_row or None, dsp, why, None))
            for ri in ris:      # the per-record sorting must give exactly the measure's input
                u = tuple(by_id[r["record_id"]].credit for r in rows
                          if r["round"] == ri.round and r["disposition"] == "COUNTED")
                s = tuple(by_id[r["record_id"]].credit for r in rows
                          if r["round"] == ri.round and r["disposition"] == "ASSISTED")
                assert u == ri.unaided and s == ri.assisted, f"{case_id} round {ri.round}"
            m = G.measure(lid, cid, ris)
            dims = []

            def rws(r, kinds):
                return [w for w in rows if w["round"] == r and w["disposition"] in kinds]
            for ri in ris:
                used = rws(ri.round, ("COUNTED",))
                dims.append(finish_dim({"name": f"VERDICT@r{ri.round}", "family": "VERDICT",
                                        "round": ri.round, "output": ri.verdict,
                                        "truth": tr["rounds"][ri.round]["known"],
                                        "n": len(used)}, used, {}))
            for ri, mr in zip(ris, m["rounds"]):
                used = rws(ri.round, ("COUNTED", "ASSISTED"))
                tg = tr["rounds"][ri.round]["true_gap"]
                dims.append(finish_dim({"name": f"ASSISTED_GAP@r{ri.round}",
                                        "family": "ASSISTED_GAP", "round": ri.round,
                                        "output": mr["gap"]["status"],
                                        "truth": tg > G.GAP_THRESHOLD, "true_gap": tg,
                                        "gap_mean": mr["gap"]["mean"], "n": len(used),
                                        "p_above": mr["gap"]["p_above_threshold"]}, used, {}))
            r1, r3 = ris[0].round, ris[-1].round
            true_red = tr["rounds"][r1]["true_gap"] - tr["rounds"][r3]["true_gap"]
            used = rws(r1, ("COUNTED", "ASSISTED")) + rws(r3, ("COUNTED", "ASSISTED"))
            dims.append(finish_dim({"name": "ASSISTED_REDUCTION", "family": "ASSISTED_REDUCTION",
                                    "round": None, "output": m["reduction"]["status"],
                                    "truth": true_red > G.REDUCTION_THRESHOLD,
                                    "true_reduction": true_red, "n": len(used),
                                    "status_path": m["reduction"]["status_path"]}, used, {}))
            conf = L["confidence"]
            crs = [C.ConfRound(ri.round, tuple((cr, conf[rid]) for cr, rid in
                                               zip(ri.unaided, ri.unaided_records)))
                   for ri in ris]
            cm = C.measure(lid, cid, crs, norm)
            tgc = {r: sum(clean[c] - clean[u] for c, _, u in v["confidence_rows"])
                   / len(v["confidence_rows"]) for r, v in tr["rounds"].items()}
            if cm["status"] == C.NO_SELF_REPORT:
                used = [w for w in rows if w["disposition"] == "COUNTED"]
                dims.append(finish_dim({"name": "CONFIDENCE_GAP", "family": "CONFIDENCE_GAP",
                                        "round": None, "output": C.NO_SELF_REPORT,
                                        "truth": None, "n": len(used),
                                        "never_reports": tr["never_reports"]}, used, {}))
            else:
                for cr, mr in zip(crs, cm["rounds"]):
                    used = rws(cr.round, ("COUNTED",))
                    dims.append(finish_dim({"name": f"CONFIDENCE_GAP@r{cr.round}",
                                            "family": "CONFIDENCE_GAP", "round": cr.round,
                                            "output": mr["gap"]["status"],
                                            "truth": truth_class(tgc[cr.round]),
                                            "true_inflation": tgc[cr.round],
                                            "reported": sum(1 for _, c in cr.answers
                                                            if c is not None),
                                            "n": len(used)}, used, {}))
                tred = abs(tgc[r1]) - abs(tgc[r3])
                used = rws(r1, ("COUNTED",)) + rws(r3, ("COUNTED",))
                dims.append(finish_dim({"name": "CONFIDENCE_REDUCTION",
                                        "family": "CONFIDENCE_REDUCTION", "round": None,
                                        "output": cm["reduction"]["status"],
                                        "truth": tred > C.REDUCTION_THRESHOLD,
                                        "true_reduction": tred, "n": len(used)}, used, {}))
            wrong_conf = [d for d in dims if d["label"] == S.WRONG
                          and d["family"].startswith("CONFIDENCE")]
            if details is not None and wrong_conf:
                # counterfactual (robustness check only): every missing self-report filled with
                # the rating the learner really had (truth), the measure run again
                full = [C.ConfRound(ri.round, tuple(
                    (cr, conf[rid] if conf[rid] is not None
                     else (T["rows"].get(rid) or {}).get("confidence_true"))
                    for cr, rid in zip(ri.unaided, ri.unaided_records))) for ri in ris]
                cm2 = C.measure(lid, cid, full, norm)
                st2 = {f"CONFIDENCE_GAP@r{x['round']}": x["gap"]["status"]
                       for x in cm2.get("rounds", [])}
                st2["CONFIDENCE_REDUCTION"] = (cm2["reduction"] or {}).get("status")
                for d in wrong_conf:
                    o2 = st2.get(d["name"])
                    d["counterfactual"] = {"input_replay": {
                        "filled_self_reports": sum(1 for rid in d["used"] if conf[rid] is None),
                        "output": o2,
                        "label": None if o2 is None else label(d["family"], o2, d["truth"], d["n"])}}
            for d in dims:
                if details is not None and d["label"] == S.WRONG and "counterfactual" not in d:
                    d["counterfactual"] = {"input_replay": "NOT_AVAILABLE (no missing field)"}
            case = {
                "format": S.FORMAT, "case_id": case_id, "run": "R95",
                "learner_id": lid, "concept_id": cid, "population": tr["population"],
                "truth": {"rounds": {r: {"knows_at_post_test": v["known"],
                                         "expected_unaided_share": v["true_unaided"],
                                         "expected_assisted_share": v["true_assisted"],
                                         "true_gap": v["true_gap"],
                                         "true_confidence_inflation": tgc[r]}
                                     for r, v in sorted(tr["rounds"].items())},
                          "never_reports_confidence": tr["never_reports"],
                          "known_before_intervention": T["known_at_start"][cid]},
                "stages": {
                    "learner_state": {"status": "STAND_IN"},
                    "verdict": {"by_round": {ri.round: ri.verdict for ri in ris}},
                    "outcome96": S.NOT_RUN,
                    "gap95": {"assisted": {"by_round": {mr["round"]: mr["gap"]["status"]
                                                        for mr in m["rounds"]},
                                           "reduction": m["reduction"]["status"]},
                              "confidence": {"status": cm["status"],
                                             "by_round": {mr["round"]: mr["gap"]["status"]
                                                          for mr in cm.get("rounds", [])},
                                             "reduction": (cm["reduction"] or {}).get("status")}},
                    "diagnosis": S.NOT_BUILT, "adaptation": S.NOT_BUILT},
                "dimensions": dims,
            }
            if details is not None:
                case["answers"] = [w for w in rows if w["phase"] != "PRACTICE"
                                   or w["disposition"] == "COUNTED"]
                case["practice_answers"] = sum(1 for w in rows if w["phase"] == "PRACTICE")
                case["intervention_delivered_at"] = [ri_["iv"].delivered_at
                                                     for ri_ in L["rounds"][cid]]
            cases.append(case)
    return cases
