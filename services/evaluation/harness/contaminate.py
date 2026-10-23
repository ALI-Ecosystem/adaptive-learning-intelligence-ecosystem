"""Answers that must NEVER affect the verdict, injected into a clean stream (decision 1:
injection in the SCRUM-94 harness; the SCRUM-93 simulator is not changed).

For every (learner, concept) case, inside the window the verdict judges (after treatment
end, before the moment judged), five answers are added. Each fails exactly ONE rule, so
the recorded exclusion reason proves which rule caught it:

  HELP        a fresh, calibrated item answered after help              -> ASSISTED
  SECOND_TRY  the first post-test item again, attempt 2, no help         -> NOT_FIRST_ATTEMPT
  REPEATED    a pre-test item again, attempt 1, no help                  -> ITEM_SEEN_BEFORE
  SHOWN       a fresh item shown during practice, answered now           -> ITEM_SEEN_BEFORE
  NO_SOURCE   a fresh item from no plan item                             -> UNKNOWN_PROVENANCE

All five are CORRECT in the "tempting" variant (they would push towards DEMONSTRATED) and
WRONG in the "damning" variant. The test: the verdict - outcome, P and BF, to the last bit
- is identical with and without them, for every case.
"""
from dataclasses import replace

from verdict.contracts import ItemShown

FRESH_B, FRESH_SE = 0.0, 0.30       # the injected fresh items get a calibration entry,
                                    # so NO_DIFFICULTY cannot be what excludes them
EXPECTED = {"HELP": "ASSISTED", "SECOND_TRY": "NOT_FIRST_ATTEMPT",
            "REPEATED": "ITEM_SEEN_BEFORE", "SHOWN": "ITEM_SEEN_BEFORE",
            "NO_SOURCE": "UNKNOWN_PROVENANCE"}


def contaminate(learner: dict, credit: float) -> tuple:
    """learner: one entry of adapter94.load_run. Returns (answers, shown, injected ids)."""
    answers = list(learner["answers"])
    shown, injected = [], {}
    phase = learner["phase"]
    for cid, iv in sorted(learner["interventions"].items()):
        mine = [a for a in learner["answers"] if a.concept_id == cid]
        post = [a for a in mine if phase[a.record_id] == "POST_TEST"]
        pre = [a for a in mine if phase[a.record_id] == "PRE_TEST"]
        practice = [a for a in mine if phase[a.record_id] == "PRACTICE"]
        if not post or not pre or not practice:
            continue
        t0, t1 = post[0].occurred_at, post[-1].occurred_at
        base = post[0]

        def make(kind, item_id, t, **kw):
            rid = f"INJ:{kind}:{base.learner_id}:{cid}"
            injected[rid] = kind
            return replace(base, record_id=rid, item_id=item_id, occurred_at=t,
                           credit=credit, chosen_option="A", item_b=FRESH_B,
                           item_b_se=FRESH_SE, **kw)
        answers.append(make("HELP", f"FRESH-HELP-{cid[:8]}", t0 + 1, help_before_answer=True))
        answers.append(make("SECOND_TRY", base.item_id, t0 + 2, attempt_number=2))
        answers.append(make("REPEATED", pre[0].item_id, t0 + 3))
        fresh = f"FRESH-SHOWN-{cid[:8]}"
        shown.append(ItemShown(base.learner_id, fresh, practice[0].occurred_at))
        answers.append(make("SHOWN", fresh, t1 - 1 if t1 - 1 > t0 + 3 else t0 + 4))
        answers.append(make("NO_SOURCE", f"FRESH-NOSRC-{cid[:8]}", t0 + 5,
                            producing_intervention_id=None, producing_intent=None))
    answers.sort(key=lambda a: (a.occurred_at, a.record_id))
    return answers, shown, injected
