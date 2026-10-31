"""Runs simulated learners through the fixed timeline and produces answers and truth.

Timeline (decision: same phases for everyone, gaps drawn per learner - option B):

  PRE_TEST      3 items per concept, 2 minutes apart
  INTERVENTION  5-15 minutes later; one exposure per concept (an INSTRUCT)
  PRACTICE      5-20 minutes later; 4 items per concept, 3 minutes apart, help allowed
  POST_TEST     10-60 minutes later; 3 items per concept (post_items), 2 minutes apart
  DELAYED_TEST  1-21 days later (log-uniform); 3 items per concept

SCRUM-95 (simulator/config.py; all off by default):
  * rounds > 1     INTERVENTION -> PRACTICE -> POST_TEST repeats, each round round_gap_days
                   after the previous one; the DELAYED_TEST follows the LAST round. Every
                   round is a new intervention with its own intervention_id.
  * assisted_items right after each round's unaided POST_TEST items, items answered WITH
                   help (activity POST_TEST, had_help true). They teach nothing.
  * confidence     may be missing (null) - see config.py.
SCRUM-96 (config.py; all off by default):
  * transfer_items  after each POST_TEST's unaided items (and after any assisted items) and
                    after the DELAYED_TEST's items: problems of a new kind on the same concept,
                    payload activity_type TRANSFER_PROBLEM. They teach nothing.
  * delayed_items   length of the DELAYED_TEST (3 by default)
  * explanation_share  some learners write one explanation per concept at the end of each
                    test: payload activity EXPLANATION, response_type OPEN, grade 0..1.
Round 1 uses exactly the SCRUM-93 random-number keys, so with the defaults the files are
byte-identical to SCRUM-93's.

No item is shown twice to the same learner. Only PRACTICE items are learning
opportunities; test items give no feedback, so they neither teach nor reset the forgetting
clock. (With test items teaching, most LEARNS_THEN_FORGETS learners relearned during the
delayed test itself - found by the independent review.) Times are counted from a fixed epoch in the
past, so a run never depends on the clock and the Learner Graph contract (which rejects
future times) accepts them.

Every learner runs twice on the same keyed random numbers: as himself and as his TWIN,
who gets no intervention. "Learned because of the intervention" at a checkpoint is the
truth "knows now AND the twin does not" (decision: option B of question 2 in the plan).
"""
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .concepts import CONCEPTS
from .config import DEFAULT, SimConfig, items_needed, transfer_items_needed
from .draws import Draws
from .items import BANK, ITEMS_PER_CONCEPT, TRANSFER, TRANSFER_BANK, build_bank
from .learner import DAY, Learner, explanation_grade
from .populations import POPULATIONS, SCRUM95_FIELDS, Params, learner_params

EPOCH = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
SENDER = "learner-simulator"
SCHEMA = "ali.learner-graph.update/v1"
SIM_NAMESPACE = uuid.UUID("3d6a9e52-8b1f-5c47-a2e0-5c1a7b0e9393")   # ids made by the simulator

MINUTE = 60.0
PHASE_ITEMS = (("PRE_TEST", 3), ("PRACTICE", 4), ("POST_TEST", 3), ("DELAYED_TEST", 3))
POST_ITEMS = 3      # default length of the immediate post-test (SCRUM-94 sweeps it)
CHECKPOINTS = {"POST_TEST": "immediate", "DELAYED_TEST": "delayed"}
_PARAM_DEFAULTS = Params()


def _id(seed: int, *parts) -> str:
    return str(uuid.uuid5(SIM_NAMESPACE, ":".join(map(str, (seed,) + parts))))


def _iso(t: float) -> str:
    return (EPOCH + timedelta(seconds=round(t))).isoformat()


def _sfx(r: int) -> str:
    """Key suffix of round r. Round 1 has none: it reuses the SCRUM-93 keys."""
    return "" if r == 1 else f"#{r}"


def _params_out(p: Params) -> dict:
    """Parameters for truth.jsonl. SCRUM-95 fields left at their default are omitted, so a
    SCRUM-93 population writes exactly the SCRUM-93 bytes."""
    return {k: v for k, v in asdict(p).items()
            if k not in SCRUM95_FIELDS or v != getattr(_PARAM_DEFAULTS, k)}


def plan_timeline(d: Draws, post_items: int = POST_ITEMS, bank: dict = BANK,
                  cfg: SimConfig = DEFAULT, explains: bool = False) -> tuple[list, dict]:
    """The schedule only - which item when. Behaviour comes later."""
    picks = {c.source_id: d.shuffled([it.item_id for it in bank[c.source_id]], "items", c.source_id)
             for c in CONCEPTS}
    by_id = {it.item_id: it for items in bank.values() for it in items}
    used = {cid: 0 for cid in picks}
    if cfg.transfer_items:
        tpicks = {c.source_id: d.shuffled([it.item_id for it in TRANSFER_BANK[c.source_id]],
                                          "transfer-items", c.source_id) for c in CONCEPTS}
        by_id.update({it.item_id: it for items in TRANSFER_BANK.values() for it in items})
        tused = {cid: 0 for cid in tpicks}
    events, times = [], {}
    t = d.uniform(0, 30 * DAY, "start")
    times["start"] = t

    def items_phase(phase, n, spacing, pkey=None, rnd=None, assisted=False, transfer=False):
        nonlocal t
        pkey = pkey or phase
        slots = [(c.source_id, j) for c in CONCEPTS for j in range(n)]
        times[pkey + "_start"] = t
        for cid, j in d.shuffled(slots, "order", pkey):
            if transfer:
                item = by_id[tpicks[cid][tused[cid]]]
                tused[cid] += 1
            else:
                item = by_id[picks[cid][used[cid]]]
                used[cid] += 1
            events.append({"kind": "EVIDENCE", "t": t, "phase": phase, "concept": cid,
                           "item": item, "slot": f"{pkey}:{cid}:{j}",
                           "pkey": pkey, "round": rnd, "assisted": assisted,
                           **({"transfer": True} if transfer else {})})
            t += spacing
        times[pkey + "_end"] = t - spacing

    def explanations(phase, pkey, rnd=None):
        """SCRUM-96: one written explanation per concept, graded by the Evidence module."""
        nonlocal t
        for c in CONCEPTS:
            events.append({"kind": "EXPLANATION", "t": t, "phase": phase,
                           "concept": c.source_id, "slot": f"{pkey}:{c.source_id}",
                           "pkey": pkey, "round": rnd})
            t += 3 * MINUTE

    def test_tail(phase, s, rnd=None):
        """SCRUM-96 additions at the end of a test (nothing when the features are off)."""
        if cfg.transfer_items:
            items_phase(phase, cfg.transfer_items, 2 * MINUTE, "TRANSFER_" + phase + s, rnd,
                        transfer=True)
        if explains:        # only an explaining learner spends the time (independent review)
            explanations(phase, "EXPLAIN_" + phase + s, rnd)

    items_phase("PRE_TEST", 3, 2 * MINUTE)
    for r in range(1, cfg.rounds + 1):
        s = _sfx(r)
        if r == 1:
            t += d.uniform(5, 15, "gap", "intervention") * MINUTE
        else:
            t += d.uniform(*cfg.round_gap_days, "gap", "round", r) * DAY
        times["intervention" + s] = t
        for i, c in enumerate(CONCEPTS):
            events.append({"kind": "EXPOSURE", "t": t + i, "phase": "INTERVENTION",
                           "concept": c.source_id, "slot": f"INTERVENTION{s}:{c.source_id}",
                           "round": r})
        t += d.uniform(5, 20, "gap", "practice" + s) * MINUTE
        items_phase("PRACTICE", 4, 3 * MINUTE, "PRACTICE" + s, r)
        t += d.uniform(10, 60, "gap", "post" + s) * MINUTE
        items_phase("POST_TEST", post_items, 2 * MINUTE, "POST_TEST" + s, r)
        if cfg.assisted_items:
            items_phase("POST_TEST", cfg.assisted_items, 2 * MINUTE, "ASSISTED" + s, r,
                        assisted=True)
        test_tail("POST_TEST", s, r)
    delay = d.log_uniform(1, 21, "gap", "delayed")
    times["delay_days"] = delay
    t += delay * DAY
    items_phase("DELAYED_TEST", cfg.delayed_items, 2 * MINUTE)
    test_tail("DELAYED_TEST", "")
    return events, times


def _checkpoint(real, twin, t: float, depth: bool = False) -> dict:
    """The truth a test measures: the state when the test BEGINS. Answered items are
    learning opportunities (BKT), so a test can still teach; the state at its end would
    credit learning that its own answers could not show."""
    cp = {}
    for c in CONCEPTS:
        real.apply_forgetting(c.source_id, t)
        twin.apply_forgetting(c.source_id, t)
        k, tk = real.states[c.source_id].known, twin.states[c.source_id].known
        cp[c.concept_id] = {"known": k, "twin_known": tk,
                            "learned_due_to_intervention": k and not tk,
                            "misconception": real.states[c.source_id].misconception}
        if depth:
            cp[c.concept_id]["depth"] = real.states[c.source_id].depth
    return {"at": _iso(t), "concepts": cp}


def _checkpoint_name(ev) -> str | None:
    """immediate, immediate_r2, ..., delayed - for the first unaided item of a test."""
    if ev["phase"] not in CHECKPOINTS or ev.get("assisted") or ev.get("transfer"):
        return None
    name = CHECKPOINTS[ev["phase"]]
    r = ev.get("round")
    return name if not r or r == 1 else f"{name}_r{r}"


def simulate_learner(seed: int, index: int, pop, post_items: int = POST_ITEMS,
                     bank: dict = BANK, cfg: SimConfig = DEFAULT) -> tuple[list, dict]:
    d = Draws(seed, index)
    learner_id = _id(seed, "learner", index)
    intervention_ids = {r: (_id(seed, "intervention", index) if r == 1
                            else _id(seed, "intervention", index, r))
                        for r in range(1, cfg.rounds + 1)}
    intervention_id = intervention_ids[1]
    params, learnable = learner_params(pop, d, CONCEPTS)
    misconceptions = ({c.source_id: d.choice([m.misconception_id for m in c.misconceptions],
                                             "holds", c.source_id) for c in CONCEPTS}
                      if pop.holds_misconception else {})
    explains = cfg.explanation_share > 0 and d.bernoulli(cfg.explanation_share, "explains")
    events, times = plan_timeline(d, post_items, bank, cfg, explains)
    never_reports = cfg.never_report > 0 and d.bernoulli(cfg.never_report, "never_report")

    real = Learner(params, d, with_intervention=True)
    twin = Learner(params, d, with_intervention=False)
    real.start(CONCEPTS, times["start"], misconceptions)
    twin.start(CONCEPTS, times["start"], misconceptions)
    known_at_start = {cid: st.known for cid, st in real.states.items()}

    answers, trace, checkpoints = [], [], {}
    for n, ev in enumerate(events):
        cid, t, key = ev["concept"], ev["t"], ev["slot"]
        rnd = ev.get("round") or 1
        rec_id = _id(seed, "record", index, n)
        body = {"schema": SCHEMA, "request_id": _id(seed, "request", index, n),
                "sender": SENDER, "learner_id": learner_id, "sent_at": _iso(t),
                "concept": {"concept_id": next(c.concept_id for c in CONCEPTS if c.source_id == cid)}}
        if ev["kind"] == "EXPOSURE":
            real.intervene(cid, t, key)
            twin.intervene(cid, t, key)
            body["operation"] = "ADD_EXPOSURE"
            body["record"] = {"source_record_id": rec_id, "occurred_at": _iso(t),
                              "payload": {"activity": "INTERVENTION", "kind": "INSTRUCT",
                                          "intervention_id": intervention_ids[rnd]}}
        elif ev["kind"] == "EXPLANATION":
            real.apply_forgetting(cid, t)
            twin.apply_forgetting(cid, t)
            st = real.states[cid]
            grade = explanation_grade(st, d, key)
            short = next(c.short for c in CONCEPTS if c.source_id == cid)
            body["operation"] = "ADD_EVIDENCE"
            body["record"] = {"source_record_id": rec_id, "occurred_at": _iso(t),
                              "payload": {"activity": "EXPLANATION", "response_type": "OPEN",
                                          "item_id": f"{short}-X-{ev['pkey']}",
                                          "test": ev["phase"], "grade": grade,
                                          "correct": grade >= 0.5, "chosen_option": None,
                                          "had_help": False, "attempt_number": 1,
                                          "confidence": None}}
            trace.append({"source_record_id": rec_id, "concept_source_id": cid,
                          "phase": "EXPLANATION", "known": st.known,
                          "twin_known": twin.states[cid].known, "misconception": st.misconception,
                          "path": "EXPLANATION", "depth": st.depth, "grade": grade})
        else:
            item = ev["item"]
            cp_name = _checkpoint_name(ev)
            if cp_name and abs(t - times[ev["pkey"] + "_start"]) < 1e-6:
                checkpoints[cp_name] = _checkpoint(real, twin, t, cfg.scrum96)
            real.apply_forgetting(cid, t)
            twin.apply_forgetting(cid, t)
            st, tw = real.states[cid], twin.states[cid]
            known, twin_known, mis = st.known, tw.known, st.misconception
            ans, had_help = real.answer(item, t, ev["phase"] == "PRACTICE", key,
                                        help_forced=ev.get("assisted", False))
            if ev["phase"] == "PRACTICE":
                # the twin practises the same item and gets the same help (same keyed draw);
                # the learner's own correctness matters only after HIS intervention (p_T_err)
                real.practice_opportunity(cid, t, key, had_help, ans.correct)
                twin.practice_opportunity(cid, t, key, had_help, ans.correct)
            reported = True
            if cfg.masks_confidence:
                reported = (not never_reports and
                            d.bernoulli(cfg.report_prob[ans.confidence - 1], "report", key))
            payload = {"activity": ev["phase"], "item_id": item.item_id,
                       "chosen_option": ans.chosen_option, "correct": ans.correct,
                       "had_help": had_help, "attempt_number": 1,
                       "confidence": ans.confidence if reported else None}
            if ev["phase"] == "PRACTICE":
                payload["intervention_id"] = intervention_ids[rnd]
            if item.kind == TRANSFER:
                payload["activity_type"] = TRANSFER
            body["operation"] = "ADD_EVIDENCE"
            body["record"] = {"source_record_id": rec_id, "occurred_at": _iso(t),
                              "payload": payload}
            row = {"source_record_id": rec_id, "concept_source_id": cid,
                   "phase": ev["phase"], "known": known, "twin_known": twin_known,
                   "misconception": mis, "path": ans.path}
            if cfg.extended:
                row.update({"round": ev.get("round"), "assisted": ev.get("assisted", False),
                            "had_help": had_help, "confidence_true": ans.confidence,
                            "confidence_reported": reported,
                            "confidence_boost": round(ans.boost, 6),
                            "confidence_uninflated": ans.uninflated})
            if cfg.scrum96:
                row.update({"depth": st.depth, "item_kind": item.kind})
            trace.append(row)
        answers.append(body)

    cid_to_uuid = {c.source_id: c.concept_id for c in CONCEPTS}
    truth = {
        "learner_id": learner_id, "population": pop.name, "intervention_id": intervention_id,
        "set_to_learn": [cid_to_uuid[c] for c in learnable],
        "params": {cid_to_uuid[c]: _params_out(p) for c, p in params.items()},
        "known_at_start": {cid_to_uuid[c]: v for c, v in known_at_start.items()},
        "misconceptions_at_start": {cid_to_uuid[c]: m for c, m in misconceptions.items()},
        "times": {"start": _iso(times["start"]), "intervention": _iso(times["intervention"]),
                  "delay_days": round(times["delay_days"], 4)},
        "checkpoints": checkpoints,
        "transitions": [{"at": _iso(t), "concept_id": cid_to_uuid[c], "event": e}
                        for t, c, e in real.transitions],
        "twin_transitions": [{"at": _iso(t), "concept_id": cid_to_uuid[c], "event": e}
                             for t, c, e in twin.transitions],
        "trace": [dict(r, concept_id=cid_to_uuid[r.pop("concept_source_id")]) for r in trace],
    }
    if cfg.scrum96:
        truth["explains"] = explains
    if cfg.extended:
        truth["never_reports_confidence"] = never_reports
        truth["rounds"] = [{"round": r, "intervention_id": intervention_ids[r],
                            "intervention_at": _iso(times["intervention" + _sfx(r)])}
                           for r in range(1, cfg.rounds + 1)]
    return answers, truth


def simulate(seed: int, n_per_population: int, populations=POPULATIONS,
             post_items: int = POST_ITEMS, items_per_concept: int = ITEMS_PER_CONCEPT,
             config: SimConfig = DEFAULT) -> dict:
    """Populations are assigned to learner indices by a keyed shuffle, so a learner's index
    (and the id made from it) does not run through the populations in blocks.

    post_items and items_per_concept (added for SCRUM-94) and config (SCRUM-95) default to
    the SCRUM-93 run: with the defaults every file is byte-identical to SCRUM-93's (a test
    checks the hash)."""
    used = items_needed(post_items, config)
    if used > items_per_concept:
        raise ValueError(f"{used} items per concept needed, the bank has {items_per_concept}: "
                         "no item may be shown twice")
    if transfer_items_needed(config) > len(next(iter(TRANSFER_BANK.values()))):
        raise ValueError("the transfer bank is too small: no item may be shown twice")
    bank = BANK if items_per_concept == ITEMS_PER_CONCEPT else build_bank(items_per_concept)
    slots = [(p.name, j) for p in populations for j in range(n_per_population)]
    order = Draws(seed, -2).shuffled(slots, "population-order")
    by_name = {p.name: p for p in populations}
    answers, truth = [], []
    for index, (name, _) in enumerate(order):
        a, t = simulate_learner(seed, index, by_name[name], post_items, bank, config)
        answers.extend(a)
        truth.append(t)
    answers.sort(key=lambda b: (b["record"]["occurred_at"], b["request_id"]))
    truth.sort(key=lambda t: t["learner_id"])
    out = {"seed": seed, "n_per_population": n_per_population,
           "populations": [p.name for p in populations], "answers": answers, "truth": truth,
           "post_items": post_items, "items_per_concept": items_per_concept, "bank": bank}
    if config.transfer_items:
        out["bank"] = {cid: items + TRANSFER_BANK[cid] for cid, items in bank.items()}
    if config.extended:
        out["config"] = asdict(config)
    return out
