"""Turns a simulator run into verdict inputs, and keeps the truth on the scoring side.

What the simulator stream lacks, and what this adapter supplies instead (each is a MISSING
field in the SCRUM-94 report, with the module that must provide it):

  * provenance of test answers - the simulator's PRE/POST/DELAYED_TEST answers carry no
    producing plan item. The adapter names one per learner and phase ("<phase>:<learner>",
    intent PROBE), as the ALE's PROBE plan items would.            -> ALE (EVAL-CR-001)
  * COMPLETED time of the intervention - none; treatment end falls back to the last
    in-treatment answer (engine.treatment_end).                     -> ALE status events
  * item difficulty b and its standard error - from the calibration table, computed on a
    SEPARATE simulator run (harness/calibrate.py), never from the generator. -> Task block
  * guess rate - 0.25: four options, the item bank's own structure.  -> Evidence block
  * cognitive level - the simulator has one; both sides use "UNSPECIFIED". -> Evidence/Task
  * evidence weights w_c, w_i - 1.0 (no reported guess, no rubric).   -> Learner State
  * items shown without an answer - none in the simulator.            -> ALE / UI log

Nothing here reads truth.jsonl except load_truth(), which only the scoring code calls.
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from verdict.contracts import AnswerRecord, Intervention
from verdict.standin import LearnerStateStandIn

EPOCH = datetime.fromisoformat("2026-01-05T08:00:00+00:00")
TARGET_MU = 0.70            # decision B: the simulator's truth is "knows" -> MASTERED boundary
LEVEL = "UNSPECIFIED"
GUESS = 0.25
TEST_PHASES = ("PRE_TEST", "POST_TEST", "DELAYED_TEST")


def secs(iso: str) -> float:
    return (datetime.fromisoformat(iso) - EPOCH).total_seconds()


def load_calibration(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return {r["item_id"]: (r["b"], r["se"]) for r in json.load(f)["items"]}


def to_record(body: dict, calib: dict) -> AnswerRecord:
    p, rec = body["record"]["payload"], body["record"]
    phase = p["activity"]
    if p.get("intervention_id"):
        prod, intent = p["intervention_id"], "PRACTISE"
    elif phase in TEST_PHASES:
        prod, intent = f"{phase}:{body['learner_id']}", "PROBE"      # adapter-supplied
    else:
        prod, intent = None, None
    b, se = calib.get(p["item_id"], (None, None))
    return AnswerRecord(
        record_id=rec["source_record_id"], learner_id=body["learner_id"],
        concept_id=body["concept"]["concept_id"], cognitive_level=LEVEL,
        occurred_at=secs(rec["occurred_at"]), item_id=p["item_id"],
        chosen_option=p["chosen_option"], credit=1.0 if p["correct"] else 0.0,
        attempt_number=p.get("attempt_number", 1), help_before_answer=bool(p.get("had_help")),
        producing_intervention_id=prod, producing_intent=intent, item_b=b, item_b_se=se,
        guess_rate=GUESS)


def load_run(run_dir, calib: dict) -> dict:
    """{learner_id: {"answers": [AnswerRecord], "phase": {record_id: phase},
                     "interventions": {concept_id: Intervention},
                     "as_of": {concept_id: end of that concept's POST_TEST}}}"""
    out = defaultdict(lambda: {"answers": [], "phase": {}, "interventions": {}, "as_of": {}})
    with open(Path(run_dir) / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            body = json.loads(line)
            lid, cid = body["learner_id"], body["concept"]["concept_id"]
            L = out[lid]
            t = secs(body["record"]["occurred_at"])
            if body["operation"] == "ADD_EXPOSURE":
                pid = body["record"]["payload"]["intervention_id"]
                L["interventions"][cid] = Intervention(
                    intervention_id=pid, learner_id=lid, concept_id=cid, cognitive_level=LEVEL,
                    intent=body["record"]["payload"].get("kind", "INSTRUCT"),
                    target_mu=TARGET_MU, delivered_at=t, completed_at=None)
                continue
            r = to_record(body, calib)
            L["answers"].append(r)
            phase = body["record"]["payload"]["activity"]
            L["phase"][r.record_id] = phase
            if phase == "POST_TEST":
                L["as_of"][cid] = max(L["as_of"].get(cid, t), t)
    for L in out.values():
        L["answers"].sort(key=lambda a: (a.occurred_at, a.record_id))
    return dict(out)


def standin_for(run: dict) -> LearnerStateStandIn:
    """Learner State as the stand-in would hold it: every answer is evidence; practice
    answers carry feedback (had_instruction). The verdict reads only baselines from it."""
    ls = LearnerStateStandIn()
    for L in run.values():
        for a in L["answers"]:
            ls.ingest({"learner_id": a.learner_id, "concept_id": a.concept_id,
                       "record_id": a.record_id, "occurred_at": a.occurred_at,
                       "credit": a.credit, "weight": 1.0, "guess_rate": a.guess_rate,
                       "had_instruction": L["phase"][a.record_id] == "PRACTICE"})
    return ls


def load_truth(run_dir) -> dict:
    """SCORING ONLY. {(learner_id, concept_id): {...immediate checkpoint..., population}}"""
    truth = {}
    with open(Path(run_dir) / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            for cid, s in t["checkpoints"]["immediate"]["concepts"].items():
                truth[(t["learner_id"], cid)] = {
                    "population": t["population"], "known": s["known"],
                    "learned_due_to_intervention": s["learned_due_to_intervention"],
                    "known_at_start": t["known_at_start"][cid]}
    return truth
