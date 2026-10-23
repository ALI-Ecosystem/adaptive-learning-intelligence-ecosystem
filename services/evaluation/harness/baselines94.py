"""The two baselines the verdict must be compared with (SCRUM-94 Validation).

1. NAIVE - "3 of the last 4 answers correct" over every answer on the concept up to the
   moment judged (the SCRUM-93 rule, harness/rules.py).

2. KNOWLEDGE TRACING, MASTERY AT 0.95 - Bayesian Knowledge Tracing (Corbett & Anderson
   1995): two states, P(L0), P(T), P(G), P(S); after each answer
       P(L | obs)  by Bayes with guess and slip,
       P(L next)   = P(L | obs) + (1 - P(L | obs)) * P(T);
   mastery when P(L) >= 0.95. The intervention exposure is one more learning opportunity
   (no observation). Four variants (decision C):

     parameters  POP     the simulator's POPULATION parameters (p_L0, p_T_int, p_T_after,
                         p_S, G = 0.25), with the true step structure (tests teach nothing).
                         Not the generating model and not an upper bound: it omits the
                         per-learner jitter, partial learners' unlearnable concepts,
                         misconception pull, forgetting and help. It does use knowledge a real
                         system lacks - the learner's population.
                 FITTED  Baum-Welch (EM) on the separate calibration run, pooled
     answers     ALL     every answer is observed, practice with help included - mastery
                         decided during practice, as in Corbett & Anderson's tutor
                 INDEP   only answers that pass the independence rules are observed; the
                         other opportunities still apply the learning transition

   A fifth, SEEDED, starts from the baseline's mean (P(L0) = mu0) with fitted T, G, S: what
   a knowledge-tracing system carrying a mis-estimated state would do.
"""
import json
import math
from collections import defaultdict
from pathlib import Path

MASTERY = 0.95


def naive_three_of_last_four(credits: list) -> bool:
    return sum(c >= 1.0 for c in credits[-4:]) >= 3


def bkt_trace(steps: list, L0: float, T: float, G: float, S: float, T_int: float | None = None,
              upto: int | None = None) -> float:
    """steps: [("EXPOSURE", None) | ("OBS", credit) | ("OPP", None)], in time order, each
    optionally with a third element: that step's own learning rate (the population-parameter variant uses it -
    test items teach nothing in the simulator). OBS = observed answer, OPP = an answer used
    only as a learning opportunity. Returns P(L) after the last step."""
    p = L0
    for step in steps[:upto]:
        kind, c = step[0], step[1]
        t_step = step[2] if len(step) > 2 else None
        if kind == "OBS":
            if c >= 1.0:
                num = p * (1 - S)
                p = num / (num + (1 - p) * G)
            else:
                num = p * S
                p = num / (num + (1 - p) * (1 - G))
            p = p + (1 - p) * (T if t_step is None else t_step)
        elif kind == "OPP":
            p = p + (1 - p) * (T if t_step is None else t_step)
        else:   # EXPOSURE
            t = t_step if t_step is not None else (T if T_int is None else T_int)
            p = p + (1 - p) * t
    return p


def fit_bkt(sequences: list, iters: int = 200, tol: float = 1e-9) -> dict:
    """Baum-Welch for standard BKT (no forgetting). sequences: lists of steps as in
    bkt_trace; EXPOSURE and OPP steps are unobserved. Deterministic start and order."""
    L0, T, G, S = 0.3, 0.1, 0.2, 0.1
    prev = -math.inf
    for _ in range(iters):
        sL0 = sT_num = sT_den = sG_num = sG_den = sS_num = sS_den = 0.0
        ll = 0.0
        for seq in sequences:
            n = len(seq)
            if n == 0:
                continue

            def emit(i, state):
                kind, c = seq[i][0], seq[i][1]
                if kind != "OBS":
                    return 1.0
                if state == 1:
                    return (1 - S) if c >= 1.0 else S
                return G if c >= 1.0 else (1 - G)
            # forward (scaled)
            a = [[0.0, 0.0] for _ in range(n)]
            sc = [0.0] * n
            a0 = [(1 - L0) * emit(0, 0), L0 * emit(0, 1)]
            sc[0] = a0[0] + a0[1]
            a[0] = [a0[0] / sc[0], a0[1] / sc[0]]
            for i in range(1, n):
                u = a[i - 1][0] * (1 - T) * emit(i, 0)
                k = (a[i - 1][0] * T + a[i - 1][1]) * emit(i, 1)
                sc[i] = u + k
                a[i] = [u / sc[i], k / sc[i]]
            ll += math.fsum(math.log(x) for x in sc)
            # backward
            b = [[1.0, 1.0] for _ in range(n)]
            for i in range(n - 2, -1, -1):
                e0, e1 = emit(i + 1, 0), emit(i + 1, 1)
                b[i][0] = ((1 - T) * e0 * b[i + 1][0] + T * e1 * b[i + 1][1]) / sc[i + 1]
                b[i][1] = (e1 * b[i + 1][1]) / sc[i + 1]
            gam = [[a[i][0] * b[i][0], a[i][1] * b[i][1]] for i in range(n)]
            for i in range(n):
                z = gam[i][0] + gam[i][1]
                gam[i] = [gam[i][0] / z, gam[i][1] / z]
            sL0 += gam[0][1]
            for i in range(n - 1):
                # expected 0 -> 1 transitions, over expected time in state 0
                xi01 = a[i][0] * T * emit(i + 1, 1) * b[i + 1][1] / sc[i + 1]
                sT_num += xi01
                sT_den += gam[i][0]
            for i in range(n):
                kind, c = seq[i][0], seq[i][1]
                if kind != "OBS":
                    continue
                if c >= 1.0:
                    sG_num += gam[i][0]
                else:
                    sS_num += gam[i][1]
                sG_den += gam[i][0]
                sS_den += gam[i][1]
        L0 = sL0 / len([s for s in sequences if s])
        T = sT_num / max(sT_den, 1e-12)
        G = min(sG_num / max(sG_den, 1e-12), 0.49)
        S = min(sS_num / max(sS_den, 1e-12), 0.49)
        if ll - prev < tol:
            break
        prev = ll
    return {"L0": L0, "T": T, "G": G, "S": S, "loglik": prev}


def oracle_params(population_params: dict) -> dict:
    """Population parameters from the simulator (Params dataclass as a dict)."""
    p = population_params
    return {"L0": p["p_L0"], "T": p["p_T_after"], "T_int": p["p_T_int"],
            "G": 0.25, "S": p["p_S"]}


def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
