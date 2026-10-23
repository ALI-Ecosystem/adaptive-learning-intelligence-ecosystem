"""The Beta distribution functions the verdict needs, in the standard library only.

Learner State's oracle (services/learner-state/docs/verify_mastery_model.py) uses scipy for
two calls: beta.sf (P(theta > x)) and beta.ppf (the 90% credible interval). This service
runs on the standard library (decision, SCRUM-94 question 5), so both are implemented here:

  inc_beta(x, a, b)   regularized incomplete beta I_x(a, b), by the continued fraction of
                      Numerical Recipes (Press et al., 3rd ed., section 6.4), evaluated with
                      the modified Lentz method
  cdf, sf             I_x(a, b) and 1 - I_x(a, b)
  ppf                 inverse of cdf by bisection: deterministic, 64 halvings

tests/test_verdict.py checks every function against scipy on a fixed table of cases when
scipy is installed (the test is skipped otherwise).
"""
import math

_EPS = 1e-15
_TINY = 1e-300
_MAX_ITER = 500


def _cont_frac(x: float, a: float, b: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _TINY else _TINY)
    h = d
    for m in range(1, _MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _TINY else _TINY)
        c = 1.0 + aa / c
        c = c if abs(c) > _TINY else _TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            return h
    raise ArithmeticError(f"incomplete beta did not converge for x={x}, a={a}, b={b}")


def inc_beta(x: float, a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        raise ValueError("a and b must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                + a * math.log(x) + b * math.log1p(-x))
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _cont_frac(x, a, b) / a
    return 1.0 - front * _cont_frac(1.0 - x, b, a) / b


def cdf(x: float, a: float, b: float) -> float:
    return inc_beta(x, a, b)


def sf(x: float, a: float, b: float) -> float:
    return 1.0 - inc_beta(x, a, b)


def ppf(q: float, a: float, b: float) -> float:
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    lo, hi = 0.0, 1.0
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if inc_beta(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
