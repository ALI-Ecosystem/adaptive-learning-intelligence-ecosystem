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

BY_NAME = {p.name: p for p in POPULATIONS}

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
