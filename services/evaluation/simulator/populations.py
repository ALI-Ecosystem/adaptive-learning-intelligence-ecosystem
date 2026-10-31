"""The seven populations of SCRUM-93 and their parameters.

All numbers here are SIMULATION SETTINGS chosen to make the populations clearly different;
none is fitted to data. Parameter meanings:

  p_L0        chance of knowing the concept before the run      (BKT p(L0), Corbett 1995)
  p_T         chance of learning at each answered item           (BKT p(T))
  p_T_int     chance of learning at the intervention itself      (Corbett 1995: a rule can be
                                                                  learned from the text, before
                                                                  practice) - decision: A+C
  p_T_after   p(T) at each answered item AFTER the intervention  (decision: A+C)
  p_S         slip: a learner who knows answers wrong            (BKT p(S))
              guess is not a parameter: a learner who does not know and holds no pulling
              misconception picks one of four options at random, so p(G) = 0.25
  tau_days, d power-law forgetting: P(still known t days after the last practice)
              = (1 + t/tau)^(-d)                                  (PROJECT ASSUMPTION)
  p_help      chance of asking for help on a practice item        (PROJECT ASSUMPTION)
  p_help_correct  chance that help carries the answer to correct  (PROJECT ASSUMPTION)
  conf_bias   shift added to self-reported confidence             (PROJECT ASSUMPTION)
  p_M_known   chance a learner who knows still picks his misconception's distractor
  p_M_unknown chance a learner who does not know picks it
  p_M_remove  chance the intervention removes a held misconception

Added for SCRUM-95 (all default to "off", so every SCRUM-93 population is unchanged):
  p_T_help    chance that a PRACTICE item answered WITH help teaches the concept. 0 for
              every population except LEARNS_FROM_HELP: by default help teaches nothing
              (SCRUM-93 decision A stays) - decision SCRUM-95 Q3 option A (PROJECT ASSUMPTION)
  help_conf_boost, boost_half_life_days
              after a help, the learner's confidence on later answers of that concept is
              raised by help_conf_boost, fading by half every boost_half_life_days since the
              LATEST help (boosts do not add up: a first version summed them and confidence
              sat at the ceiling, +4 on average). Non-zero only in
              HELP_INFLATED - decision SCRUM-95 Q5 option B. The direction is anchored in
              Bassner et al. (2025): fluent AI help is read as evidence of learning; the
              size and the fading are PROJECT ASSUMPTIONS.

Added for SCRUM-96 (all default to "off", so every earlier population is unchanged):
  p_idea      when the learner comes to know a concept, the chance that what he learned is
              the IDEA (enough for a new kind of problem) rather than only the PATTERN of the
              practised problems. 1.0 everywhere except LEARNS_PATTERN, where it is 0 -
              decision SCRUM-96 Q2 option A (two levels of knowing). PROJECT ASSUMPTION.
  p_T_err     extra learning chance on a practice item answered WRONG after the
              intervention (decision SCRUM-96 Q4 option B). Li et al. (2025) report that, for
              novices, repeated practice errors were ASSOCIATED with larger gains; making the
              error a cause is a PROJECT ASSUMPTION. Only after the intervention, so the
              twin (who never gets one) is untouched and the twin coupling still holds.
  p_M_clear_on_learn
              chance that a held misconception goes away at the moment the learner comes to
              know the concept (ERRORS_THEN_LEARNS only). PROJECT ASSUMPTION.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Params:
    p_L0: float = 0.10
    p_T: float = 0.03
    p_T_int: float = 0.0
    p_T_after: float = 0.03
    p_S: float = 0.10
    tau_days: float = 20.0
    d: float = 0.5
    p_help: float = 0.20
    p_help_correct: float = 0.85
    conf_bias: float = 0.0
    p_M_known: float = 0.25
    p_M_unknown: float = 0.60
    p_M_remove: float = 0.0
    p_T_help: float = 0.0
    help_conf_boost: float = 0.0
    boost_half_life_days: float = 1.0
    p_idea: float = 1.0
    p_T_err: float = 0.0
    p_M_clear_on_learn: float = 0.0


LEARNS = Params(p_T_int=0.70, p_T_after=0.30)
NO_LEARN = Params(p_L0=0.0, p_T=0.0, p_T_int=0.0, p_T_after=0.0)


@dataclass(frozen=True)
class Population:
    name: str
    description: str
    params: Params
    partial: bool = False               # learns only some of the concepts
    holds_misconception: bool = False   # one misconception per concept at the start


POPULATIONS = (
    Population("LEARNS", "learns from the intervention and keeps it", LEARNS),
    Population("DOES_NOT_LEARN", "does not know and does not learn", NO_LEARN),
    Population("LEARNS_PARTIALLY", "learns one or two of the three concepts, never all or none",
               replace(LEARNS, p_T_int=0.80), partial=True),
    Population("LEARNS_THEN_FORGETS", "learns like LEARNS but forgets fast",
               replace(LEARNS, tau_days=1.0, d=1.0)),
    Population("CONFIDENT_RIGHT", "already knows, calibrated confidence",
               replace(LEARNS, p_L0=0.90)),
    Population("CONFIDENT_WRONG", "learns little, rates himself high, asks for help often",
               Params(p_L0=0.05, p_T=0.02, p_T_int=0.10, p_T_after=0.05,
                      conf_bias=2.5, p_help=0.70)),
    Population("HOLDS_MISCONCEPTION", "holds a misconception per concept; the intervention "
               "removes it only sometimes",
               Params(p_T_int=0.50, p_T_after=0.20, p_M_remove=0.30), holds_misconception=True),
)

# ---- SCRUM-95 populations (decisions Q2, Q3) -----------------------------------------------
# Each new population switches on ONE gap, so each measure can be tested on its own.
# They are NOT part of POPULATIONS: adding them there would reshuffle the learner order of
# every SCRUM-93/94 run. A SCRUM-95 run asks for ALL_POPULATIONS explicitly.
# Learning rates are low on purpose: over three rounds a learner gets three interventions and
# twelve practice items, and "learns a little" must stay a little (about 3 in 10 by round 3;
# with CONFIDENT_WRONG's rates it was 6 in 10).
HELP_LEARNING = Params(p_L0=0.05, p_T=0.01, p_T_int=0.03, p_T_after=0.02, p_help=0.70)

POPULATIONS_95 = (
    Population("HELP_DEPENDENT", "asks for help often, learns a little, calibrated "
               "confidence - the control for HELP_INFLATED", HELP_LEARNING),
    Population("HELP_INFLATED", "like HELP_DEPENDENT, but help raises his confidence on "
               "later answers, fading with a 1-day half-life since the latest help",
               replace(HELP_LEARNING, help_conf_boost=1.5, boost_half_life_days=1.0)),
    Population("LEARNS_FROM_HELP", "starts not knowing, asks for help often, and every helped "
               "practice item can teach him", replace(HELP_LEARNING, p_T_help=0.15)),
)

# ---- SCRUM-96 populations (decisions Q2, Q4) -----------------------------------------------
# Not part of POPULATIONS either, for the same reason. A SCRUM-96 run asks for POPULATIONS_96.
#   LEARNS_PATTERN     learns like LEARNS, but only the pattern: practised kinds of problem
#                      right, a new kind of problem (TRANSFER_PROBLEM) like a learner who
#                      does not know -> expected SHALLOW
#   ERRORS_THEN_LEARNS starts not knowing and holding a misconception that pulls hard, so
#                      practice is full of the same wrong option; every wrong practice answer
#                      after the intervention can teach, and learning clears the misconception
#                      -> expected DEMONSTRATED(_RETAINED), never MISCONCEPTION_PERSISTS
POPULATIONS_96_NEW = (
    Population("LEARNS_PATTERN", "learns from the intervention, but only the pattern of the "
               "practised problems, not the idea", replace(LEARNS, p_idea=0.0)),
    Population("ERRORS_THEN_LEARNS", "starts not knowing, repeats one misconception's option "
               "in practice, learns from those errors and drops the misconception",
               Params(p_L0=0.0, p_T=0.02, p_T_int=0.05, p_T_after=0.15, p_T_err=0.25,
                      p_M_unknown=0.85, p_M_clear_on_learn=1.0), holds_misconception=True),
)
POPULATIONS_96 = POPULATIONS + POPULATIONS_96_NEW

ALL_POPULATIONS = POPULATIONS + POPULATIONS_95
BY_NAME = {p.name: p for p in ALL_POPULATIONS + POPULATIONS_96_NEW}
# fields written to truth.jsonl only when they differ from the default, so an earlier
# population writes exactly the earlier bytes
SCRUM95_FIELDS = ("p_T_help", "help_conf_boost", "boost_half_life_days",
                  "p_idea", "p_T_err", "p_M_clear_on_learn")

JITTER = (0.75, 1.25)       # per-learner multiplier on p_T_int and p_T_after (individual BKT)


def learner_params(pop: Population, draws, concepts) -> tuple[dict, list]:
    """Per-concept parameters for one learner, and the concepts he is set to learn
    (all of them unless the population is partial). Learning rates get a per-learner
    multiplier: learners differ mostly in learning rate (Yudelson et al., as summarised by
    Abdelrahman et al. 2023)."""
    k = draws.uniform(*JITTER, "jitter")
    base = replace(pop.params, p_T_int=min(1.0, pop.params.p_T_int * k),
                   p_T_after=min(1.0, pop.params.p_T_after * k))
    ids = [c.source_id for c in concepts]
    learnable = ids
    if pop.partial:
        n = 1 + int(draws.u("partial-count") < 0.5)               # one or two concepts
        learnable = draws.shuffled(ids, "partial-which")[:n]
    per = {cid: (base if cid in learnable else NO_LEARN) for cid in ids}
    for p in per.values():
        assert p.p_T_after >= p.p_T, "twin coupling needs p_T_after >= p_T"
    return per, sorted(learnable)
