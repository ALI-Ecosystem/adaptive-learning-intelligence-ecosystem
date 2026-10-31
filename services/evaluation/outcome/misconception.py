"""Misconception state at delivery, and the error-repetition measure (SCRUM-96 Q3).

Learner State (LS 3.8) is specified to track every misconception as a Beta(alpha, beta) fed
by the item bank's option -> misconception map: picking a mapped distractor is evidence FOR
the misconception, and only a DISCRIMINATING item (one that carries that misconception as a
distractor) can count against it. Learner State does not exist yet and its read view
(MisconceptionView) exposes no (alpha, beta): EVAL-CR-003 (e). Until then this stand-in
builds the state the same way, from the answers BEFORE delivery (decision 3c, the
compromise: the main result uses this; the simulator's truth is used only as an upper bound,
on the scoring side - harness/validate96.py, never in this package).

    prior          Beta(0.5, 1.5)   LS prior strength n0 = 2, centred on 1/k = 0.25 - the
                                    chance of picking one given option of four when guessing
    known          posterior mean > 0.25: there is evidence for it beyond guessing
    error repetition (after the intervention, independent answers only, on discriminating
                   items): chose = 1 if the picked option is mapped to the misconception
    persists?      H: rate > r0, r0 = slip / 3 - a learner who knows and holds no
                   misconception picks one given distractor only when he slips, and a slip
                   is spread over the three distractors (decision 3b option A).
                   P = P(rate > r0 | prior + observations), BF = posterior odds / prior odds;
                   the SCRUM-94 rule: SUPPORTED if BF >= 4 and P > 0.5, NOT_SUPPORTED if
                   BF <= 1/4 and P < 0.5, otherwise INSUFFICIENT.

Practice answers never count: they are IN_TREATMENT for the eligibility gate (Li et al.
2025: practice errors of novices go with larger gains).
"""
from verdict import betafn, model
from verdict.standin import SLIP

PRIOR = (0.5, 1.5)
CHANCE = 0.25
R0 = SLIP / 3.0


def option_map(public_items: list) -> dict:
    """items.json -> {item_id: {option: misconception_id or None}}"""
    return {it["item_id"]: {o["option"]: o["misconception_id"] for o in it["options"]}
            for it in public_items}


def carries(item_map: dict, item_id: str, mid: str) -> bool:
    return mid in (item_map.get(item_id) or {}).values()


def chose(item_map: dict, item_id: str, option: str | None, mid: str) -> int:
    return int(option is not None and (item_map.get(item_id) or {}).get(option) == mid)


class AnswerBuiltMisconceptions:
    """The stand-in: Beta per misconception from the learner's answers before as_of.
    concept_misconceptions: {concept_id: [misconception_id, ...]} (item bank metadata)."""
    SOURCE = "misconception-standin(LS 3.8 rules, answers before delivery)"

    def __init__(self, concept_misconceptions: dict, item_map: dict):
        self.cm, self.item_map = concept_misconceptions, item_map

    def state(self, learner_id: str, concept_id: str, answers: list, as_of: float) -> dict:
        """{mid: (alpha, beta, known)} from every MCQ answer of this learner on this concept
        that occurred strictly before as_of (Learner State ingests all evidence)."""
        out = {}
        mine = [a for a in answers if a.learner_id == learner_id and a.concept_id == concept_id
                and a.occurred_at < as_of and a.chosen_option is not None]
        for mid in self.cm.get(concept_id, ()):
            a, b = PRIOR
            for x in mine:
                if carries(self.item_map, x.item_id, mid):
                    c = chose(self.item_map, x.item_id, x.chosen_option, mid)
                    a, b = a + c, b + (1 - c)
            out[mid] = (a, b, a / (a + b) > CHANCE)
        return out


class Repetition:
    """The error-repetition measure of one known misconception, fed one observation at a
    time."""

    def __init__(self, mid: str, alpha: float, beta: float):
        self.mid, self.a0, self.b0 = mid, alpha, beta
        self.n = self.picks = 0
        self.prior_p = betafn.sf(R0, alpha, beta)

    def add(self, c: int):
        self.n += 1
        self.picks += c

    def read(self) -> dict:
        a, b = self.a0 + self.picks, self.b0 + (self.n - self.picks)
        p = betafn.sf(R0, a, b) if self.n else self.prior_p
        pr = self.prior_p
        bf = ((p / max(1 - p, 1e-300)) / (pr / max(1 - pr, 1e-300))) if self.n else 1.0
        return {"misconception_id": self.mid, "n": self.n, "picks": self.picks,
                "prior": [round(self.a0, 6), round(self.b0, 6)],
                "p_persists": p, "bayes_factor": bf,
                "status": model.status_from(p, bf, self.n)}
