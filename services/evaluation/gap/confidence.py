"""Perceived-versus-demonstrated gap from self-reported confidence (decisions C1-C3).

For one learner, one concept, per round - on the round's UNAIDED answers that the SCRUM-94
gate counted AND that carry a reported confidence:

  perceived      expected share correct = mean of norm[c_i] over those answers
                 (gap/confnorm.py: what each rating means in a calibration cohort)
  demonstrated   share correct, posterior Beta(e*n0 + k, (1 - e)*n0 + n - k): the prior is
                 centred on NO GAP (demonstrated = perceived e) with the weight of n0 = 4
                 answers (decision C4 option C) - the conservative null, as the SCRUM-94
                 prior is centred on no change. With a flat prior ONE wrong answer at
                 confidence 5 already read as a credible gap; the proposal's own risk section
                 says a single question is not enough. Now it takes four.
  gap            perceived - demonstrated (Schraw's bias index on the norm scale), exact:
                 P(gap > d) = P(demonstrated < perceived - d) = Beta cdf
  status         PERCEIVED_ABOVE    P(gap >  0.2) >= 0.8
                 PERCEIVED_BELOW    P(gap < -0.2) >= 0.8        (both directions: C3)
                 NO_CREDIBLE_GAP    P(|gap| < 0.2) >= 0.8
                 INSUFFICIENT_EVIDENCE otherwise, or no reported answer in this round
                 NO_SELF_REPORT     the learner reported no confidence at all - perceived
                                    understanding is never invented (task requirement)
  discrimination mean confidence on correct - on incorrect answers (Schraw's discrimination
                 index): does confidence track correctness at all? Mapping-free; descriptive.
  reduction      |gap| round 1 - |gap| round 3: REDUCED if P(> 0.1) >= 0.8, NOT_REDUCED if
                 P(< 0.1) >= 0.8 (exact convolution of the two binned posteriors)

Bias and sensitivity are reported separately (Fleming & Lau 2014: correlations such as gamma
mix the two). Thresholds 0.2 / 0.1 / 0.8 as in the assisted gap (PROJECT ASSUMPTIONS).
A MEASUREMENT for the Diagnosis Engine: no label about the learner, no advice.
"""
from dataclasses import dataclass, field
from functools import lru_cache

from verdict import betafn
from .assisted import CREDIBILITY, INSUFFICIENT, NOT_REDUCED, REDUCED
from .betadiff import MASS

GAP_THRESHOLD = 0.2
REDUCTION_THRESHOLD = 0.1
MEASURE_VERSION = "eval-gap-confidence/0.1"
ABOVE, BELOW, NONE = "PERCEIVED_ABOVE", "PERCEIVED_BELOW", "NO_CREDIBLE_GAP"
NO_SELF_REPORT = "NO_SELF_REPORT"
PRIOR_WEIGHT = 4.0


@dataclass(frozen=True)
class ConfRound:
    round: int
    answers: tuple          # ((credit, confidence or None), ...) counted unaided, time order


def _discrimination(pairs):
    right = [c for k, c in pairs if k == 1]
    wrong = [c for k, c in pairs if k == 0]
    if not right or not wrong:
        return None
    return sum(right) / len(right) - sum(wrong) / len(wrong)


def _ab(k, n, e, n0):
    return e * n0 + k, (1 - e) * n0 + n - k


@lru_cache(maxsize=None)
def _exact(k: int, n: int, e: float, d: float, n0: float = PRIOR_WEIGHT) -> dict:
    a, b = _ab(k, n, e, n0)
    p_above = betafn.cdf(min(max(e - d, 0.0), 1.0), a, b)          # demonstrated < e - d
    p_below = betafn.sf(min(max(e + d, 0.0), 1.0), a, b)           # demonstrated > e + d
    lo, hi = betafn.ppf((1 - MASS) / 2, a, b), betafn.ppf((1 + MASS) / 2, a, b)
    return {"p_above": p_above, "p_below": p_below, "p_within": 1 - p_above - p_below,
            "interval90": [e - hi, e - lo], "mean": e - a / (a + b)}


def status_of(s: dict, cred: float = CREDIBILITY) -> str:
    if s["p_above"] >= cred:
        return ABOVE
    if s["p_below"] >= cred:
        return BELOW
    if s["p_within"] >= cred:
        return NONE
    return INSUFFICIENT


def round_gap(r: ConfRound, norm: dict, threshold: float = GAP_THRESHOLD,
              n0: float = PRIOR_WEIGHT) -> dict:
    rep = [(k, c) for k, c in r.answers if c is not None]
    out = {"round": r.round, "answers_counted": len(r.answers), "answers_with_confidence": len(rep),
           "discrimination": _discrimination(rep)}
    if not rep:
        out.update({"perceived": None, "demonstrated": None,
                    "gap": {"mean": None, "interval90": None, "status": INSUFFICIENT,
                            "reason": "no reported confidence in this round"}})
        return out
    k = int(round(sum(x for x, _ in rep)))
    n = len(rep)
    e = round(sum(norm[c] for _, c in rep) / n, 6)
    s = _exact(k, n, e, threshold, n0)
    a, b = _ab(k, n, e, n0)
    out.update({"perceived": {"expected_share": e, "mean_confidence": sum(c for _, c in rep) / n},
                "demonstrated": {"correct": k, "n": n, "mean": a / (a + b)},
                "gap": {"mean": s["mean"], "interval90": s["interval90"],
                        "p_above": s["p_above"], "p_below": s["p_below"], "status": status_of(s)}})
    return out


GRID = 160          # bins per posterior for the reduction (exact bin masses from the cdf)


def _bins(k, n, e, n0):
    """(|e - x| at each bin midpoint, bin mass) for the demonstrated posterior."""
    a, b = _ab(k, n, e, n0)
    cdf = [betafn.cdf(i / GRID, a, b) for i in range(GRID + 1)]
    return [(abs(e - (i + 0.5) / GRID), cdf[i + 1] - cdf[i]) for i in range(GRID)]


@lru_cache(maxsize=None)
def _reduction(k1, n1, e1, r1, k3, n3, e3, r3, d, n0=PRIOR_WEIGHT):
    """|gap| first round - |gap| last round, by exact convolution of the two binned
    posteriors (deterministic; the rounds are independent sets of answers)."""
    import bisect
    v = _bins(k1, n1, e1, n0)
    w = sorted(_bins(k3, n3, e3, n0))
    wv = [x for x, _ in w]
    cum = [0.0]
    for _, m in w:
        cum.append(cum[-1] + m)
    tot_v, tot_w = sum(m for _, m in v), cum[-1]

    def p_le(t):        # P(D1 - D3 <= t) = sum_i m_i * P(D3 >= v_i - t)
        return sum(m * (tot_w - cum[bisect.bisect_left(wv, x - t)]) for x, m in v) / (tot_v * tot_w)

    def quantile(q):
        lo, hi = -1.0, 1.0
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if p_le(mid) < q else (lo, mid)
        return (lo + hi) / 2

    mean = sum(x * m for x, m in v) / tot_v - sum(x * m for x, m in w) / tot_w
    p_red = 1 - p_le(d)
    p_not = p_le(d - 1e-12)
    return {"mean": mean, "p_reduced": p_red, "p_not": p_not,
            "interval90": [quantile((1 - MASS) / 2), quantile((1 + MASS) / 2)]}


def measure(learner_id: str, concept_id: str, rounds: list, norm: dict,
            gap_threshold: float = GAP_THRESHOLD,
            reduction_threshold: float = REDUCTION_THRESHOLD, n0: float = PRIOR_WEIGHT) -> dict:
    rounds = sorted(rounds, key=lambda r: r.round)
    out = {"measure": MEASURE_VERSION, "learner_id": learner_id, "concept_id": concept_id,
           "thresholds": {"gap": gap_threshold, "reduction": reduction_threshold,
                          "credibility": CREDIBILITY, "prior_weight": n0},
           "norm": {str(c): v for c, v in sorted(norm.items())}}
    if not any(c is not None for r in rounds for _, c in r.answers):
        out.update({"status": NO_SELF_REPORT, "rounds": [], "reduction": None})
        return out
    rs = [round_gap(r, norm, gap_threshold, n0) for r in rounds]
    first, last = rs[0], rs[-1]
    red = {"first_round": first["round"], "last_round": last["round"],
           "status_path": [r["gap"]["status"] for r in rs]}
    if first["gap"]["mean"] is None or last["gap"]["mean"] is None or first is last:
        red.update({"mean": None, "interval90": None, "p_reduced": None, "status": INSUFFICIENT})
    else:
        f, l = first, last
        s = _reduction(f["demonstrated"]["correct"], f["demonstrated"]["n"],
                       f["perceived"]["expected_share"], f["round"],
                       l["demonstrated"]["correct"], l["demonstrated"]["n"],
                       l["perceived"]["expected_share"], l["round"], reduction_threshold, n0)
        st = (REDUCED if s["p_reduced"] >= CREDIBILITY else
              NOT_REDUCED if s["p_not"] >= CREDIBILITY else INSUFFICIENT)
        red.update({"mean": s["mean"], "interval90": s["interval90"],
                    "p_reduced": s["p_reduced"], "status": st,
                    "perceived_change": l["perceived"]["expected_share"] - f["perceived"]["expected_share"],
                    "demonstrated_change": l["demonstrated"]["mean"] - f["demonstrated"]["mean"]})
    out.update({"status": "MEASURED", "rounds": rs, "reduction": red})
    return out


def answers_to_detect(pairs: tuple, norm: dict, threshold: float = GAP_THRESHOLD,
                      n0: float = PRIOR_WEIGHT):
    """How many reported answers until the gap first reads PERCEIVED_ABOVE (None: never)."""
    seen = []
    for k, c in pairs:
        if c is None:
            continue
        seen.append((k, c))
        if round_gap(ConfRound(1, tuple(seen)), norm, threshold, n0)["gap"]["status"] == ABOVE:
            return len(seen)
    return None
