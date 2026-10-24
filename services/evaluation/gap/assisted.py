"""Assisted-versus-unaided gap, per round, and its reduction (SCRUM-95 decisions M1-M3).

For one learner and one concept:

  side      raw share correct of the round's answers, Beta(k + 1, n - k + 1) posterior
            unaided  = the answers the SCRUM-94 eligibility gate COUNTED for that round's
                       verdict (independent, first attempt, after the treatment, ...)
            assisted = the answers the gate excluded ONLY because help reached the learner
                       (help given, otherwise eligible: first attempt, item not seen before,
                       not flagged); an answer failing another rule counts on neither side
  gap       assisted - unaided, on the SAME raw scale (decision M1: the verdict's mastery is
            free of guessing and the assisted share is not, so subtracting one from the
            other would inflate the gap of weak learners). The round's verdict is reported
            NEXT TO the gap as the measure of independent performance.
            CREDIBLE_GAP        P(gap > 0.2) >= 0.8
            NO_CREDIBLE_GAP     P(gap < 0.2) >= 0.8
            INSUFFICIENT_EVIDENCE otherwise, or a side without answers      (decision M2)
  reduction gap(first round) - gap(last round)                             (decision M3)
            REDUCED             P(reduction > 0.1) >= 0.8
            NOT_REDUCED         P(reduction < 0.1) >= 0.8
            INSUFFICIENT_EVIDENCE otherwise
            with the change of each side, and the path of round statuses as a description.

Thresholds 0.2 and 0.1 are PROJECT ASSUMPTIONS (no source); validate95 reports how the
results move at other thresholds. Credibility 0.8 is the SCRUM-94 value (Bayes factor 4).

The output is a MEASUREMENT for the Diagnosis Engine: it says what the answers show, never
why, and carries no label about the learner and no recommendation.
"""
from dataclasses import dataclass, field
from functools import lru_cache

from verdict import betafn
from .betadiff import MASS, draws, gap_draws, summary

GAP_THRESHOLD = 0.2
REDUCTION_THRESHOLD = 0.1
CREDIBILITY = 0.80
MEASURE_VERSION = "eval-gap-assisted/0.1"

CREDIBLE_GAP, NO_CREDIBLE_GAP = "CREDIBLE_GAP", "NO_CREDIBLE_GAP"
REDUCED, NOT_REDUCED = "REDUCED", "NOT_REDUCED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class RoundInput:
    round: int
    intervention_id: str
    unaided: tuple                  # credits (0/1) of the counted answers, time order
    assisted: tuple                 # credits of the help-only-excluded answers
    verdict: str                    # the round's SCRUM-94 outcome
    excluded: tuple = field(default_factory=tuple)   # ((record_id, reason), ...) neither side
    unaided_records: tuple = field(default_factory=tuple)   # record ids of `unaided`, same order


def _side(credits: tuple) -> dict:
    k, n = int(round(sum(credits))), len(credits)
    a, b = k + 1, n - k + 1
    return {"correct": k, "n": n, "mean": a / (a + b),
            "interval90": [betafn.ppf((1 - MASS) / 2, a, b), betafn.ppf((1 + MASS) / 2, a, b)]}


def three_way(p_above: float, p_below: float, yes: str, no: str,
              credibility: float = CREDIBILITY) -> str:
    if p_above >= credibility:
        return yes
    if p_below >= credibility:
        return no
    return INSUFFICIENT


@lru_cache(maxsize=None)
def _gap_summary(ka, na, ku, nu, rnd, threshold):
    return summary(gap_draws(ka, na, ku, nu, rnd), threshold)


@lru_cache(maxsize=None)
def _reduction_summary(first: tuple, last: tuple, threshold):
    g1, g2 = gap_draws(*first), gap_draws(*last)
    return summary(tuple(x - y for x, y in zip(g1, g2)), threshold)


def _key(r: dict) -> tuple:
    return (r["assisted"]["correct"], r["assisted"]["n"], r["unaided"]["correct"],
            r["unaided"]["n"], r["round"])


def round_gap(r: RoundInput, threshold: float = GAP_THRESHOLD) -> dict:
    u, a = _side(r.unaided), _side(r.assisted)
    out = {"round": r.round, "intervention_id": r.intervention_id, "unaided": u, "assisted": a,
           "verdict": r.verdict, "excluded": [list(x) for x in r.excluded]}
    if u["n"] == 0 or a["n"] == 0:
        out["gap"] = {"mean": None, "interval90": None, "p_above_threshold": None,
                      "status": INSUFFICIENT,
                      "reason": "no unaided answer" if u["n"] == 0 else "no assisted answer"}
        return out
    s = _gap_summary(a["correct"], a["n"], u["correct"], u["n"], r.round, threshold)
    out["gap"] = {"mean": s["mean"], "interval90": s["interval90"],
                  "p_above_threshold": s["p_above"],
                  "status": three_way(s["p_above"], s["p_below"], CREDIBLE_GAP, NO_CREDIBLE_GAP)}
    return out


def reduction(first: dict, last: dict, threshold: float = REDUCTION_THRESHOLD) -> dict:
    out = {"first_round": first["round"], "last_round": last["round"]}
    if first["gap"]["mean"] is None or last["gap"]["mean"] is None or first is last:
        out.update({"mean": None, "interval90": None, "p_reduced": None, "status": INSUFFICIENT,
                    "unaided_change": None, "assisted_change": None})
        return out
    s = _reduction_summary(_key(first), _key(last), threshold)   # cached: counts are few
    out.update({"mean": s["mean"], "interval90": s["interval90"], "p_reduced": s["p_above"],
                "status": three_way(s["p_above"], s["p_below"], REDUCED, NOT_REDUCED),
                "unaided_change": last["unaided"]["mean"] - first["unaided"]["mean"],
                "assisted_change": last["assisted"]["mean"] - first["assisted"]["mean"]})
    return out


def measure(learner_id: str, concept_id: str, rounds: list,
            gap_threshold: float = GAP_THRESHOLD,
            reduction_threshold: float = REDUCTION_THRESHOLD) -> dict:
    """rounds: [RoundInput] -> AssistedGapMeasurement (a plain dict, JSON-ready)."""
    rs = [round_gap(r, gap_threshold) for r in sorted(rounds, key=lambda r: r.round)]
    red = reduction(rs[0], rs[-1], reduction_threshold) if rs else None
    if red is not None:
        red["status_path"] = [r["gap"]["status"] for r in rs]
    return {"measure": MEASURE_VERSION, "learner_id": learner_id, "concept_id": concept_id,
            "rounds": rs, "reduction": red,
            "thresholds": {"gap": gap_threshold, "reduction": reduction_threshold,
                           "credibility": CREDIBILITY}}
