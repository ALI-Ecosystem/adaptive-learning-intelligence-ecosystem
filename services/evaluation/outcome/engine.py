"""SCRUM-96: the verdict followed over time - retention, near transfer, error repetition.

    run_case(case) -> CaseResult     every version of the outcome, oldest first
    snapshot(case, as_of) -> dict    the outcome at one moment, computed from scratch

Input: the SCRUM-94 inputs (intervention, Learner State reader, answers, items shown) plus
what SCRUM-96 needs: the declared activity type of each answer (TRANSFER_PROBLEM,
EXPLANATION), the explanation grades, the item bank's option -> misconception map and a
misconception-state reader.

1. Eligibility: the SCRUM-94 gate, unchanged, with no retention cut (h = infinity): every
   answer is counted or excluded with the first failing rule. Practice answers are
   IN_TREATMENT, help, second attempts and seen items are excluded, as in SCRUM-94.
2. Each counted answer is ONE observation of ONE dimension (architecture 3.5):
     TRANSFER      the record declares a TRANSFER_PROBLEM (this module never judges novelty)
     EXPLANATION   an OPEN answer to an EXPLANATION activity - reported only
     ACQUISITION   otherwise, before the retention point t_R
     RETENTION     otherwise, at or after t_R
   and every counted multiple-choice answer on an item that carries a known misconception
   is also an ERROR_REPETITION observation of that misconception.
3. t_R = treatment end + h * log2(1 / R*), h = Learner State half-life, R* = 0.90 (AP-4,
   the SCRUM-94 engine.retention_point); a check is OVERDUE at treatment end + 2 * h *
   log2(1/R*) - retrievability R*^2 = 0.81, one review interval late.
4. ACQUISITION, RETENTION, TRANSFER: the SCRUM-94 statistic (BF + posterior against the
   case target, same prior from the baseline at delivery), each on its own observations.
5. The table (first match wins; decisions 3a): see TABLE below.
6. A new version is issued whenever the output fingerprint changes - an answer arrives, or
   time makes a check due or overdue - and every earlier version is kept (decision 6A).
7. Coverage: for each check, whether and when it happened; missing checks are listed,
   never guessed.

Nothing is written back to Learner State (architecture AP-2).
"""
import hashlib
import json
import math
from dataclasses import dataclass, field

from verdict import engine as V
from verdict import model
from verdict.contracts import Exclusion

from .misconception import Repetition, carries, chose

POLICY_VERSION = "eval-outcome/0.1 (SCRUM-96)"
TRANSFER_TYPE, EXPLANATION_TYPE = "TRANSFER_PROBLEM", "EXPLANATION"
ACQ, RET, TRF, EXP, ERR = "ACQUISITION", "RETENTION", "TRANSFER", "EXPLANATION", "ERROR_REPETITION"
SUP, NOT, INS, NA = model.SUPPORTED, model.NOT_SUPPORTED, model.INSUFFICIENT, "NOT_APPLICABLE"

NOT_EVALUABLE = "NOT_EVALUABLE"
ILLUSION = "ILLUSION_SUSPECTED"
NOT_YET = "NOT_YET_DEMONSTRATED"
NOT_RETAINED = "NOT_RETAINED"
PERSISTS = "MISCONCEPTION_PERSISTS"
SHALLOW = "SHALLOW"
RETAINED = "DEMONSTRATED_RETAINED"
DEMONSTRATED = "DEMONSTRATED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

TABLE = (   # order, condition, outcome - documented here, implemented in decide()
    (0, "baseline unavailable", NOT_EVALUABLE),
    (1, "failure alone and PERCEIVED HIGH (input from SCRUM-95; off when not given)", ILLUSION),
    (2, "failure alone", NOT_YET),
    (3, "ACQUISITION SUPPORTED and RETENTION NOT_SUPPORTED", NOT_RETAINED),
    ("3b", "(ACQUISITION or RETENTION SUPPORTED) and ERROR_REPETITION SUPPORTED", PERSISTS),
    (4, "TRANSFER NOT_SUPPORTED and (ACQUISITION or RETENTION SUPPORTED)", SHALLOW),
    (5, "RETENTION SUPPORTED", RETAINED),
    (6, "ACQUISITION SUPPORTED", DEMONSTRATED),
    (7, "otherwise", INSUFFICIENT),
)

# check states
NOT_DUE, WAITING, OVERDUE, RESOLVED, RESOLVED_LATE = (
    "NOT_DUE", "WAITING", "OVERDUE", "RESOLVED", "RESOLVED_LATE")


@dataclass
class Case:
    iv: object                      # verdict.contracts.Intervention
    reader: object                  # LearnerStateReader (read-only)
    mis_reader: object              # misconception state reader
    answers: list                   # AnswerRecord of this learner (all concepts)
    shown: list
    meta: dict                      # record_id -> {"activity_type": ..., "grade": ...}
    item_map: dict                  # item_id -> {option: misconception_id}
    horizon: float                  # last moment judged (end of the data)
    perceived: str | None = None    # "HIGH" / "NOT_HIGH" from SCRUM-95, or None
    err_scope: str = "SHOWN_WINDOWS"  # which observations error repetition reads (see _Acc)
    err_targets: str = "ALL_KNOWN"  # ALL_KNOWN or MOST_ACTIVE (the highest-mean known one)
    err_prior: str = "STATE"        # STATE: Learner State's misconception Beta at delivery;
                                    # NEUTRAL: the LS default prior (see misconception.py)


@dataclass
class CaseResult:
    versions: list = field(default_factory=list)
    observations: list = field(default_factory=list)     # (record_id, t, dimension or reason)
    t_end: float = 0.0
    t_r: float = 0.0
    overdue_at: float = 0.0
    known_misconceptions: list = field(default_factory=list)

    @property
    def final(self) -> dict:
        return self.versions[-1]


# ---- preparation -----------------------------------------------------------------------------

def prepare(case: Case) -> dict:
    iv = case.iv
    cfg = case.reader.config()
    base = V.prepare(iv, case.reader, case.answers, case.shown, case.horizon)   # prior, k, theta_t
    judged = [(a, r) for a, r in V.gate(iv, case.answers, case.shown, case.horizon, math.inf)
              if r != Exclusion.WRONG_TARGET]
    t_end = V.treatment_end(iv, case.answers, case.horizon)
    t_r = V.retention_point(t_end, cfg["h_base_days"])
    overdue = t_end + 2.0 * (t_r - t_end)
    mis = case.mis_reader.state(iv.learner_id, iv.concept_id, case.answers, iv.delivered_at)
    known = sorted(m for m, (_, _, k) in mis.items() if k)
    if known and case.err_targets == "MOST_ACTIVE":
        mean = lambda m: mis[m][0] / (mis[m][0] + mis[m][1])
        known = [max(known, key=lambda m: (mean(m), mis[m][0], m))]
    obs = []
    for a, r in judged:
        kind = (case.meta.get(a.record_id) or {}).get("activity_type")
        if r is not None:
            obs.append((a, None, r.value))
            continue
        if kind == EXPLANATION_TYPE:
            dim = EXP
        elif kind == TRANSFER_TYPE:
            dim = TRF
        else:
            dim = ACQ if a.occurred_at < t_r else RET
        obs.append((a, dim, None))
    return {"base": base, "obs": obs, "t_end": t_end, "t_r": t_r, "overdue": overdue,
            "mis": mis, "known": known}


# ---- the decision ----------------------------------------------------------------------------

def _err_status(reps: dict) -> str:
    if not reps:
        return NA
    st = [r["status"] for r in reps.values()]
    if SUP in st:
        return SUP
    if all(s == NOT for s in st):
        return NOT
    return INS


def decide(dims: dict, err: str, perceived: str | None, evaluable: bool = True) -> tuple:
    """(rule, outcome) from dimension statuses. First match wins."""
    a, r, t = dims[ACQ]["status"], dims[RET]["status"], dims[TRF]["status"]
    if not evaluable:
        return 0, NOT_EVALUABLE
    failure_alone = (a == NOT and r != SUP) or (a == INS and r == NOT)
    if failure_alone and perceived == "HIGH":
        return 1, ILLUSION
    if failure_alone:
        return 2, NOT_YET
    if a == SUP and r == NOT:
        return 3, NOT_RETAINED
    shown_once = a == SUP or r == SUP
    if shown_once and err == SUP:
        return "3b", PERSISTS
    if t == NOT and shown_once:
        return 4, SHALLOW
    if r == SUP:
        return 5, RETAINED
    if a == SUP:
        return 6, DEMONSTRATED
    return 7, INSUFFICIENT


def confidence(rule, dims: dict, reps: dict) -> float | None:
    """Architecture 3.6: P of the deciding dimension (1 - P for a NOT_SUPPORTED rule); the
    smaller of the two for a two-condition rule; None for rules 0 and 7."""
    pa, pr, pt = (dims[d]["p"] for d in (ACQ, RET, TRF))
    shown = max(p for p, d in ((pa, ACQ), (pr, RET)) if dims[d]["status"] == SUP) \
        if SUP in (dims[ACQ]["status"], dims[RET]["status"]) else None
    if rule == 2:
        return 1 - (pa if dims[ACQ]["status"] == NOT else pr)
    if rule == 1:
        return 1 - (pa if dims[ACQ]["status"] == NOT else pr)
    if rule == 3:
        return min(pa, 1 - pr)
    if rule == "3b":
        pe = max(x["p_persists"] for x in reps.values() if x["status"] == SUP)
        return min(shown, pe)
    if rule == 4:
        return min(shown, 1 - pt)
    if rule == 5:
        return pr
    if rule == 6:
        return pa
    return None


def _checks(state: dict, at: float, t_end: float, t_r: float, overdue: float,
            has_err: bool) -> list:
    """Every check with its due / overdue times and where it stands at `at`."""
    spec = [(ACQ, t_end, t_r), (RET, t_r, overdue), (TRF, t_end, overdue)]
    if has_err:
        spec.append((ERR, t_end, overdue))
    out = []
    for dim, due, late in spec:
        first = state.get(dim)
        if first is not None:
            st = RESOLVED if first < late else RESOLVED_LATE   # at `late` it is overdue
        elif at < due:
            st = NOT_DUE
        elif at < late:
            st = WAITING
        else:
            st = OVERDUE
        out.append({"dimension": dim, "due_from": due, "overdue_at": late, "state": st,
                    "first_observed_at": first})
    return out


def _fingerprint(out: dict) -> str:
    q = {"outcome": out["outcome"], "rule": str(out["rule"]),
         "dims": {d: (v["status"], v["n"]) for d, v in out["dimensions"].items()},
         "err": {m: (v["status"], v["n"], v["picks"]) for m, v in out["error_repetition"].items()},
         "exp": (out["explanation"]["n"], out["explanation"]["mean_grade"]),
         "checks": [(c["dimension"], c["state"]) for c in out["checks"]]}
    return hashlib.sha256(json.dumps(q, sort_keys=True).encode()).hexdigest()


class _Acc:
    """Running state of one case: one posterior per dimension, one Repetition per known
    misconception, explanation grades, first observation time per check."""

    def __init__(self, prep: dict, case: Case):
        b = prep["base"]
        self.case, self.prep = case, prep
        self.cfg, self.theta_t = b["cfg"], b["theta_t"]
        self.post = {d: model.Posterior(b["prior"]["theta0"], b["prior"]["sd"])
                     for d in (ACQ, RET, TRF)}
        self.read = {d: self._read(d) for d in (ACQ, RET, TRF)}
        # error-repetition observations per known misconception and per window
        self.rep_obs = {m: {ACQ: [0, 0], RET: [0, 0], TRF: [0, 0]} for m in prep["known"]}
        self.rep_first = {ACQ: None, RET: None, TRF: None}   # first discriminating obs per window
        from .misconception import PRIOR
        self.reps = {m: Repetition(m, *(prep["mis"][m][:2] if case.err_prior == "STATE" else PRIOR))
                     for m in prep["known"]}
        self.rep_read = {m: r.read() for m, r in self.reps.items()}
        self.grades = []
        self.first = {}

    def _read(self, d):
        p, bf, prior_p = self.post[d].read(self.theta_t)
        n = self.post[d].n
        return {"status": model.status_from(p, bf, n), "n": n,
                "p": p if n else None, "bayes_factor": bf if n else None,
                "prior_p": prior_p}

    def add(self, a, dim):
        if dim == EXP:
            self.grades.append((self.case.meta.get(a.record_id) or {}).get("grade", a.credit))
            self.first.setdefault(EXP, a.occurred_at)
            return
        p = self.post[dim]
        p.add(a.credit, a.item_b, a.item_b_se, a.guess_rate, self.cfg["slip"],
              a.w_correct, a.w_incorrect)
        self.read[dim] = self._read(dim)
        self.first.setdefault(dim, a.occurred_at)
        for m in self.reps:
            if carries(self.case.item_map, a.item_id, m):
                o = self.rep_obs[m][dim]
                o[0] += 1
                o[1] += chose(self.case.item_map, a.item_id, a.chosen_option, m)
                if self.rep_first[dim] is None:
                    self.rep_first[dim] = a.occurred_at
        self._refresh_reps()

    def _refresh_reps(self):
        """Error repetition reads the observations of the windows in which the learner
        DEMONSTRATED the target (scope SHOWN_WINDOWS): its threshold r0 = slip / 3 is the
        rate of a learner who knows, so only answers from where he performs at the target
        can test it. A guess on a failed transfer problem or after forgetting picks a given
        distractor a quarter of the time, misconception or not (found on the first run:
        LEARNS_PATTERN learners came out MISCONCEPTION_PERSISTS from their transfer
        guesses). Scope ALL reads every window (kept for comparison)."""
        if self.case.err_scope == "ALL":
            windows = (ACQ, RET, TRF)
        else:
            windows = tuple(d for d in (ACQ, RET) if self.read[d]["status"] == SUP)
        for m, r in self.reps.items():
            r.n = sum(self.rep_obs[m][w][0] for w in windows)
            r.picks = sum(self.rep_obs[m][w][1] for w in windows)
            self.rep_read[m] = dict(r.read(), windows=list(windows))
        # the check counts as observed only through observations IN SCOPE (independent review:
        # it was marked RESOLVED from out-of-scope answers while the measure had n = 0)
        ts = [self.rep_first[w] for w in windows if self.rep_first[w] is not None]
        if ts:
            self.first[ERR] = min(ts)
        else:
            self.first.pop(ERR, None)

    def output(self, at: float) -> dict:
        dims = {d: dict(v) for d, v in self.read.items()}
        err = _err_status(self.rep_read)
        evaluable = self.prep["base"]["baseline"] is not None
        rule, outcome = decide(dims, err, self.case.perceived, evaluable)
        g = self.grades
        out = {"as_of": at, "outcome": outcome, "rule": rule,
               "confidence": confidence(rule, dims, self.rep_read),
               "dimensions": dims, "error_repetition_status": err,
               "error_repetition": {m: dict(v) for m, v in self.rep_read.items()},
               "explanation": {"n": len(g), "mean_grade": round(sum(g) / len(g), 3) if g else None,
                               "role": "reported only, never in the table"},
               "checks": _checks(self.first, at, self.prep["t_end"], self.prep["t_r"],
                                 self.prep["overdue"], bool(self.reps))}
        out["missing"] = [c for c in out["checks"] if c["state"] in (NOT_DUE, WAITING, OVERDUE)]
        return out


# ---- entry points ----------------------------------------------------------------------------

def _late_treatment(case: Case, prep: dict) -> bool:
    """True when an answer of the intervention itself arrives after an answer on the tuple
    that is NOT part of it: then the treatment end, k and the gate change over time, and
    every version must be a fresh evaluation (independent review). Never the case in the
    simulator's data (practice comes before every test)."""
    iv = case.iv
    mine = [a for a in case.answers if a.learner_id == iv.learner_id
            and a.concept_id == iv.concept_id and a.occurred_at > iv.delivered_at]
    other = [a.occurred_at for a in mine if a.producing_intervention_id != iv.intervention_id]
    own = [a.occurred_at for a in mine if a.producing_intervention_id == iv.intervention_id]
    return bool(other and own) and max(own) > min(other)


def run_case(case: Case) -> CaseResult:
    """Every version, oldest first. Events: each answer on the tuple after delivery (in time
    order; answers at the SAME moment are one event) and the TIME points t_R (acquisition
    overdue, retention due) and the overdue point; version 1 is issued at the treatment end.
    Each version equals snapshot() at its moment: incrementally when the data allow it,
    by a fresh evaluation otherwise."""
    prep = prepare(case)
    if _late_treatment(case, prep):
        return _run_fresh(case, prep)
    acc = _Acc(prep, case)
    res = CaseResult(t_end=prep["t_end"], t_r=prep["t_r"], overdue_at=prep["overdue"],
                     known_misconceptions=prep["known"])
    res.observations = [(a.record_id, a.occurred_at, dim or reason) for a, dim, reason in prep["obs"]]
    events = [(a.occurred_at, 0, a.record_id, a, dim) for a, dim, _ in prep["obs"]
              if dim is not None and a.occurred_at > prep["t_end"]]
    for t, label in ((prep["t_r"], "TIME:RETENTION_DUE"), (prep["overdue"], "TIME:OVERDUE")):
        if t <= case.horizon:
            events.append((t, 1, label, None, None))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    def issue(at, trigger):
        out = acc.output(at)
        fp = _fingerprint(out)
        if res.versions and res.versions[-1]["fingerprint"] == fp:
            return
        out.update({"version": len(res.versions) + 1, "trigger": trigger, "fingerprint": fp,
                    "previous": res.versions[-1]["version"] if res.versions else None,
                    "policy_version": POLICY_VERSION})
        res.versions.append(out)

    issue(prep["t_end"], "TREATMENT_END")
    i = 0
    while i < len(events):
        t, kind, label = events[i][0], events[i][1], events[i][2]
        if kind == 0:                       # every answer at this moment, then one version
            while i < len(events) and events[i][0] == t and events[i][1] == 0:
                acc.add(events[i][3], events[i][4])
                i += 1
            issue(t, f"ANSWER:{label}")
        else:
            issue(t, label)
            i += 1
    return res


def _run_fresh(case: Case, prep: dict) -> CaseResult:
    """The slow path: every version from snapshot() at its moment."""
    res = CaseResult(t_end=prep["t_end"], t_r=prep["t_r"], overdue_at=prep["overdue"],
                     known_misconceptions=prep["known"])
    res.observations = [(a.record_id, a.occurred_at, dim or reason) for a, dim, reason in prep["obs"]]
    times = sorted({a.occurred_at for a in case.answers
                    if a.learner_id == case.iv.learner_id and a.concept_id == case.iv.concept_id
                    and a.occurred_at > case.iv.delivered_at} | {prep["t_r"], prep["overdue"]})
    for t in [x for x in times if x <= case.horizon]:
        out = snapshot(case, t)
        fp = _fingerprint(out)
        if res.versions and res.versions[-1]["fingerprint"] == fp:
            continue
        out.update({"version": len(res.versions) + 1, "trigger": f"FRESH@{t:.0f}",
                    "fingerprint": fp, "policy_version": POLICY_VERSION,
                    "previous": res.versions[-1]["version"] if res.versions else None})
        res.versions.append(out)
    return res


def snapshot(case: Case, as_of: float) -> dict:
    """The outcome at `as_of`, computed from scratch on the data that existed at `as_of`
    (horizon = as_of: a later record cannot change it). Used to check that the incremental
    versions are exactly what a fresh evaluation would give."""
    from dataclasses import replace
    case = replace(case, horizon=as_of)
    prep = prepare(case)
    acc = _Acc(prep, case)
    for a, dim, _ in sorted(prep["obs"], key=lambda o: (o[0].occurred_at, o[0].record_id)):
        if dim is not None and prep["t_end"] < a.occurred_at <= as_of:
            acc.add(a, dim)
    return acc.output(as_of)
