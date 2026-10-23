"""Runs simulated learners through the fixed timeline and produces answers and truth.

Timeline (decision: same phases for everyone, gaps drawn per learner - option B):

  PRE_TEST      3 items per concept, 2 minutes apart
  INTERVENTION  5-15 minutes later; one exposure per concept (an INSTRUCT)
  PRACTICE      5-20 minutes later; 4 items per concept, 3 minutes apart, help allowed
  POST_TEST     10-60 minutes later; 3 items per concept (post_items), 2 minutes apart
  DELAYED_TEST  1-21 days later (log-uniform); 3 items per concept

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
from .draws import Draws
from .items import BANK, ITEMS_PER_CONCEPT, build_bank
from .learner import DAY, Learner
from .populations import POPULATIONS, learner_params

EPOCH = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
SENDER = "learner-simulator"
SCHEMA = "ali.learner-graph.update/v1"
SIM_NAMESPACE = uuid.UUID("3d6a9e52-8b1f-5c47-a2e0-5c1a7b0e9393")   # ids made by the simulator

MINUTE = 60.0
PHASE_ITEMS = (("PRE_TEST", 3), ("PRACTICE", 4), ("POST_TEST", 3), ("DELAYED_TEST", 3))
POST_ITEMS = 3      # default length of the immediate post-test (SCRUM-94 sweeps it)
CHECKPOINTS = {"POST_TEST": "immediate", "DELAYED_TEST": "delayed"}


def _id(seed: int, *parts) -> str:
    return str(uuid.uuid5(SIM_NAMESPACE, ":".join(map(str, (seed,) + parts))))


def _iso(t: float) -> str:
    return (EPOCH + timedelta(seconds=round(t))).isoformat()


def plan_timeline(d: Draws, post_items: int = POST_ITEMS, bank: dict = BANK) -> tuple[list, dict]:
    """The schedule only - which item when. Behaviour comes later."""
    picks = {c.source_id: d.shuffled([it.item_id for it in bank[c.source_id]], "items", c.source_id)
             for c in CONCEPTS}
    by_id = {it.item_id: it for items in bank.values() for it in items}
    used = {cid: 0 for cid in picks}
    events, times = [], {}
    t = d.uniform(0, 30 * DAY, "start")
    times["start"] = t

    def items_phase(phase, n, spacing):
        nonlocal t
        slots = [(c.source_id, j) for c in CONCEPTS for j in range(n)]
        times[phase + "_start"] = t
        for cid, j in d.shuffled(slots, "order", phase):
            item = by_id[picks[cid][used[cid]]]
            used[cid] += 1
            events.append({"kind": "EVIDENCE", "t": t, "phase": phase, "concept": cid,
                           "item": item, "slot": f"{phase}:{cid}:{j}"})
            t += spacing
        times[phase + "_end"] = t - spacing

    items_phase("PRE_TEST", 3, 2 * MINUTE)
    t += d.uniform(5, 15, "gap", "intervention") * MINUTE
    times["intervention"] = t
    for i, c in enumerate(CONCEPTS):
        events.append({"kind": "EXPOSURE", "t": t + i, "phase": "INTERVENTION",
                       "concept": c.source_id, "slot": f"INTERVENTION:{c.source_id}"})
    t += d.uniform(5, 20, "gap", "practice") * MINUTE
    items_phase("PRACTICE", 4, 3 * MINUTE)
    t += d.uniform(10, 60, "gap", "post") * MINUTE
    items_phase("POST_TEST", post_items, 2 * MINUTE)
    delay = d.log_uniform(1, 21, "gap", "delayed")
    times["delay_days"] = delay
    t += delay * DAY
    items_phase("DELAYED_TEST", 3, 2 * MINUTE)
    return events, times


def _checkpoint(real, twin, t: float) -> dict:
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
    return {"at": _iso(t), "concepts": cp}


def simulate_learner(seed: int, index: int, pop, post_items: int = POST_ITEMS,
                     bank: dict = BANK) -> tuple[list, dict]:
    d = Draws(seed, index)
    learner_id = _id(seed, "learner", index)
    intervention_id = _id(seed, "intervention", index)
    params, learnable = learner_params(pop, d, CONCEPTS)
    misconceptions = ({c.source_id: d.choice([m.misconception_id for m in c.misconceptions],
                                             "holds", c.source_id) for c in CONCEPTS}
                      if pop.holds_misconception else {})
    events, times = plan_timeline(d, post_items, bank)

    real = Learner(params, d, with_intervention=True)
    twin = Learner(params, d, with_intervention=False)
    real.start(CONCEPTS, times["start"], misconceptions)
    twin.start(CONCEPTS, times["start"], misconceptions)
    known_at_start = {cid: st.known for cid, st in real.states.items()}

    answers, trace, checkpoints = [], [], {}
    for n, ev in enumerate(events):
        cid, t, key = ev["concept"], ev["t"], ev["slot"]
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
                                          "intervention_id": intervention_id}}
        else:
            item = ev["item"]
            if ev["phase"] in CHECKPOINTS and abs(t - times[ev["phase"] + "_start"]) < 1e-6:
                checkpoints[CHECKPOINTS[ev["phase"]]] = _checkpoint(real, twin, t)
            real.apply_forgetting(cid, t)
            twin.apply_forgetting(cid, t)
            st, tw = real.states[cid], twin.states[cid]
            known, twin_known, mis = st.known, tw.known, st.misconception
            ans, had_help = real.answer(item, t, ev["phase"] == "PRACTICE", key)
            if ev["phase"] == "PRACTICE":
                real.practice_opportunity(cid, t, key)
                twin.practice_opportunity(cid, t, key)
            payload = {"activity": ev["phase"], "item_id": item.item_id,
                       "chosen_option": ans.chosen_option, "correct": ans.correct,
                       "had_help": had_help, "attempt_number": 1,
                       "confidence": ans.confidence}
            if ev["phase"] == "PRACTICE":
                payload["intervention_id"] = intervention_id
            body["operation"] = "ADD_EVIDENCE"
            body["record"] = {"source_record_id": rec_id, "occurred_at": _iso(t),
                              "payload": payload}
            trace.append({"source_record_id": rec_id, "concept_source_id": cid,
                          "phase": ev["phase"], "known": known, "twin_known": twin_known,
                          "misconception": mis, "path": ans.path})
        answers.append(body)

    cid_to_uuid = {c.source_id: c.concept_id for c in CONCEPTS}
    truth = {
        "learner_id": learner_id, "population": pop.name, "intervention_id": intervention_id,
        "set_to_learn": [cid_to_uuid[c] for c in learnable],
        "params": {cid_to_uuid[c]: asdict(p) for c, p in params.items()},
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
    return answers, truth


def simulate(seed: int, n_per_population: int, populations=POPULATIONS,
             post_items: int = POST_ITEMS, items_per_concept: int = ITEMS_PER_CONCEPT) -> dict:
    """Populations are assigned to learner indices by a keyed shuffle, so a learner's index
    (and the id made from it) does not run through the populations in blocks.

    post_items and items_per_concept (added for SCRUM-94) default to the SCRUM-93 run: with
    the defaults every file is byte-identical to SCRUM-93's (a test checks the hash)."""
    used = 3 + 4 + post_items + 3
    if used > items_per_concept:
        raise ValueError(f"{used} items per concept needed, the bank has {items_per_concept}: "
                         "no item may be shown twice")
    bank = BANK if items_per_concept == ITEMS_PER_CONCEPT else build_bank(items_per_concept)
    slots = [(p.name, j) for p in populations for j in range(n_per_population)]
    order = Draws(seed, -2).shuffled(slots, "population-order")
    by_name = {p.name: p for p in populations}
    answers, truth = [], []
    for index, (name, _) in enumerate(order):
        a, t = simulate_learner(seed, index, by_name[name], post_items, bank)
        answers.extend(a)
        truth.append(t)
    answers.sort(key=lambda b: (b["record"]["occurred_at"], b["request_id"]))
    truth.sort(key=lambda t: t["learner_id"])
    return {"seed": seed, "n_per_population": n_per_population,
            "populations": [p.name for p in populations], "answers": answers, "truth": truth,
            "post_items": post_items, "items_per_concept": items_per_concept, "bank": bank}
