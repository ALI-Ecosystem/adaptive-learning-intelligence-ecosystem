"""Deliberately naive evaluation rules, run on the answer stream only.

This module must never open the truth file (a test checks it). Its only input is
answers.jsonl; its output is decisions.jsonl.

Rules, applied at two checkpoints - after the POST_TEST and after the DELAYED_TEST - to
all answers on the concept up to that point, in time order:

  three_of_last_four   the last 4 answers: 3 or more correct -> "learned"   (SCRUM-93 example)
  last_answer          the last answer correct -> "learned"                  (proposal baseline:
                                                                              "recommendations
                                                                              based only on the
                                                                              most recent answer")

Both are naive on purpose: they use help-assisted practice answers like any other, ignore
what the learner knew before, and ignore guessing. They give later missions a baseline to
beat, not a method to keep.
"""
import json
from collections import defaultdict
from pathlib import Path

CHECKPOINT_PHASE = {"immediate": "POST_TEST", "delayed": "DELAYED_TEST"}


def three_of_last_four(answers: list) -> bool:
    return sum(a["correct"] for a in answers[-4:]) >= 3


def last_answer(answers: list) -> bool:
    return bool(answers) and answers[-1]["correct"]


RULES = {"three_of_last_four": three_of_last_four, "last_answer": last_answer}


def load_answers(path) -> dict:
    """{(learner_id, concept_id): [payload + occurred_at, ...]} in time order."""
    seqs = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            b = json.loads(line)
            if b["operation"] != "ADD_EVIDENCE":
                continue
            p = dict(b["record"]["payload"], occurred_at=b["record"]["occurred_at"])
            seqs[(b["learner_id"], b["concept"]["concept_id"])].append(p)
    for s in seqs.values():
        s.sort(key=lambda p: p["occurred_at"])
    return seqs


def decide(seqs: dict) -> list:
    out = []
    for (learner_id, concept_id), seq in sorted(seqs.items()):
        for checkpoint, phase in CHECKPOINT_PHASE.items():
            last = max((i for i, a in enumerate(seq) if a["activity"] == phase), default=None)
            if last is None:
                continue
            upto = seq[:last + 1]
            for name, rule in RULES.items():
                out.append({"learner_id": learner_id, "concept_id": concept_id,
                            "checkpoint": checkpoint, "rule": name, "learned": rule(upto)})
    return out


def run(run_dir) -> Path:
    run_dir = Path(run_dir)
    decisions = decide(load_answers(run_dir / "answers.jsonl"))
    out = run_dir / "decisions.jsonl"
    out.write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in decisions),
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    print(run(sys.argv[1] if len(sys.argv) > 1 else "runs/seed-93"))
