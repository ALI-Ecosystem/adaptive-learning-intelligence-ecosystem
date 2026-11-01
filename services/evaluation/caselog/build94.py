"""Cases of the SCRUM-94 run: one (learner, concept), judged at the end of its 8-item
post-test. The chain: truth -> answers (counted / excluded) -> verdict -> label."""
import json
from pathlib import Path

from harness import adapter94 as A
from verdict import engine

from . import spec as S
from .common import finish_dim, row


def load_trace(run_dir) -> dict:
    """SCORING SIDE: {learner_id: {"pop", "rows": {record_id: trace row}, "truth": ...}}"""
    out = {}
    with open(Path(run_dir) / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            out[t["learner_id"]] = {
                "population": t["population"],
                "rows": {r["source_record_id"]: r for r in t["trace"]},
                "checkpoints": t["checkpoints"], "known_at_start": t["known_at_start"],
                "misconceptions_at_start": t.get("misconceptions_at_start", {}),
                "params": t["params"]}
    return out


def build(root=".", details=None):
    """All cases (light) - or, with details = {case_id}, the full chain of those only."""
    cfg = S.RUNS["R94"]
    run_dir, calib_dir = Path(root) / cfg["run"], Path(root) / cfg["calib"]
    calib = A.load_calibration(calib_dir / "calibration.json")
    run = A.load_run(run_dir, calib)
    ls = A.standin_for(run)
    trace = load_trace(run_dir)
    cases = []
    for lid in sorted(run):
        L, T = run[lid], trace[lid]
        for cid in sorted(L["interventions"]):
            case_id = f"R94-{lid[:8]}-{cid[:8]}"
            if details is not None and case_id not in details:
                continue
            iv, as_of = L["interventions"][cid], L["as_of"][cid]
            v = engine.evaluate(iv, ls, L["answers"], [], as_of)
            by_id = {a.record_id: a for a in L["answers"]}
            imm = T["checkpoints"]["immediate"]["concepts"][cid]
            rows = []
            for j in v.answers:
                a = by_id[j.record_id]
                if a.concept_id != cid:
                    continue
                meta = {"phase": L["phase"][a.record_id]}
                rows.append(row(a, meta, T["rows"].get(a.record_id),
                                "COUNTED" if j.counted else "EXCLUDED", j.exclusion,
                                "VERDICT" if j.counted else None))
            used = [r for r in rows if r["disposition"] == "COUNTED"]
            dim = finish_dim({"name": "VERDICT", "family": "VERDICT", "round": None,
                              "output": v.outcome.value, "truth": imm["known"], "n": len(used),
                              "p": v.p_target, "bayes_factor": v.bayes_factor}, used, {})
            case = {
                "format": S.FORMAT, "case_id": case_id, "run": "R94",
                "learner_id": lid, "concept_id": cid, "population": T["population"],
                "truth": {"knows_at_post_test": imm["known"],
                          "learned_due_to_intervention": imm["learned_due_to_intervention"],
                          "known_before_intervention": T["known_at_start"][cid],
                          "misconception_at_post_test": imm.get("misconception"),
                          "judged_at": as_of},
                "stages": {
                    "learner_state": {"status": "STAND_IN",
                                      "prior_p_target": v.prior_p_target},
                    "verdict": {"outcome": v.outcome.value, "p_target": v.p_target,
                                "bayes_factor": v.bayes_factor, "counted": len(used),
                                "excluded": len(rows) - len(used)},
                    "outcome96": S.NOT_RUN, "gap95": S.NOT_RUN,
                    "diagnosis": S.NOT_BUILT, "adaptation": S.NOT_BUILT},
                "dimensions": [dim],
            }
            if details is not None and dim["label"] == S.WRONG:
                dim["counterfactual"] = {"replay": "NOT_AVAILABLE (complete records, fixed schedule)"}
            if details is not None:
                case["answers"] = [r for r in rows if r["phase"] != "PRACTICE"
                                   or r["disposition"] == "COUNTED"]
                case["practice_answers"] = sum(1 for r in rows if r["phase"] == "PRACTICE")
                case["intervention_delivered_at"] = iv.delivered_at
            cases.append(case)
    return cases
