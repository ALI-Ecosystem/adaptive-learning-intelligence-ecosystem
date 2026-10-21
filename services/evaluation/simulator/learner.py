"""The true state of one simulated learner, and how it changes.

The generating model is DISCRETE, in the style of BKT (Corbett & Anderson 1995): per
concept the learner either knows it or does not. Added to standard BKT:

  * forgetting  - a learner who knows can fall back to "does not know". When the learner
                  practises while knowing, a forgetting moment is drawn from a power-law
                  survival curve S(t) = (1 + t/tau)^(-d). Standard BKT has no forgetting;
                  extensions add a forget probability (Kaser et al., in Abdelrahman et al.
                  2023). The power-law form is a PROJECT ASSUMPTION (decision: option C).
  * intervention - one immediate chance to learn (p_T_int), then a higher learning rate
                  per answered item (p_T_after) (decision: A + C).
  * misconception - a separate state: it can be held whether or not the concept is known
                  (decision: option B) and the intervention removes it with p_M_remove.
  * help        - raises the chance of a correct answer on that item only; it teaches
                  nothing (decision: option A, PROJECT ASSUMPTION).
  * confidence  - 1..5, calibrated to the true state, plus noise and a per-learner bias
                  that is 0 except in CONFIDENT_WRONG (PROJECT ASSUMPTION).

The same class runs the learner and its twin (with_intervention=False). Both read the
same keyed random numbers, so they differ only through the intervention.
"""
from dataclasses import dataclass, field

from .items import OPTIONS

DAY = 86_400.0
CONF_KNOWN, CONF_UNKNOWN, CONF_NOISE_SD = 4.0, 2.2, 1.0


@dataclass
class ConceptState:
    known: bool
    misconception: str | None
    forget_at: float | None = None          # seconds since the run epoch


@dataclass
class Answer:
    chosen_option: str
    correct: bool
    confidence: int
    path: str           # truth only: KNOWS, SLIP, MISCONCEPTION, GUESS, HELP


@dataclass
class Learner:
    params: dict                         # {concept_source_id: Params}
    draws: object
    with_intervention: bool = True
    states: dict = field(default_factory=dict)
    intervened: set = field(default_factory=set)
    transitions: list = field(default_factory=list)

    # ---- setup ---------------------------------------------------------------------------
    def start(self, concepts, t0: float, misconceptions: dict):
        for c in concepts:
            p = self.params[c.source_id]
            known = self.draws.bernoulli(p.p_L0, "L0", c.source_id)
            st = ConceptState(known, misconceptions.get(c.source_id))
            self.states[c.source_id] = st
            if known:
                self._draw_forget(c.source_id, t0, "start")
                self.transitions.append((t0, c.source_id, "KNOWN_AT_START"))

    # ---- state changes -------------------------------------------------------------------
    def _draw_forget(self, cid: str, t: float, *key):
        """Forgetting moment from S(t) = (1 + t/tau)^(-d): inverse transform."""
        p = self.params[cid]
        u = max(self.draws.u("forget", cid, *key), 1e-12)
        self.states[cid].forget_at = t + p.tau_days * DAY * (u ** (-1.0 / p.d) - 1.0)

    def apply_forgetting(self, cid: str, t: float):
        st = self.states[cid]
        if st.known and st.forget_at is not None and t >= st.forget_at:
            self.transitions.append((st.forget_at, cid, "FORGOT"))
            st.known, st.forget_at = False, None

    def intervene(self, cid: str, t: float, key):
        """The intervention. The twin skips it entirely."""
        if not self.with_intervention:
            return
        self.apply_forgetting(cid, t)
        p, st = self.params[cid], self.states[cid]
        self.intervened.add(cid)
        if not st.known and self.draws.bernoulli(p.p_T_int, "T_int", cid, key):
            st.known = True
            self.transitions.append((t, cid, "LEARNED_AT_INTERVENTION"))
            self._draw_forget(cid, t, "int", key)
        # A learner who already knew keeps his forgetting moment: a fresh draw here would
        # be a draw the twin never gets, and could make the learner forget while the twin
        # remembers (found by the independent review). The intervention can only add.
        if st.misconception and self.draws.bernoulli(p.p_M_remove, "M_remove", cid, key):
            self.transitions.append((t, cid, f"MISCONCEPTION_REMOVED:{st.misconception}"))
            st.misconception = None

    def practice_opportunity(self, cid: str, t: float, key):
        """After every PRACTICE item: the BKT learning transition, and a fresh forgetting
        moment if the learner knows (practice while knowing resets the forgetting clock).
        Test items are not learning opportunities (no feedback): see generator.py.

        Twin coupling: both use the same number u for the same item, and p_T_after >= p_T,
        so whenever the twin learns (u < p_T) the learner learns too (u < p_T_after)."""
        p, st = self.params[cid], self.states[cid]
        rate = p.p_T_after if cid in self.intervened else p.p_T
        if not st.known and self.draws.bernoulli(rate, "T", cid, key):
            st.known = True
            self.transitions.append((t, cid, "LEARNED_IN_PRACTICE"))
        if st.known:
            self._draw_forget(cid, t, "practice", key)

    # ---- behaviour -----------------------------------------------------------------------
    def answer(self, item, t: float, help_allowed: bool, key) -> tuple[Answer, bool]:
        """One answer to one item at time t. Returns (answer, had_help)."""
        cid = item.concept_source_id
        self.apply_forgetting(cid, t)
        p, st, d = self.params[cid], self.states[cid], self.draws
        had_help = help_allowed and d.bernoulli(p.p_help, "help", key)
        mis_opt = item.option_for(st.misconception) if st.misconception else None
        distractors = [o for o, _ in item.distractors]

        if had_help and d.bernoulli(p.p_help_correct, "help_carries", key):
            chosen, path = item.correct_option, "HELP"
        elif st.known:
            if mis_opt and d.bernoulli(p.p_M_known, "mis_known", key):
                chosen, path = mis_opt, "MISCONCEPTION"
            elif d.bernoulli(p.p_S, "slip", key):
                chosen, path = d.choice(distractors, "slip_option", key), "SLIP"
            else:
                chosen, path = item.correct_option, "KNOWS"
        else:
            if mis_opt and d.bernoulli(p.p_M_unknown, "mis_unknown", key):
                chosen, path = mis_opt, "MISCONCEPTION"
            else:
                chosen, path = d.choice(OPTIONS, "guess", key), "GUESS"

        base = CONF_KNOWN if st.known else CONF_UNKNOWN
        raw = base + p.conf_bias + CONF_NOISE_SD * d.normal("confidence", key)
        confidence = int(min(5, max(1, round(raw))))
        return Answer(chosen, chosen == item.correct_option, confidence, path), had_help
