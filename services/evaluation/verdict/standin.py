"""A Learner State stand-in, behind the interface the real module will implement.

Learner State is not implemented yet (services/learner-state/src/core is empty). The verdict
needs one thing from it: the learner's state at the moment the intervention was delivered,
with its uncertainty. This module reproduces the Learner State ORACLE
(services/learner-state/docs/verify_mastery_model.py, architecture sections 3.4-3.9) in the
standard library, so the verdict reads the same numbers the real module is specified to give.

The interface is READ-ONLY. The verdict receives a LearnerStateReader and can only ask it
for a baseline and for configuration; it has no way to send evidence back (architecture
AP-2: a verdict is never evidence). tests/test_verdict.py checks that the verdict package
never calls the stand-in's ingest method.
"""
import functools
import math
from typing import Protocol

from . import betafn
from .contracts import Baseline

# Learner State configuration (LS 3.9) - read, not re-decided
ALPHA_PRIOR = 0.6
BETA_PRIOR = 1.4
N_MAX = 30.0
KAPPA = 1.0
H_BASE = 14.0
MASTERY_THRESHOLD = 0.70
MASTERY_CREDIBILITY = 0.80
DEVELOPING_MU = 0.40
SLIP = 0.10
LEARN_RATE = 0.10
DAY = 86_400.0


class LearnerStateReader(Protocol):
    def baseline(self, learner_id: str, concept_id: str, as_of: float) -> Baseline: ...

    def config(self) -> dict: ...


# ---- the oracle's functional core, standard library ------------------------------------

def mean(a, b):
    return a / (a + b)


def decay(a, b, dt_days, h_base=H_BASE, reinforcements=0,
          a0=ALPHA_PRIOR, b0=BETA_PRIOR, kappa=KAPPA):
    """LS 3.5 - exponential reversion toward the prior."""
    if dt_days <= 0:
        return a, b
    h_eff = h_base * (1 + kappa * math.log(1 + reinforcements))
    d = 2.0 ** (-dt_days / h_eff)
    return a0 + (a - a0) * d, b0 + (b - b0) * d


def responsibility(p, correct, slip, guess):
    c = float(correct)
    q_correct = (p * (1 - slip)) / (p * (1 - slip) + (1 - p) * guess)
    q_incorrect = (p * slip) / (p * slip + (1 - p) * (1 - guess))
    if c == 1.0:
        return q_correct
    if c == 0.0:
        return q_incorrect
    return c * q_correct + (1 - c) * q_incorrect


def update(a, b, correct, weight=1.0, slip=SLIP, guess=0.25, had_instruction=False,
           learn_rate=LEARN_RATE, dt_days=0.0, reinforcements=0, n_max=N_MAX):
    """LS 3.4 - the full evidence update. Returns (alpha, beta, q)."""
    a, b = decay(a, b, dt_days, reinforcements=reinforcements)
    p = mean(a, b)
    q = responsibility(p, correct, slip, guess)
    a = a + weight * q
    b = b + weight * (1 - q)
    if had_instruction:
        n = a + b
        m = a / n
        m_star = m + (1 - m) * learn_rate
        a, b = m_star * n, (1 - m_star) * n
    n = a + b
    if n > n_max:
        r = n_max / n
        a, b = a * r, b * r
    return a, b, q


def p_above(a, b, threshold=MASTERY_THRESHOLD):
    return betafn.sf(threshold, a, b)


@functools.lru_cache(maxsize=65536)
def credible_interval(a, b, mass=0.90):
    lo = (1 - mass) / 2
    return betafn.ppf(lo, a, b), betafn.ppf(1 - lo, a, b)


# ---- the stand-in -----------------------------------------------------------------------

class LearnerStateStandIn:
    """Folds an evidence log exactly as the oracle specifies, and answers baseline reads.

    Evidence: dicts with learner_id, concept_id, occurred_at (seconds), credit, weight,
    guess_rate, had_instruction. Reinforcement counting (sessions >= 24 h apart) is not
    modelled: the simulator's pre-test is one session, so r = 0 at every baseline read.
    """
    SOURCE = "learner-state-standin(verify_mastery_model.py, stdlib)"

    def __init__(self):
        self._log = {}
        self._memo = {}

    def ingest(self, evidence: dict):
        key = (evidence["learner_id"], evidence["concept_id"])
        self._log.setdefault(key, []).append(evidence)
        self._memo.clear()

    def config(self) -> dict:
        return {"slip": SLIP, "learn_rate": LEARN_RATE, "credibility": MASTERY_CREDIBILITY,
                "mastered_mu": MASTERY_THRESHOLD, "developing_mu": DEVELOPING_MU,
                "h_base_days": H_BASE, "prior": (ALPHA_PRIOR, BETA_PRIOR)}

    def baseline(self, learner_id: str, concept_id: str, as_of: float) -> Baseline:
        """State from evidence that occurred strictly before as_of (the delivery time),
        decayed to as_of."""
        key = (learner_id, concept_id, as_of)
        if key not in self._memo:
            self._memo[key] = self._read(learner_id, concept_id, as_of)
        return self._memo[key]

    def _read(self, learner_id: str, concept_id: str, as_of: float) -> Baseline:
        a, b, last = ALPHA_PRIOR, BETA_PRIOR, None
        events = sorted(self._log.get((learner_id, concept_id), []),
                        key=lambda e: (e["occurred_at"], e.get("record_id", "")))
        for e in events:
            if e["occurred_at"] >= as_of:
                break
            dt = 0.0 if last is None else (e["occurred_at"] - last) / DAY
            a, b, _ = update(a, b, e["credit"], weight=e.get("weight", 1.0),
                             guess=e.get("guess_rate", 0.25),
                             had_instruction=e.get("had_instruction", False), dt_days=dt)
            last = e["occurred_at"]
        if last is not None:
            a, b = decay(a, b, (as_of - last) / DAY)
        return Baseline(alpha=a, beta=b, ci90=credible_interval(a, b), as_of=as_of,
                        source=self.SOURCE)


class FixedBaselineReader:
    """Returns a chosen Beta for every read: used to test mis-estimated baselines (a
    baseline deliberately too low or too high while the truth stays the same)."""

    def __init__(self, alpha: float, beta: float, inner: LearnerStateReader | None = None,
                 keep_mean_of_inner: bool = False):
        self.alpha, self.beta, self.inner = alpha, beta, inner
        self.keep_mean = keep_mean_of_inner

    def config(self) -> dict:
        return LearnerStateStandIn().config()

    def baseline(self, learner_id, concept_id, as_of) -> Baseline:
        a, b = self.alpha, self.beta
        if self.keep_mean:
            # same centre as the inner reader, precision n = alpha + beta: a STRONG baseline
            m = self.inner.baseline(learner_id, concept_id, as_of).mean
            n = self.alpha + self.beta
            a, b = m * n, (1 - m) * n
        return Baseline(alpha=a, beta=b, ci90=credible_interval(a, b), as_of=as_of,
                        source=f"fixed-baseline({a:.4f},{b:.4f})")
