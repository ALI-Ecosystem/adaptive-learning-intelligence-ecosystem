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
Added for SCRUM-96 (all off by default, so SCRUM-93/94/95 files stay byte-identical):
  transfer_items  per concept, in the immediate post-test AND in the delayed test: problems
                  of a NEW KIND on the same concept, from a separate transfer bank, placed
                  after that test's ordinary unaided items (decision Q2a option A). The
                  record declares it: activity_type TRANSFER_PROBLEM - the Evaluation module
                  never judges novelty itself. Test items: they teach nothing.
  delayed_items   length of the delayed test per concept (SCRUM-93: 3; decision Q7 option B:
                  8 in the SCRUM-96 run, like the immediate post-test)
  explanation_share
                  share of learners who also write a short explanation per concept at the end
                  of each test; the simulator plays the Evidence module's grader and records
                  a grade in [0, 1] (decision Q5 option B). Reported only, never deciding.
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
    transfer_items: int = 0
    delayed_items: int = 3
    explanation_share: float = 0.0

    def __post_init__(self):
        assert self.rounds >= 1 and self.assisted_items >= 0
        assert self.transfer_items >= 0 and self.delayed_items >= 1
        assert 0.0 <= self.explanation_share <= 1.0
        assert len(self.report_prob) == 5 and 0.0 <= self.never_report <= 1.0

    @property
    def extended(self) -> bool:
        """True when any SCRUM-95 feature is on: only then do the extra fields appear."""
        return self != SimConfig()

    @property
    def scrum96(self) -> bool:
        """True when any SCRUM-96 feature is on: only then do the SCRUM-96 fields appear."""
        return (self.transfer_items, self.delayed_items, self.explanation_share) != (0, 3, 0.0)

    @property
    def masks_confidence(self) -> bool:
        return self.never_report > 0 or any(p < 1.0 for p in self.report_prob)


DEFAULT = SimConfig()
SCRUM95 = SimConfig(rounds=3, assisted_items=2, never_report=0.20,
                    report_prob=(0.40, 0.55, 0.75, 0.90, 0.95))
SCRUM95_POST_ITEMS = 8          # the SCRUM-94 choice (coverage 81% at 8 items)
SCRUM96 = SimConfig(transfer_items=4, delayed_items=8, explanation_share=0.5)
SCRUM96_POST_ITEMS = 8


def items_needed(post_items: int, cfg: SimConfig) -> int:
    return 3 + cfg.rounds * (4 + post_items + cfg.assisted_items) + cfg.delayed_items


def transfer_items_needed(cfg: SimConfig) -> int:
    """Transfer problems per concept: one set in the post-test of every round, one in the
    delayed test."""
    return (cfg.rounds + 1) * cfg.transfer_items
