"""Run-level settings added for SCRUM-95. The defaults reproduce the SCRUM-93 timeline
exactly: with SimConfig() every output file is byte-identical to a SCRUM-93/94 run
(tests/test_simulator95.py checks the hashes).

  rounds          intervention -> practice -> post-test, repeated this many times on the
                  same concepts, then one delayed test (decision SCRUM-95 Q1: a FIXED number
                  of rounds for everyone, so a gap's reduction compares the same learners;
                  adaptive stopping is left as an optional robustness check)
  round_gap_days  gap between the end of one round and the next intervention, drawn per
                  learner (uniform)
  assisted_items  per concept per round: items offered WITH help, placed AFTER the unaided
                  post-test items (decision Q4 option A: added, never replacing unaided
                  items; measure alone first so help cannot leak into the unaided answers).
                  They teach nothing, like every test item.
  never_report    share of learners who never report confidence           (decision Q6 C)
  report_prob     chance of reporting, by true confidence 1..5: low confidence is skipped
                  more often, so the missing answers are NOT missing at random   (Q6 C)
All numbers are SIMULATION SETTINGS (PROJECT ASSUMPTIONS), not fitted to data.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SimConfig:
    rounds: int = 1
    round_gap_days: tuple = (0.75, 1.25)
    assisted_items: int = 0
    never_report: float = 0.0
    report_prob: tuple = (1.0, 1.0, 1.0, 1.0, 1.0)

    def __post_init__(self):
        assert self.rounds >= 1 and self.assisted_items >= 0
        assert len(self.report_prob) == 5 and 0.0 <= self.never_report <= 1.0

    @property
    def extended(self) -> bool:
        """True when any SCRUM-95 feature is on: only then do the extra fields appear."""
        return self != SimConfig()

    @property
    def masks_confidence(self) -> bool:
        return self.never_report > 0 or any(p < 1.0 for p in self.report_prob)


DEFAULT = SimConfig()
SCRUM95 = SimConfig(rounds=3, assisted_items=2, never_report=0.20,
                    report_prob=(0.40, 0.55, 0.75, 0.90, 0.95))
SCRUM95_POST_ITEMS = 8          # the SCRUM-94 choice (coverage 81% at 8 items)


def items_needed(post_items: int, cfg: SimConfig) -> int:
    return 3 + cfg.rounds * (4 + post_items + cfg.assisted_items) + 3
