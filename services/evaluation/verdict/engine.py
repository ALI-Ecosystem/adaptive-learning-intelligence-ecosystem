"""The intervention verdict: a pure function of logged inputs (SCRUM-94 prototype).

    evaluate(intervention, reader, answers, shown, as_of) -> Verdict

1. reads the baseline from Learner State AT DELIVERY (read-only; nothing is written back);
2. passes every answer through the eligibility gate - counted, or excluded with the first
   failing rule as its reason;
3. builds the prior from the baseline and folds the counted answers in time order;
4. decides DEMONSTRATED / NOT_YET_DEMONSTRATED / INSUFFICIENT_EVIDENCE from the two
   conditions of model.status_from;
5. explains: every answer with its fate, P, BF, the prior belief, a one-line reason;
6. is deterministic: same inputs -> same verdict, and the verdict carries a SHA-256 of
   its canonical inputs.

The verdict is a MEASUREMENT. It does not estimate what the learner knows (it reads that),
does not diagnose, does not choose what comes next, and does not claim the intervention
caused anything: DEMONSTRATED means "now performs at the target unaided".
"""
import hashlib
import json
import math

from . import model
from .contracts import (POLICY_VERSION, AnswerRecord, Exclusion, Intervention, ItemShown,
                        Judged, Outcome, Verdict)

R_STAR = 0.90                   # ALE 3.8 review target -> retention point (AP-4)
DAY = 86_400.0

OUTCOME_OF = {model.SUPPORTED: Outcome.DEMONSTRATED,
              model.NOT_SUPPORTED: Outcome.NOT_YET_DEMONSTRATED,
              model.INSUFFICIENT: Outcome.INSUFFICIENT_EVIDENCE}


def treatment_end(iv: Intervention, answers: list, as_of: float) -> float:
    """COMPLETED time, or the last answer the intervention itself produced if later - only
    answers that exist at as_of: data logged after the judged moment cannot move it."""
    t = iv.completed_at if iv.completed_at is not None else iv.delivered_at
    for a in answers:
        if (a.producing_intervention_id == iv.intervention_id and a.learner_id == iv.learner_id
                and a.occurred_at <= as_of):
            t = max(t, a.occurred_at)
    return t


def retention_point(t_end: float, h_days: float) -> float:
    """t_R = h * log2(1 / R*): when LS's forgetting model says retrievability falls to the
    ALE's review target. Answers at or after it belong to RETENTION (SCRUM-96)."""
    return t_end + h_days * math.log2(1.0 / R_STAR) * DAY


def gate(iv: Intervention, answers: list, shown: list, as_of: float, h_days: float,
         censor_at: float | None = None) -> list:
    """Every answer of this learner, in time order, as Judged (counted or excluded).
    The first failing rule is the recorded reason. 'Seen before' is derived from time,
    never from arrival order: an item counts as seen if this learner answered it, or was
    shown it, strictly earlier."""
    t_end = treatment_end(iv, answers, as_of)
    t_r = retention_point(t_end, h_days)
    mine = sorted((a for a in answers if a.learner_id == iv.learner_id),
                  key=lambda a: (a.occurred_at, a.record_id))
    # first exposure of each item: answers ordered by (time, record id) - a tie at the same
    # second is broken by record id, so exactly one of two simultaneous answers is first -
    # and items shown without an answer, at their show time
    first_answer = {}
    for a in mine:
        first_answer.setdefault(a.item_id, (a.occurred_at, a.record_id))
    first_shown = {}
    for s in shown:
        if s.learner_id == iv.learner_id:
            first_shown[s.item_id] = min(first_shown.get(s.item_id, s.shown_at), s.shown_at)

    censor_pass_used = False
    out = []
    for a in mine:
        reason = None
        seen_before = (first_answer[a.item_id] < (a.occurred_at, a.record_id)
                       or first_shown.get(a.item_id, a.occurred_at) < a.occurred_at)
        if a.concept_id != iv.concept_id or a.cognitive_level != iv.cognitive_level:
            reason = Exclusion.WRONG_TARGET
        elif a.occurred_at > as_of:
            reason = Exclusion.AFTER_AS_OF          # did not exist at the judged moment
        elif not a.applied:
            reason = Exclusion.NOT_APPLIED
        elif a.propagated:
            reason = Exclusion.PROPAGATED
        elif a.producing_intervention_id is None:
            reason = Exclusion.UNKNOWN_PROVENANCE
        elif a.producing_intervention_id == iv.intervention_id:
            reason = Exclusion.IN_TREATMENT
        elif a.occurred_at <= t_end:
            reason = Exclusion.BEFORE_TREATMENT_END
        elif a.occurred_at >= t_r:
            reason = Exclusion.RETENTION_WINDOW
        elif censor_at is not None and a.occurred_at >= censor_at and (
                censor_pass_used or a.help_before_answer or a.attempt_number != 1):
            reason = Exclusion.AFTER_CENSOR
        elif a.help_before_answer:
            reason = Exclusion.ASSISTED
        elif a.attempt_number != 1:
            reason = Exclusion.NOT_FIRST_ATTEMPT
        elif seen_before:
            reason = Exclusion.ITEM_SEEN_BEFORE
        elif a.item_flagged:
            reason = Exclusion.ITEM_FLAGGED
        elif a.item_b is None or a.item_b_se is None:
            reason = Exclusion.NO_DIFFICULTY
        if (reason is None and censor_at is not None and a.occurred_at >= censor_at):
            censor_pass_used = True          # the one first answer that passes the censor
        out.append((a, reason))
    return out


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o))


def inputs_digest(iv, baseline, answers, shown, as_of, config, censor_at=None) -> str:
    payload = {"policy": POLICY_VERSION, "intervention": iv.__dict__, "censor_at": censor_at,
               "baseline": baseline.__dict__,
               "answers": sorted((a.__dict__ for a in answers),
                                 key=lambda d: (d["occurred_at"], d["record_id"])),
               "shown": sorted((s.__dict__ for s in shown),
                               key=lambda d: (d["shown_at"], d["learner_id"], d["item_id"])),
               "as_of": as_of, "config": config}
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


def prepare(iv: Intervention, reader, answers: list, shown: list, as_of: float,
            censor_at: float | None = None) -> dict:
    """Everything the decision uses: baseline at delivery, judged answers, the counted ones,
    treatment length k, the prior and the target on the ability scale."""
    cfg = reader.config()
    baseline = reader.baseline(iv.learner_id, iv.concept_id, iv.delivered_at)
    judged = [(a, r) for a, r in gate(iv, answers, shown, as_of, cfg["h_base_days"], censor_at)
              if r != Exclusion.WRONG_TARGET]      # other tuples: used only for "seen before"
    counted = [a for a, r in judged if r is None]
    # k: instructional opportunities, counted (not chosen) - the delivery itself plus every
    # answer the intervention produced on this tuple up to as_of, whatever its other flags
    k = 1 + sum(1 for a, _ in judged if a.producing_intervention_id == iv.intervention_id
                and a.occurred_at <= as_of)
    pp = model.prior_params(baseline.alpha, baseline.beta, baseline.ci90,
                            cfg["learn_rate"], k)
    return {"cfg": cfg, "baseline": baseline, "judged": judged, "counted": counted, "k": k,
            "prior": pp, "theta_t": model.logit(iv.target_mu), "censor_at": censor_at}


def evaluate(iv: Intervention, reader, answers: list, shown: list, as_of: float,
             censor_at: float | None = None, trace: bool = False) -> Verdict:
    """The prototype's entry point: intervention + Learner State reader + answers -> Verdict."""
    return decide(prepare(iv, reader, answers, shown, as_of, censor_at), iv, answers, shown,
                  as_of, trace)


def decide(ev: dict, iv: Intervention, answers: list, shown: list, as_of: float,
           trace: bool = False) -> Verdict:
    cfg, baseline, judged, counted = ev["cfg"], ev["baseline"], ev["judged"], ev["counted"]
    k, pp, theta_t = ev["k"], ev["prior"], ev["theta_t"]
    post = model.Posterior(pp["theta0"], pp["sd"])
    steps = []
    for a in counted:
        post.add(a.credit, a.item_b, a.item_b_se, a.guess_rate, cfg["slip"],
                 a.w_correct, a.w_incorrect)
        if trace:
            p, bf, _ = post.read(theta_t)
            steps.append((post.n, model.status_from(p, bf, post.n), p, bf))
    p, bf, prior_p = post.read(theta_t)
    status = model.status_from(p, bf, post.n)
    outcome = OUTCOME_OF[status]
    n_ok = sum(a.credit for a in counted)
    if not counted:
        reason = "no independent answer after the intervention"
        p_out, bf_out = None, None
    else:
        p_out, bf_out = p, bf
        cond = {model.SUPPORTED: f"BF {bf:.3g} >= 4 and P {p:.3f} > 0.5",
                model.NOT_SUPPORTED: f"BF {bf:.3g} <= 1/4 and P {p:.3f} < 0.5",
                model.INSUFFICIENT: f"BF {bf:.3g} and P {p:.3f} do not both decide"}[status]
        reason = (f"{len(counted)} independent answers ({n_ok:g} correct) against target "
                  f"mu {iv.target_mu}; baseline mu0 {baseline.mean:.3f} (n {baseline.n:.1f}), "
                  f"k {k}; {cond}")
    v = Verdict(intervention_id=iv.intervention_id, learner_id=iv.learner_id,
                concept_id=iv.concept_id, as_of=as_of, outcome=outcome, p_target=p_out,
                bayes_factor=bf_out, prior_p_target=prior_p, n_counted=len(counted),
                n_excluded=len(judged) - len(counted),
                answers=[Judged(a.record_id, a.occurred_at, a.item_id, a.credit, r is None,
                                None if r is None else r.value) for a, r in judged],
                reason=reason,
                inputs_sha256=inputs_digest(iv, baseline, answers, shown, as_of, cfg,
                                            ev["censor_at"]))
    v.trace = steps
    return v
