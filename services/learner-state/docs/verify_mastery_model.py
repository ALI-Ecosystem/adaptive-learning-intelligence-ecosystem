#!/usr/bin/env python3
"""
Verification script for the Learner State mastery model.

Reproduces every number in Appendix B of learner-state-architecture.md and
asserts the invariants listed in section 12.

Usage:  python3 verify_mastery_model.py
Requires: scipy, numpy
"""

import math
import numpy as np
from scipy.stats import beta as beta_dist

# ── Model configuration (§3.9) ────────────────────────────────────────────────
ALPHA_PRIOR = 0.6
BETA_PRIOR = 1.4
N_MAX = 30.0
KAPPA = 1.0
H_BASE = 14.0
MASTERY_THRESHOLD = 0.70
MASTERY_CREDIBILITY = 0.80
CONF_UNKNOWN = 0.50      # below this, we decline to label at all
DECAY_PEAK = 0.70        # peak_mastery above which DECAYED becomes possible
DECAY_NOW = 0.60         # current mean below which a once-known concept is DECAYED


# ── Functional core (§3) ──────────────────────────────────────────────────────
def mean(a, b):
    return a / (a + b)


def variance(a, b):
    n = a + b
    return (a * b) / (n * n * (n + 1))


def sd(a, b):
    return math.sqrt(variance(a, b))


def confidence(a, b, a0=ALPHA_PRIOR, b0=BETA_PRIOR):
    """
    Evidence sufficiency: the fraction of the belief that comes from observed
    evidence rather than from the prior.  conf = 1 - n0/n.

    Deliberately NOT sd-based: the sd of a Beta depends on both the evidence
    count and how extreme the mean is, so an sd-based measure would report
    higher 'confidence' for an extreme mean than for mean~0.5 on identical
    evidence.  Statistical uncertainty is reported separately, via the
    credible interval.
    """
    n0 = a0 + b0
    n = a + b
    return max(0.0, min(1.0, 1.0 - n0 / n))


def decay(a, b, dt_days, h_base=H_BASE, reinforcements=0,
          a0=ALPHA_PRIOR, b0=BETA_PRIOR, kappa=KAPPA):
    """§3.5 — exponential reversion toward the prior."""
    if dt_days <= 0:
        return a, b
    h_eff = h_base * (1 + kappa * math.log(1 + reinforcements))
    d = 2.0 ** (-dt_days / h_eff)
    return a0 + (a - a0) * d, b0 + (b - b0) * d


def responsibility(p, correct, slip, guess):
    """§3.4 step 3 — P(learner knew it | observation).

    `correct` is a credit in [0, 1]: True/1.0 = CORRECT, False/0.0 = INCORRECT,
    anything in between = PARTIAL. v0.5: credit-weighted mixture of the two
    branches; c = 1 and c = 0 reproduce the binary formulas exactly.
    """
    c = float(correct)
    q_correct = (p * (1 - slip)) / (p * (1 - slip) + (1 - p) * guess)
    q_incorrect = (p * slip) / (p * slip + (1 - p) * (1 - guess))
    if c == 1.0:
        return q_correct
    if c == 0.0:
        return q_incorrect
    return c * q_correct + (1 - c) * q_incorrect


def update(a, b, correct, weight=1.0, slip=0.10, guess=0.25,
           had_instruction=False, learn_rate=0.10, dt_days=0.0,
           reinforcements=0, n_max=N_MAX):
    """§3.4 — full evidence update. Returns (alpha, beta, q)."""
    # Step 1 — decay to the present
    a, b = decay(a, b, dt_days, reinforcements=reinforcements)
    # Step 2 — current belief
    p = mean(a, b)
    # Step 3 — responsibility
    q = responsibility(p, correct, slip, guess)
    # Step 4 — weighted Beta update
    a = a + weight * q
    b = b + weight * (1 - q)
    # Step 5 — BKT learning transition
    if had_instruction:
        n = a + b
        m = a / n
        m_star = m + (1 - m) * learn_rate
        a, b = m_star * n, (1 - m_star) * n
    # Step 6 — precision cap
    n = a + b
    if n > n_max:
        r = n_max / n
        a, b = a * r, b * r
    return a, b, q


def p_above(a, b, threshold=MASTERY_THRESHOLD):
    """P(theta > threshold) under Beta(a, b)."""
    return float(beta_dist.sf(threshold, a, b))


def credible_interval(a, b, mass=0.90):
    lo = (1 - mass) / 2
    return float(beta_dist.ppf(lo, a, b)), float(beta_dist.ppf(1 - lo, a, b))


def label(a, b, peak_mastery=0.0, misconception_active=False):
    """§3.6 — mastery label. First match wins."""
    m = mean(a, b)
    c = confidence(a, b)
    if misconception_active:
        return "MISCONCEPTION"
    # DECAYED is checked BEFORE UNKNOWN: decay lowers confidence, so a
    # previously-mastered concept that has faded would otherwise be reported
    # as UNKNOWN, discarding the fact that it was once known. "Used to know
    # it, has faded" -> review; "never knew it" -> teach. Different actions.
    if peak_mastery >= DECAY_PEAK and m < DECAY_NOW:
        return "DECAYED"
    if c < CONF_UNKNOWN:   # fewer than ~2 effective observations
        return "UNKNOWN"
    if p_above(a, b) >= MASTERY_CREDIBILITY:
        return "MASTERED"
    if m >= 0.40:
        return "DEVELOPING"
    return "NOT_MASTERED"


# ── Appendix B reproduction ───────────────────────────────────────────────────
def section(title):
    print(f"\n{title}\n" + "-" * len(title))


def main():
    print("=" * 78)
    print("Learner State mastery model — verification")
    print("=" * 78)
    print(f"Prior: Beta({ALPHA_PRIOR}, {BETA_PRIOR})  "
          f"mean={mean(ALPHA_PRIOR, BETA_PRIOR):.4f}  "
          f"sd={sd(ALPHA_PRIOR, BETA_PRIOR):.4f}  n0={ALPHA_PRIOR + BETA_PRIOR}")

    # ── B.1 evidence updates ──
    section("B.1  Evidence updates (w = 1.0, no instruction)")
    print(f"{'#':<3}{'start':<16}{'obs':<11}{'s':<7}{'g':<7}{'q':<9}"
          f"{'result':<20}{'mean':<9}{'conf':<8}")
    cases = [
        (1, 0.6, 1.4, True, 0.10, 0.25),
        (2, 0.6, 1.4, False, 0.10, 0.25),
        (3, 0.6, 1.4, True, 0.10, 0.05),
        (4, 5.0, 5.0, True, 0.10, 0.25),
        (5, 5.0, 5.0, False, 0.10, 0.25),
    ]
    for i, a, b, corr, s, g in cases:
        na, nb, q = update(a, b, corr, slip=s, guess=g)
        print(f"{i:<3}Beta({a},{b})".ljust(19)
              + f"{'correct' if corr else 'incorrect':<11}{s:<7}{g:<7}"
              + f"{q:<9.4f}({na:.4f}, {nb:.4f})".ljust(20)
              + f"  {mean(na, nb):<9.4f}{confidence(na, nb):<8.4f}")

    # ── B.2 learning transition ──
    section("B.2  Learning transition (T = 0.10) applied after case 2")
    a2, b2, _ = update(0.6, 1.4, False, slip=0.10, guess=0.25)
    n_before = a2 + b2
    a3, b3, _ = update(0.6, 1.4, False, slip=0.10, guess=0.25,
                       had_instruction=True, learn_rate=0.10)
    print(f"before: ({a2:.4f}, {b2:.4f})  mean={mean(a2, b2):.4f}  n={n_before:.4f}")
    print(f"after : ({a3:.4f}, {b3:.4f})  mean={mean(a3, b3):.4f}  n={a3 + b3:.4f}")
    assert abs((a3 + b3) - n_before) < 1e-12, "learning transition must preserve n"
    print("OK  learning transition preserves precision n")

    # ── B.3 decay ──
    section("B.3  Decay from Beta(8, 2), h_base = 14 d, r = 0")
    print(f"{'dt':<8}{'d':<10}{'alpha':<10}{'beta':<10}{'mean':<10}{'conf':<10}")
    prev_mean, prev_n = None, None
    for dt in [0, 7, 14, 30, 90, 365]:
        a, b = decay(8.0, 2.0, dt)
        d = 2.0 ** (-dt / H_BASE) if dt > 0 else 1.0
        print(f"{dt:<8}{d:<10.4f}{a:<10.4f}{b:<10.4f}"
              f"{mean(a, b):<10.4f}{confidence(a, b):<10.4f}")
        if prev_mean is not None:
            assert mean(a, b) <= prev_mean + 1e-12, "mean must decay monotonically"
            assert (a + b) <= prev_n + 1e-12, "precision must decay monotonically"
        prev_mean, prev_n = mean(a, b), a + b
    print("OK  decay is monotone in mean and precision")

    # ── B.4 spacing effect ──
    section("B.4  Spacing effect (kappa = 1.0, dt = 30 d, from Beta(8,2))")
    print(f"{'r':<6}{'h_eff':<10}{'mean@30d':<12}")
    prev = None
    for r in [0, 1, 3, 10]:
        h_eff = H_BASE * (1 + KAPPA * math.log(1 + r))
        a, b = decay(8.0, 2.0, 30, reinforcements=r)
        print(f"{r:<6}{h_eff:<10.4f}{mean(a, b):<12.4f}")
        if prev is not None:
            assert mean(a, b) > prev, "more reinforcement must slow decay"
        prev = mean(a, b)
    print("OK  reinforcement flattens the forgetting curve")

    # ── B.5 labelling ──
    section("B.5  Mastery labelling (theta* = 0.7, credibility 0.8)")
    print(f"{'state':<16}{'mean':<9}{'P(t>0.7)':<11}{'conf':<9}"
          f"{'CI90':<20}{'label':<15}")
    label_cases = [(3, 1, 0.0), (12, 3, 0.0), (1, 1, 0.0), (2, 6, 0.0),
                   (2.28, 1.54, 0.80)]   # B.3 row at 30 days, previously mastered
    for a, b, peak in label_cases:
        lo, hi = credible_interval(a, b)
        print(f"Beta({a},{b})".ljust(16)
              + f"{mean(a, b):<9.4f}{p_above(a, b):<11.4f}{confidence(a, b):<9.4f}"
              + f"[{lo:.3f}, {hi:.3f}]".ljust(20)
              + f"{label(a, b, peak_mastery=peak):<15}")

    # ── Section 12 invariants ──
    section("Section 12 — invariant checks")
    rng = np.random.default_rng(42)
    checks = 0

    # identity at dt = 0
    for _ in range(200):
        a, b = rng.uniform(0.1, 20, 2)
        assert decay(a, b, 0.0) == (a, b)
        checks += 1
    print("OK  decay(s, dt=0) is the identity")

    # full reversion
    for _ in range(200):
        a, b = rng.uniform(0.1, 20, 2)
        da, db = decay(a, b, 100000.0)
        assert abs(da - ALPHA_PRIOR) < 1e-9 and abs(db - BETA_PRIOR) < 1e-9
        checks += 1
    print("OK  decay(s, dt -> inf) reverts exactly to the prior")

    # variance grows under decay when n > n0
    for _ in range(200):
        a, b = rng.uniform(2.0, 20, 2)
        if a + b <= ALPHA_PRIOR + BETA_PRIOR:
            continue
        v0 = variance(a, b)
        da, db = decay(a, b, rng.uniform(1, 200))
        assert variance(da, db) >= v0 - 1e-12, "variance must not shrink under decay"
        checks += 1
    print("OK  decay widens the posterior (uncertainty grows)")

    # responsibility in range
    for _ in range(500):
        p = rng.uniform(0.001, 0.999)
        s = rng.uniform(0.01, 0.40)
        g = rng.uniform(0.01, 0.50)
        for corr in (True, False):
            q = responsibility(p, corr, s, g)
            assert 0.0 < q < 1.0, f"q out of range: {q}"
            checks += 1
    print("OK  responsibility q stays strictly in (0,1)")

    # directional monotonicity: correct raises the mean, incorrect lowers it
    for _ in range(500):
        a, b = rng.uniform(0.5, 15, 2)
        s = rng.uniform(0.01, 0.30)
        g = rng.uniform(0.01, 0.40)
        if s + g >= 1:
            continue
        m0 = mean(a, b)
        ca, cb, _ = update(a, b, True, slip=s, guess=g)
        ia, ib, _ = update(a, b, False, slip=s, guess=g)
        assert mean(ca, cb) > m0, "correct answer must raise the mean"
        assert mean(ia, ib) < m0, "incorrect answer must lower the mean"
        checks += 1
    print("OK  update is directionally monotone in the outcome")

    # precision cap preserves the mean
    for _ in range(200):
        a, b = rng.uniform(20, 60, 2)
        n = a + b
        if n <= N_MAX:
            continue
        r = N_MAX / n
        ca, cb = a * r, b * r
        assert abs(mean(ca, cb) - mean(a, b)) < 1e-12
        assert abs((ca + cb) - N_MAX) < 1e-12
        checks += 1
    print("OK  precision cap preserves the mean and enforces n_max")

    # alpha, beta stay positive through long random sequences
    for _ in range(200):
        a, b = ALPHA_PRIOR, BETA_PRIOR
        for _ in range(100):
            a, b, _ = update(a, b, bool(rng.integers(0, 2)),
                             weight=rng.uniform(0.1, 1.0),
                             dt_days=rng.uniform(0, 30),
                             had_instruction=bool(rng.integers(0, 2)))
            assert a > 0 and b > 0, "alpha/beta must stay positive"
            assert a + b <= N_MAX + 1e-9, "n must respect the cap"
        checks += 1
    print("OK  long sequences keep alpha,beta > 0 and n <= n_max")

    # confidence is 0 at the prior and increases with evidence
    assert abs(confidence(ALPHA_PRIOR, BETA_PRIOR)) < 1e-12
    prev_c = 0.0
    a, b = ALPHA_PRIOR, BETA_PRIOR
    for _ in range(20):
        a, b, _ = update(a, b, True, slip=0.1, guess=0.25)
        c = confidence(a, b)
        assert c >= prev_c - 1e-12, "confidence must not fall as evidence accrues"
        prev_c = c
    print("OK  confidence starts at 0 and rises monotonically with evidence")

    # confidence depends only on evidence count, not on the direction of it
    for _ in range(200):
        a, b = ALPHA_PRIOR, BETA_PRIOR
        ca, cb, _ = update(a, b, True, slip=0.1, guess=0.25)
        ia, ib, _ = update(a, b, False, slip=0.1, guess=0.25)
        assert abs(confidence(ca, cb) - confidence(ia, ib)) < 1e-12, \
            "one observation is one observation, regardless of outcome"
        checks += 1
    print("OK  confidence is outcome-independent (evidence quantity only)")

    # decay reduces confidence
    for _ in range(200):
        a, b = rng.uniform(3, 25, 2)
        c0 = confidence(a, b)
        da, db = decay(a, b, rng.uniform(1, 200))
        assert confidence(da, db) <= c0 + 1e-12, "decay must not raise confidence"
        checks += 1
    print("OK  decay reduces confidence")

    # ── v0.5: partial credit (§3.4 step 3) ──────────────────────────────
    section("v0.5  Partial credit — credit-weighted mixture")
    for _ in range(300):
        a, b = rng.uniform(0.5, 25, 2)
        g = rng.choice([0.05, 0.25, 0.5])
        hi = update(a, b, True, guess=g)
        lo = update(a, b, False, guess=g)
        assert update(a, b, 1.0, guess=g) == hi, "credit 1.0 must equal CORRECT exactly"
        assert update(a, b, 0.0, guess=g) == lo, "credit 0.0 must equal INCORRECT exactly"
        checks += 2
    print("OK  binary outcomes are bit-identical to v0.4")

    for _ in range(300):
        a, b = rng.uniform(0.5, 25, 2)
        c1, c2 = sorted(rng.uniform(0, 1, 2))
        m1 = mean(*update(a, b, c1, guess=0.05)[:2])
        m2 = mean(*update(a, b, c2, guess=0.05)[:2])
        assert m1 <= m2 + 1e-12, "more credit must never lower the mean"
        checks += 1
    print("OK  posterior mean is monotone in credit")

    # the regression that motivated the change: 20 answers at 10% credit
    a_mix = b_mix = a_old = b_old = 1.0
    for _ in range(20):
        a_mix, b_mix, _ = update(a_mix, b_mix, 0.1, guess=0.05)
        p = mean(a_old, b_old)
        q = responsibility(p, True, 0.10, 0.05)          # v0.4: correct at weight c
        a_old, b_old = a_old + 0.1 * q, b_old + 0.1 * (1 - q)
    print(f"    20 x 10% credit, open response, from Beta(1,1):  "
          f"v0.4 rule -> {mean(a_old, b_old):.3f}   mixture -> {mean(a_mix, b_mix):.3f}")
    assert mean(a_mix, b_mix) < 0.30, "consistent low credit must read as NOT_MASTERED"
    assert mean(a_old, b_old) > 0.70, "documents the v0.4 defect"
    checks += 2
    print("OK  consistent low credit drives mastery down, not up")

    print(f"\nAll invariants hold ({checks} randomised checks passed).")


if __name__ == "__main__":
    main()
