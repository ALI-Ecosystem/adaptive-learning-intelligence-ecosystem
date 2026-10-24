"""Turns a SCRUM-95 simulator run (several rounds) into gap-measure inputs.

Builds on adapter94 (same AnswerRecord, same calibration, same Learner State stand-in). What
is new: a learner has one intervention per concept PER ROUND, so each round gets its own
verdict, judged at the end of that round's post-test. The SCRUM-94 eligibility gate then
sorts every answer:

  counted                      -> the round's UNAIDED side (and the verdict)
  excluded ASSISTED, and would  -> the round's ASSISTED side
  pass every later rule
  anything else inside the
  round's window               -> neither side, listed with its reason

Nothing here reads truth.jsonl except load_truth95(), which only the scoring code calls.
"""
import json
from collections import defaultdict
from pathlib import Path

from gap.assisted import RoundInput
from harness import adapter94 as A
from verdict import engine
from verdict.contracts import Exclusion, Intervention

STRUCTURAL = {None, Exclusion.ASSISTED.value, Exclusion.IN_TREATMENT.value,
              Exclusion.BEFORE_TREATMENT_END.value, Exclusion.AFTER_AS_OF.value,
              Exclusion.RETENTION_WINDOW.value}


def load_run95(run_dir, calib: dict) -> dict:
    """{learner_id: {"answers": [AnswerRecord], "phase": {record_id: phase},
                     "rounds": {concept_id: [{"round", "iv", "as_of"}]}}}"""
    out = defaultdict(lambda: {"answers": [], "phase": {}, "ivs": defaultdict(list),
                               "post": defaultdict(list), "confidence": {}})
    with open(Path(run_dir) / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            body = json.loads(line)
            lid, cid = body["learner_id"], body["concept"]["concept_id"]
            L = out[lid]
            t = A.secs(body["record"]["occurred_at"])
            if body["operation"] == "ADD_EXPOSURE":
                p = body["record"]["payload"]
                L["ivs"][cid].append(Intervention(
                    intervention_id=p["intervention_id"], learner_id=lid, concept_id=cid,
                    cognitive_level=A.LEVEL, intent=p.get("kind", "INSTRUCT"),
                    target_mu=A.TARGET_MU, delivered_at=t, completed_at=None))
                continue
            r = A.to_record(body, calib)
            L["answers"].append(r)
            phase = body["record"]["payload"]["activity"]
            L["phase"][r.record_id] = phase
            L["confidence"][r.record_id] = body["record"]["payload"].get("confidence")
            if phase == "POST_TEST":
                L["post"][cid].append(t)
    run = {}
    for lid, L in out.items():
        L["answers"].sort(key=lambda a: (a.occurred_at, a.record_id))
        rounds = {}
        for cid, ivs in L["ivs"].items():
            ivs.sort(key=lambda iv: iv.delivered_at)
            starts = [iv.delivered_at for iv in ivs] + [float("inf")]
            rounds[cid] = [{"round": i + 1, "iv": iv,
                            "as_of": max(t for t in L["post"][cid] if starts[i] < t < starts[i + 1])}
                           for i, iv in enumerate(ivs)]
        run[lid] = {"answers": L["answers"], "phase": L["phase"], "rounds": rounds,
                    "confidence": L["confidence"]}
    return run


def round_inputs(L: dict, cid: str, reader) -> list:
    """[RoundInput] for one learner and concept, each round with its own verdict."""
    answers = L["answers"]
    by_id = {a.record_id: a for a in answers}
    first = {}
    for a in answers:
        first.setdefault(a.item_id, (a.occurred_at, a.record_id))
    out = []
    for rd in L["rounds"][cid]:
        iv, as_of = rd["iv"], rd["as_of"]
        v = engine.evaluate(iv, reader, answers, [], as_of)
        t_end = engine.treatment_end(iv, answers, as_of)
        unaided, assisted, excluded, ids = [], [], [], []
        for j in v.answers:
            if j.counted:
                unaided.append(j.credit)
                ids.append(j.record_id)
                continue
            if not (t_end < j.occurred_at <= as_of):
                continue                        # another round's answer: not this round's
            a = by_id[j.record_id]
            if j.exclusion == Exclusion.ASSISTED.value:
                also = [n for n, bad in (
                    (Exclusion.NOT_FIRST_ATTEMPT.value, a.attempt_number != 1),
                    (Exclusion.ITEM_SEEN_BEFORE.value,
                     first[a.item_id] < (a.occurred_at, a.record_id)),
                    (Exclusion.ITEM_FLAGGED.value, a.item_flagged)) if bad]
                if also:
                    excluded.append((j.record_id, "ASSISTED+" + "+".join(also)))
                else:
                    assisted.append(j.credit)
            elif j.exclusion not in STRUCTURAL:
                excluded.append((j.record_id, j.exclusion))
        out.append(RoundInput(round=rd["round"], intervention_id=iv.intervention_id,
                              unaided=tuple(unaided), assisted=tuple(assisted),
                              verdict=v.outcome.value, excluded=tuple(excluded),
                              unaided_records=tuple(ids)))
    return out


# ---- scoring side only ------------------------------------------------------------------------

def _p_correct(row: dict, item: dict, p: dict) -> float:
    """Expected P(correct) of one answered item from the TRUE state (learner.answer)."""
    mis_opt = any(o["misconception_id"] == row["misconception"] for o in item["options"]) \
        if row["misconception"] else False
    if row["known"]:
        base = (1 - (p["p_M_known"] if mis_opt else 0.0)) * (1 - p["p_S"])
    else:
        base = (1 - (p["p_M_unknown"] if mis_opt else 0.0)) * 0.25
    if row["had_help"]:
        return p["p_help_correct"] + (1 - p["p_help_correct"]) * base
    return base


def load_truth95(run_dir) -> dict:
    """SCORING ONLY. {(learner_id, concept_id): {"population", "rounds": {r: {
        "true_unaided", "true_assisted", "true_gap", "known"}}}}"""
    items = {it["item_id"]: it for it in json.loads((Path(run_dir) / "items.json").read_text())}
    payload_item = {}
    with open(Path(run_dir) / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            b = json.loads(line)
            if b["operation"] == "ADD_EVIDENCE":
                payload_item[b["record"]["source_record_id"]] = b["record"]["payload"]["item_id"]
    truth = {}
    with open(Path(run_dir) / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            acc = defaultdict(lambda: {"U": [], "A": [], "C": []})
            for row in t["trace"]:
                if row["phase"] != "POST_TEST":
                    continue
                p = _p_correct(row, items[payload_item[row["source_record_id"]]],
                               t["params"][row["concept_id"]])
                acc[(row["concept_id"], row["round"])]["A" if row["assisted"] else "U"].append(p)
                if not row["assisted"]:
                    acc[(row["concept_id"], row["round"])]["C"].append(
                        (row["confidence_true"], p, row["confidence_uninflated"]))
            for cid in t["params"]:
                rounds = {}
                for (c, r), v in acc.items():
                    if c != cid:
                        continue
                    tu, ta = sum(v["U"]) / len(v["U"]), sum(v["A"]) / len(v["A"])
                    cp = t["checkpoints"]["immediate" if r == 1 else f"immediate_r{r}"]
                    rounds[r] = {"true_unaided": tu, "true_assisted": ta, "true_gap": ta - tu,
                                 "known": cp["concepts"][cid]["known"],
                                 "confidence_rows": v["C"]}   # (true conf, E[correct], uninflated conf)
                truth[(t["learner_id"], cid)] = {"population": t["population"], "rounds": rounds,
                                                 "never_reports": t["never_reports_confidence"]}
    return truth
