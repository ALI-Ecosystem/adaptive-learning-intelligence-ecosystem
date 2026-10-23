"""The three inputs of the verdict and its output (SCRUM-94 "Define the inputs").

Conceptual contracts, not wire formats: no Adaptive Learning Engine or Evidence module exists
in code yet. Every field says which module must provide it in the real system; where the
simulator cannot provide a field, the adapter (harness/adapter94.py) fills it and the field
is listed as MISSING in the SCRUM-94 report.

Times are seconds since a fixed epoch (floats), so the core never reads a clock.
"""
from dataclasses import dataclass, field
from enum import Enum

POLICY_VERSION = "eval-verdict/0.1"


class Outcome(str, Enum):
    DEMONSTRATED = "DEMONSTRATED"
    NOT_YET_DEMONSTRATED = "NOT_YET_DEMONSTRATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Exclusion(str, Enum):
    """Why an answer does not count. The FIRST failing rule is recorded (gate order)."""
    WRONG_TARGET = "WRONG_TARGET"                # another learner / concept / level
    NOT_APPLIED = "NOT_APPLIED"                  # E1  Learner State did not apply it
    PROPAGATED = "PROPAGATED"                    # E2  inferred, not observed on this tuple
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"    # E3  no producing plan item
    IN_TREATMENT = "IN_TREATMENT"                # E4  part of the intervention itself
    BEFORE_TREATMENT_END = "BEFORE_TREATMENT_END"  # E5 not after the intervention
    AFTER_AS_OF = "AFTER_AS_OF"                  # E5  later than the moment judged
    RETENTION_WINDOW = "RETENTION_WINDOW"        # E5  at/after the retention point: SCRUM-96
    AFTER_CENSOR = "AFTER_CENSOR"                # E5  after the next treatment was delivered
    ASSISTED = "ASSISTED"                        # E6  help reached the learner before it
    NOT_FIRST_ATTEMPT = "NOT_FIRST_ATTEMPT"      # E7
    ITEM_SEEN_BEFORE = "ITEM_SEEN_BEFORE"        # E8  answered or shown earlier
    ITEM_FLAGGED = "ITEM_FLAGGED"                # E9  drift-flagged item
    NO_DIFFICULTY = "NO_DIFFICULTY"              # E10 no difficulty snapshot


@dataclass(frozen=True)
class Intervention:
    """What was delivered, to whom, and what it was meant to reach.
    Provider: the Adaptive Learning Engine (plan item + status events)."""
    intervention_id: str
    learner_id: str
    concept_id: str
    cognitive_level: str            # the tuple's level; the simulator has one level only
    intent: str                     # INSTRUCT, PRACTISE, ...
    target_mu: float                # Learner State label boundary the intent must reach
    delivered_at: float             # DELIVERED status time
    completed_at: float | None      # COMPLETED status time (None: not reported)


@dataclass(frozen=True)
class Baseline:
    """Learner State at the moment of delivery, with its uncertainty.
    Provider: Learner State, getState(asOf = delivery time)."""
    alpha: float
    beta: float
    ci90: tuple                     # (low, high) of the 90% credible interval of mastery
    as_of: float
    source: str                     # which implementation produced it

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n(self) -> float:
        return self.alpha + self.beta


@dataclass(frozen=True)
class AnswerRecord:
    """One answer, with everything needed to judge whether it is independent evidence."""
    record_id: str
    learner_id: str
    concept_id: str
    cognitive_level: str
    occurred_at: float
    item_id: str
    chosen_option: str
    credit: float                           # 1 correct, 0 incorrect, between: partial
    attempt_number: int                     # Evidence block
    help_before_answer: bool                # Evidence block: ANY help reached the learner
    producing_intervention_id: str | None   # ALE: the plan item that produced the answer
    producing_intent: str | None            # ALE: PROBE, PRACTISE, ... of that plan item
    item_b: float | None                    # Task block, snapshotted at selection
    item_b_se: float | None
    guess_rate: float = 0.25                # Evidence block itemParams.guessRate
    applied: bool = True                    # Learner State disposition
    propagated: bool = False                # Learner State: inferred along the graph
    w_correct: float = 1.0                  # Learner State weights (LS 3.4 step 4)
    w_incorrect: float = 1.0
    item_flagged: bool = False              # Evaluation offline drift monitoring


@dataclass(frozen=True)
class ItemShown:
    """An item shown to the learner without (or before) an answer: a worked example, a
    solution displayed. Provider: ALE / UI delivery log. Needed for 'seen before'."""
    learner_id: str
    item_id: str
    shown_at: float


@dataclass(frozen=True)
class Judged:
    record_id: str
    occurred_at: float
    item_id: str
    credit: float
    counted: bool
    exclusion: str | None


@dataclass
class Verdict:
    intervention_id: str
    learner_id: str
    concept_id: str
    as_of: float
    outcome: Outcome
    p_target: float | None          # belief: P(ability >= target | baseline + answers)
    bayes_factor: float | None      # evidence: posterior odds / prior odds
    prior_p_target: float           # belief before any answer
    n_counted: int
    n_excluded: int
    answers: list = field(default_factory=list)     # Judged, in time order
    reason: str = ""
    policy_version: str = POLICY_VERSION
    inputs_sha256: str = ""
    trace: list = field(default_factory=list)       # (n, status, P, BF) after each answer

    def to_dict(self) -> dict:
        return {"intervention_id": self.intervention_id, "learner_id": self.learner_id,
                "concept_id": self.concept_id, "as_of": self.as_of,
                "outcome": self.outcome.value,
                "p_target": None if self.p_target is None else round(self.p_target, 12),
                "bayes_factor": None if self.bayes_factor is None else round(self.bayes_factor, 9),
                "prior_p_target": round(self.prior_p_target, 12),
                "n_counted": self.n_counted, "n_excluded": self.n_excluded,
                "answers": [a.__dict__ for a in self.answers], "reason": self.reason,
                "policy_version": self.policy_version, "inputs_sha256": self.inputs_sha256}
