"""Reproducible random numbers keyed by what they are for.

Every random number is a hash of (run seed, learner index, key). Nothing depends on the
order in which numbers are drawn, so:

  * the same seed gives the same run on any machine (no global random state);
  * a learner and its twin (the same learner without the intervention) use the SAME
    number for the same event. The twin differs from the learner only by the
    intervention - a perfect counterfactual, which is what makes "learned because of the
    intervention" a well-defined truth (design decision, SCRUM-93 question 2).
"""
import hashlib
import math


class Draws:
    def __init__(self, seed: int, learner_index: int):
        self._prefix = f"ali-sim|{seed}|{learner_index}|".encode()

    def u(self, *key) -> float:
        """A uniform number in [0, 1) for this key."""
        h = hashlib.sha256(self._prefix + "|".join(map(str, key)).encode()).digest()
        return (int.from_bytes(h[:8], "big") >> 11) / float(1 << 53)

    def bernoulli(self, p: float, *key) -> bool:
        return self.u(*key) < p

    def normal(self, *key) -> float:
        """Standard normal (Box-Muller)."""
        u1 = max(self.u(*key, "n1"), 1e-300)
        u2 = self.u(*key, "n2")
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def uniform(self, lo: float, hi: float, *key) -> float:
        return lo + (hi - lo) * self.u(*key)

    def log_uniform(self, lo: float, hi: float, *key) -> float:
        return math.exp(self.uniform(math.log(lo), math.log(hi), *key))

    def choice(self, seq, *key):
        seq = list(seq)
        return seq[min(int(self.u(*key) * len(seq)), len(seq) - 1)]

    def shuffled(self, seq, *key) -> list:
        """A deterministic permutation: sort by a keyed number per element."""
        return sorted(seq, key=lambda x: (self.u(*key, x), str(x)))
