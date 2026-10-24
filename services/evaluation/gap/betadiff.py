"""Differences of Beta posteriors, deterministic, standard library only.

A side (unaided or assisted answers of one round) with k correct of n has the posterior
Beta(k + 1, n - k + 1) under a uniform prior. The gap is a difference of two such
posteriors, the reduction a difference of two gaps; neither has a closed form, so both are
read from S keyed draws:

  * the draws for (k, n, slot) come from random.Random("scrum95|k|n|slot") - the same on
    every machine and run, so every measurement is reproducible;
  * the slot names the side AND the round ("U1", "A3"): two sides, or the same side in two
    rounds, never share draws, even when their counts are equal (shared draws would make a
    gap of equal counts exactly zero and a reduction of equal gaps certain);
  * draws are cached by (k, n, slot): counts are small, so a few hundred distinct posteriors
    serve every learner.

Monte Carlo error: with S = 20000 a probability near 0.8 has a standard error of 0.003.
The uniform prior is a PROJECT ASSUMPTION: the assisted side has no Learner State baseline,
so both sides start from the same flat prior and the gap is not tilted either way.
"""
import random
from functools import lru_cache

S = 20_000
MASS = 0.90


@lru_cache(maxsize=None)
def draws(k: int, n: int, slot: str) -> tuple:
    rng = random.Random(f"scrum95|{k}|{n}|{slot}")
    return tuple(rng.betavariate(k + 1, n - k + 1) for _ in range(S))


@lru_cache(maxsize=None)
def gap_draws(ka: int, na: int, ku: int, nu: int, rnd: int) -> tuple:
    """assisted minus unaided, round rnd."""
    a, u = draws(ka, na, f"A{rnd}"), draws(ku, nu, f"U{rnd}")
    return tuple(x - y for x, y in zip(a, u))


def summary(xs, threshold: float) -> dict:
    """mean, 90% interval, P(x > threshold), P(x < threshold) of a tuple of draws."""
    s = sorted(xs)
    n = len(s)
    lo = s[int((1 - MASS) / 2 * (n - 1))]
    hi = s[int((1 + MASS) / 2 * (n - 1))]
    above = sum(1 for x in xs if x > threshold) / n
    below = sum(1 for x in xs if x < threshold) / n
    return {"mean": sum(xs) / n, "interval90": [lo, hi], "p_above": above, "p_below": below}
