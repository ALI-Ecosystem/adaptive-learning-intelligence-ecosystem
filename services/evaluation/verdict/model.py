"""The statistic behind the verdict (evaluation architecture section 3.4), standard library.

Ability on the tuple is theta = logit(mu). An item of difficulty b is answered correctly with

    p(correct | theta) = g + (1 - g - s) * sigmoid((theta - b) / omega),
    omega = sqrt(1 + pi * se^2 / 8)            (item difficulty uncertainty integrated out)

Prior, built only from Learner State at delivery (the baseline):

    theta0 = logit(mu0)
    sd0    = (logit(hi) - logit(lo)) / (2 * 1.645)       [lo, hi] = LS 90% interval
    mu_k   = 1 - (1 - mu0) * (1 - T)^k                    LS's own learning model, k counted
    prior  = Normal(theta0, sd0^2 + (logit(mu_k) - theta0)^2)

centred on NO CHANGE (the conservative null), as wide as LS's uncertainty plus the distance
LS's own model says the treatment could have moved the learner.

Two numbers, both on a fixed grid (deterministic):

    P   = P(theta >= theta_t | prior + answers)          belief
    BF  = posterior odds / prior odds of theta >= theta_t   evidence from the answers alone

Status: SUPPORTED if BF >= 4 and P > 0.5; NOT_SUPPORTED if BF <= 1/4 and P < 0.5;
otherwise INSUFFICIENT. 4 = LS credibility 0.80 read as odds at an even prior.

The grid is [-12, 12] with step 0.01 (2401 points). The architecture's verification script
uses step 0.005; tests/test_verdict.py checks that this grid reproduces its Appendix B.4
minimum-evidence table exactly.
"""
import bisect
import math

Z90 = 1.6448536269514722            # standard normal 0.95 quantile
GRID_LO, GRID_HI, GRID_STEP = -12.0, 12.0, 0.01
GRID = [GRID_LO + i * GRID_STEP for i in range(int(round((GRID_HI - GRID_LO) / GRID_STEP)) + 1)]
CREDIBILITY = 0.80
BF_THRESHOLD = CREDIBILITY / (1 - CREDIBILITY)      # = 4

SUPPORTED, NOT_SUPPORTED, INSUFFICIENT = "SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT"


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


_ITEM_CACHE = {}


def item_loglik(b: float, se: float, g: float, s: float) -> tuple:
    """(log p, log(1 - p)) over the grid for one item; cached per item parameters."""
    key = (b, se, g, s)                    # exact floats: no two items share an entry
    hit = _ITEM_CACHE.get(key)
    if hit is None:
        omega = math.sqrt(1.0 + math.pi * se * se / 8.0)
        lp, lq = [], []
        for x in GRID:
            p = g + (1.0 - g - s) * _sigmoid((x - b) / omega)
            lp.append(math.log(p))
            lq.append(math.log1p(-p))
        hit = (lp, lq)
        _ITEM_CACHE[key] = hit
    return hit


def prior_params(alpha: float, beta: float, ci90: tuple, learn_rate: float, k: int) -> dict:
    mu0 = alpha / (alpha + beta)
    lo, hi = ci90
    theta0 = logit(mu0)
    sd0 = (logit(hi) - logit(lo)) / (2.0 * Z90)
    mu_k = 1.0 - (1.0 - mu0) * (1.0 - learn_rate) ** max(k, 1)
    d_t = logit(mu_k) - theta0
    return {"mu0": mu0, "theta0": theta0, "sd0": sd0, "d_t": d_t,
            "sd": math.sqrt(sd0 * sd0 + d_t * d_t), "k": max(k, 1)}


_PRIOR_CACHE = {}


def log_prior(theta0: float | None, sd: float | None) -> list:
    """Normal log density on the grid; theta0 = None gives a FLAT prior (used only by the
    no-prior comparison approach)."""
    key = (theta0, sd)                     # exact floats: a cache hit is the same prior
    hit = _PRIOR_CACHE.get(key)
    if hit is None:
        if theta0 is None:
            hit = [0.0] * len(GRID)
        else:
            hit = [-0.5 * ((x - theta0) / sd) ** 2 for x in GRID]
        if len(_PRIOR_CACHE) > 20000:
            _PRIOR_CACHE.clear()
        _PRIOR_CACHE[key] = hit
    return hit


def split_index(theta_t: float) -> int:
    """Index of the first grid point >= theta_t."""
    return bisect.bisect_left(GRID, theta_t)


def masses(logp: list, theta_t: float) -> tuple:
    """(mass at or above theta_t, mass below) of the normalised density exp(logp)."""
    m = max(logp)
    exp = math.exp
    w = [exp(v - m) for v in logp]
    i = split_index(theta_t)
    # math.fsum is correctly rounded: the same result on every Python version and machine
    # (built-in sum() of floats changed to compensated summation in Python 3.12)
    down = math.fsum(w[:i])
    up = math.fsum(w[i:])
    tot = up + down
    return up / tot, down / tot


_PRIOR_MASS = {}


class Posterior:
    """Accumulates answers one at a time over a fixed prior; reads P and BF at any point."""

    def __init__(self, theta0: float | None, sd: float | None):
        self.key = (theta0, sd)
        self.lp = log_prior(theta0, sd)
        self.ll = [0.0] * len(GRID)
        self.n = 0

    def add(self, credit: float, b: float, se: float, g: float, s: float,
            w_c: float = 1.0, w_i: float = 1.0):
        lp, lq = item_loglik(b, se, g, s)
        a1, a0 = credit * w_c, (1.0 - credit) * w_i
        ll = self.ll
        if a0 == 0.0:
            self.ll = [x + a1 * y for x, y in zip(ll, lp)]
        elif a1 == 0.0:
            self.ll = [x + a0 * y for x, y in zip(ll, lq)]
        else:
            self.ll = [x + a1 * y + a0 * z for x, y, z in zip(ll, lp, lq)]
        self.n += 1

    def read(self, theta_t: float) -> tuple:
        """(P(theta >= theta_t | data), BF, prior P)."""
        mk = (self.key, theta_t)
        pm = _PRIOR_MASS.get(mk)
        if pm is None:
            if len(_PRIOR_MASS) > 50000:
                _PRIOR_MASS.clear()
            pm = _PRIOR_MASS[mk] = masses(self.lp, theta_t)
        pr_up, pr_down = pm
        if self.n == 0:
            return pr_up, 1.0, pr_up
        po_up, po_down = masses([a + b for a, b in zip(self.lp, self.ll)], theta_t)
        prior_odds = pr_up / max(pr_down, 1e-300)
        post_odds = po_up / max(po_down, 1e-300)
        return po_up, post_odds / max(prior_odds, 1e-300), pr_up


def status_from(p_post: float, bf: float, n_obs: int) -> str:
    if n_obs == 0:
        return INSUFFICIENT
    if bf >= BF_THRESHOLD and p_post > 0.5:
        return SUPPORTED
    if bf <= 1.0 / BF_THRESHOLD and p_post < 0.5:
        return NOT_SUPPORTED
    return INSUFFICIENT
