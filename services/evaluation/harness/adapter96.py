"""Turns a SCRUM-96 simulator run into outcome cases, and plays the Adaptive Learning
Engine's part in the retention check (decision Q1 option B).

What is new against adapter94:
  * activity type - TRANSFER_PROBLEM is read from the record (payload activity_type), as
    the ALE's intent / activity type would declare it; the producing plan item of a
    transfer answer gets intent TRANSFER.                                  -> ALE
  * explanations - OPEN answers with a grade from the Evidence module. They have no item
    difficulty; the adapter gives them b = 0, se = 0 ONLY so the SCRUM-94 gate's
    "no difficulty" rule does not exclude them - the outcome engine never puts them in a
    statistic with b (reported only).                                       -> Evidence block
  * the ALE stand-in: whether a delayed check reached the learner at all. The simulator
    gives every learner a delayed test; the ALE does not schedule a check for everyone.
    For a share NEVER_SHARE of learners (keyed, reproducible) the delayed answers are
    removed before evaluation: "the check never happened". All other delayed answers stay,
    whenever they fall - before t_R they are acquisition (decision 1a option A).
  * the misconception map - from items.json; the misconceptions of each concept.

Nothing here reads truth.jsonl except load_truth96(), which only the scoring code calls.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from harness import adapter94 as A
from verdict.contracts import AnswerRecord, Intervention

NEVER_SHARE = 0.20
STUDY_TAIL_DAYS = 7
COVERAGE_KEY = "ali-ale-standin|scrum96|delayed-check"


def never_checked(learner_id: str, share: float = NEVER_SHARE) -> bool:
    """The ALE stand-in's decision, keyed by the learner id: no shared random state."""
    h = hashlib.sha256(f"{COVERAGE_KEY}|{learner_id}".encode()).digest()
    return (int.from_bytes(h[:8], "big") >> 11) / float(1 << 53) < share


def load_items(run_dir) -> list:
    with open(Path(run_dir) / "items.json", encoding="utf-8") as f:
        return json.load(f)


def concept_misconceptions(items: list, concept_by_source: dict) -> dict:
    out = defaultdict(set)
    for it in items:
        cid = concept_by_source[it["concept_source_id"]]
        out[cid].update(o["misconception_id"] for o in it["options"] if o["misconception_id"])
    return {c: sorted(v) for c, v in out.items()}


def to_record96(body: dict, calib: dict) -> tuple:
    p, rec = body["record"]["payload"], body["record"]
    phase = p["activity"]
    kind = p.get("activity_type")
    meta = {"phase": phase}
    if phase == "EXPLANATION":
        meta.update(activity_type="EXPLANATION", grade=p["grade"], test=p.get("test"))
        prod, intent = f"{p.get('test')}:{body['learner_id']}", "PROBE"
        b, se = 0.0, 0.0
        credit = float(p["grade"])
    else:
        if p.get("intervention_id"):
            prod, intent = p["intervention_id"], "PRACTISE"
        elif phase in A.TEST_PHASES:
            intent = "TRANSFER" if kind == "TRANSFER_PROBLEM" else "PROBE"
            prod = f"{phase}:{intent}:{body['learner_id']}"
        else:
            prod, intent = None, None
        b, se = calib.get(p["item_id"], (None, None))
        credit = 1.0 if p["correct"] else 0.0
        if kind:
            meta["activity_type"] = kind
    r = AnswerRecord(
        record_id=rec["source_record_id"], learner_id=body["learner_id"],
        concept_id=body["concept"]["concept_id"], cognitive_level=A.LEVEL,
        occurred_at=A.secs(rec["occurred_at"]), item_id=p["item_id"],
        chosen_option=p.get("chosen_option"), credit=credit,
        attempt_number=p.get("attempt_number", 1), help_before_answer=bool(p.get("had_help")),
        producing_intervention_id=prod, producing_intent=intent, item_b=b, item_b_se=se,
        guess_rate=A.GUESS)
    return r, meta


def load_run96(run_dir, calib: dict, never_share: float = NEVER_SHARE) -> dict:
    """{learner_id: {"answers", "meta", "interventions", "never_checked", "removed",
                     "horizon"}} - the delayed answers of never-checked learners are removed
    (kept count in "removed")."""
    out = defaultdict(lambda: {"answers": [], "meta": {}, "interventions": {}, "removed": 0,
                               "all_answers": []})
    with open(Path(run_dir) / "answers.jsonl", encoding="utf-8") as f:
        for line in f:
            body = json.loads(line)
            lid, cid = body["learner_id"], body["concept"]["concept_id"]
            L = out[lid]
            t = A.secs(body["record"]["occurred_at"])
            if body["operation"] == "ADD_EXPOSURE":
                p = body["record"]["payload"]
                L["interventions"][cid] = Intervention(
                    intervention_id=p["intervention_id"], learner_id=lid, concept_id=cid,
                    cognitive_level=A.LEVEL, intent=p.get("kind", "INSTRUCT"),
                    target_mu=A.TARGET_MU, delivered_at=t, completed_at=None)
                continue
            r, meta = to_record96(body, calib)
            L["meta"][r.record_id] = meta
            L["all_answers"].append(r)
            delayed = meta["phase"] == "DELAYED_TEST" or meta.get("test") == "DELAYED_TEST"
            if delayed and never_checked(lid, never_share):
                L["removed"] += 1
                continue
            L["answers"].append(r)
    for lid, L in out.items():
        L["answers"].sort(key=lambda a: (a.occurred_at, a.record_id))
        L["never_checked"] = never_checked(lid, never_share)
        last = max(a.occurred_at for a in L["all_answers"])
        # the study end: a week after the learner's last record, the same for checked and
        # never-checked learners, so every check has either happened or become overdue
        L["horizon"] = last + STUDY_TAIL_DAYS * 86_400.0
    return dict(out)


def standin_for96(run: dict):
    """Learner State stand-in fed with every MCQ answer that reached the system (explanations
    are graded open answers; the stand-in's mastery update is for MCQ evidence)."""
    from verdict.standin import LearnerStateStandIn
    ls = LearnerStateStandIn()
    for L in run.values():
        for a in L["answers"]:
            if L["meta"][a.record_id].get("activity_type") == "EXPLANATION":
                continue
            ls.ingest({"learner_id": a.learner_id, "concept_id": a.concept_id,
                       "record_id": a.record_id, "occurred_at": a.occurred_at,
                       "credit": a.credit, "weight": 1.0, "guess_rate": a.guess_rate,
                       "had_instruction": L["meta"][a.record_id]["phase"] == "PRACTICE"})
    return ls


def load_truth96(run_dir) -> dict:
    """SCORING ONLY. {(learner_id, concept_id): {...}}"""
    truth = {}
    with open(Path(run_dir) / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            imm, dl = t["checkpoints"]["immediate"], t["checkpoints"]["delayed"]
            for cid, s in imm["concepts"].items():
                d = dl["concepts"][cid]
                truth[(t["learner_id"], cid)] = {
                    "population": t["population"], "learner_id": t["learner_id"],
                    "known_imm": s["known"], "depth_imm": s.get("depth"),
                    "mis_imm": s["misconception"], "learned": s["learned_due_to_intervention"],
                    "known_del": d["known"], "depth_del": d.get("depth"),
                    "mis_del": d["misconception"], "delayed_at": A.secs(dl["at"]),
                    "mis_start": t["misconceptions_at_start"].get(cid),
                    "known_at_start": t["known_at_start"][cid],
                    "explains": t.get("explains", False)}
    return truth
