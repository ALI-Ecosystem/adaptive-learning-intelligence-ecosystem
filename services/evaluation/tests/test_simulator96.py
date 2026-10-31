"""SCRUM-96 extensions of the learner simulator.

1. With the defaults nothing changes: the SCRUM-93 and SCRUM-95 files are byte-identical
   (hashes taken BEFORE the SCRUM-96 extension was written).
2. Each extension does what the SCRUM-96 decisions say, and only that.
"""
import hashlib
import json
import math

import pytest

from simulator.concepts import CONCEPTS
from simulator.config import SCRUM95, SCRUM96, SimConfig, items_needed
from simulator.draws import Draws
from simulator.generator import simulate
from simulator.items import BANK, TRANSFER, TRANSFER_BANK
from simulator.learner import IDEA, PATTERN, ConceptState, Learner
from simulator.populations import ALL_POPULATIONS, BY_NAME, POPULATIONS, POPULATIONS_96, Params
from simulator.records import write_run

Z999 = 3.29


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.mark.parametrize("args, cfg, pops, ans, tru", [
    ((93, 200), SimConfig(), POPULATIONS, "9a5c0a8cad24d389", "eaf57bdcbdfb8d0f"),
    ((95, 60), SCRUM95, ALL_POPULATIONS, "0b4f371a5a4fe5f7", "07a288dca5d8623c"),
])
def test_defaults_are_byte_identical_to_earlier_runs(tmp_path, args, cfg, pops, ans, tru):
    post = 8 if cfg == SCRUM95 else 3
    bank = max(20, items_needed(post, cfg))
    m = write_run(simulate(*args, populations=pops, post_items=post, items_per_concept=bank,
                           config=cfg), tmp_path)
    assert m["sha256"]["answers.jsonl"][:16] == ans
    assert m["sha256"]["truth.jsonl"][:16] == tru


def test_ordinary_bank_unchanged_and_transfer_bank_separate():
    assert all(it.kind != TRANSFER for items in BANK.values() for it in items)
    assert all("activity_type" not in it.to_public() for items in BANK.values() for it in items)
    ids = {it.item_id for items in TRANSFER_BANK.values() for it in items}
    assert not ids & {it.item_id for items in BANK.values() for it in items}
    assert all(it.to_public()["activity_type"] == TRANSFER
               for items in TRANSFER_BANK.values() for it in items)


@pytest.fixture(scope="module")
def run96(tmp_path_factory):
    d = tmp_path_factory.mktemp("run96")
    write_run(simulate(11, 40, populations=POPULATIONS_96, post_items=8,
                       items_per_concept=items_needed(8, SCRUM96), config=SCRUM96), d)
    return {"answers": read_jsonl(d / "answers.jsonl"), "truth": read_jsonl(d / "truth.jsonl")}


def test_timeline_transfer_after_ordinary_items_and_delayed_length(run96):
    by_learner = {}
    for b in run96["answers"]:
        if b["operation"] == "ADD_EVIDENCE":
            by_learner.setdefault((b["learner_id"], b["concept"]["concept_id"]), []).append(b)
    for rows in by_learner.values():
        for test in ("POST_TEST", "DELAYED_TEST"):
            mine = [b["record"]["payload"] for b in rows if b["record"]["payload"]["activity"] == test]
            plain = [p for p in mine if "activity_type" not in p]
            transfer = [p for p in mine if p.get("activity_type") == TRANSFER]
            assert len(plain) == 8 and len(transfer) == 4
            assert all("-T" in p["item_id"] for p in transfer)
        times = {}
        for b in rows:
            p = b["record"]["payload"]
            key = (p["activity"], p.get("activity_type"))
            times.setdefault(key, []).append(b["record"]["occurred_at"])
        assert max(times[("POST_TEST", None)]) < min(times[("POST_TEST", TRANSFER)])
        assert max(times[("DELAYED_TEST", None)]) < min(times[("DELAYED_TEST", TRANSFER)])


def test_pattern_learners_fail_transfer_only(run96):
    rows = [r for t in run96["truth"] if t["population"] == "LEARNS_PATTERN" for r in t["trace"]
            if r["phase"] in ("POST_TEST", "DELAYED_TEST") and r["known"]]
    assert rows
    assert all(r["depth"] == PATTERN for r in rows)
    transfer = [r for r in rows if r["item_kind"] == TRANSFER]
    plain = [r for r in rows if r["item_kind"] != TRANSFER]
    assert all(r["path"].startswith("PATTERN_ONLY_") for r in transfer)
    assert not any(r["path"].startswith("PATTERN_ONLY_") for r in plain)
    # every other population learns the idea
    other = [r for t in run96["truth"] if t["population"] != "LEARNS_PATTERN" for r in t["trace"]
             if r["known"] and r["phase"] != "EXPLANATION"]
    assert all(r["depth"] == IDEA for r in other)


def test_errors_then_learns_clears_misconception_on_learning(run96):
    for t in run96["truth"]:
        if t["population"] != "ERRORS_THEN_LEARNS":
            continue
        assert all(t["misconceptions_at_start"].values())
        for cid, s in t["checkpoints"]["immediate"]["concepts"].items():
            if s["known"]:
                assert s["misconception"] is None
        events = [e["event"] for e in t["transitions"]]
        learned = sum(e.startswith("LEARNED") for e in events)
        cleared = sum(e.startswith("MISCONCEPTION_CLEARED_ON_LEARN") for e in events)
        assert cleared == learned


def test_practice_errors_teach_only_after_the_intervention():
    c = CONCEPTS[0]
    p = Params(p_L0=0.0, p_T=0.0, p_T_after=0.0, p_T_err=1.0)
    lrn = Learner({c.source_id: p}, Draws(1, 0))
    lrn.states[c.source_id] = ConceptState(False, None)
    lrn.practice_opportunity(c.source_id, 10.0, "k1", answered_correct=False)
    assert not lrn.states[c.source_id].known          # no intervention yet: no effect
    lrn.intervened.add(c.source_id)
    lrn.practice_opportunity(c.source_id, 20.0, "k2", answered_correct=True)
    assert not lrn.states[c.source_id].known          # a right answer: no extra chance
    lrn.practice_opportunity(c.source_id, 30.0, "k3", answered_correct=False)
    assert lrn.states[c.source_id].known


def test_twin_coupling_still_holds(run96):
    """Whenever the twin (no intervention) comes to know a concept, the learner knows it at
    that moment too - p_T_err and the clearing rule do not break the coupling."""
    for t in run96["truth"]:
        for e in t["twin_transitions"]:
            if not e["event"].startswith("LEARNED"):
                continue
            known = False
            for r in sorted(t["transitions"], key=lambda r: r["at"]):
                if r["concept_id"] != e["concept_id"] or r["at"] > e["at"]:
                    continue
                if r["event"] == "KNOWN_AT_START" or r["event"].startswith("LEARNED"):
                    known = True
                elif r["event"] == "FORGOT":
                    known = False
            assert known, (t["population"], e)


def test_explanations_only_for_explaining_learners(run96):
    by = {t["learner_id"]: t for t in run96["truth"]}
    expl = [b for b in run96["answers"] if b["operation"] == "ADD_EVIDENCE"
            and b["record"]["payload"]["activity"] == "EXPLANATION"]
    assert expl
    for b in expl:
        p = b["record"]["payload"]
        assert by[b["learner_id"]]["explains"]
        assert 0.0 <= p["grade"] <= 1.0 and p["response_type"] == "OPEN"
        assert p["chosen_option"] is None
    share = sum(t["explains"] for t in run96["truth"]) / len(run96["truth"])
    n = len(run96["truth"])
    assert abs(share - 0.5) <= Z999 * math.sqrt(0.25 / n)


def test_explanation_grade_follows_depth(run96):
    g = {IDEA: [], PATTERN: [], None: []}
    for t in run96["truth"]:
        for r in t["trace"]:
            if r["phase"] == "EXPLANATION":
                g[r["depth"] if r["known"] else None].append(r["grade"])
    mean = {k: sum(v) / len(v) for k, v in g.items() if v}
    assert mean[IDEA] > mean[PATTERN] > mean[None]


def test_new_populations_are_not_in_the_earlier_lists():
    names = {p.name for p in ALL_POPULATIONS}
    assert "LEARNS_PATTERN" not in names and "ERRORS_THEN_LEARNS" not in names
    assert BY_NAME["LEARNS_PATTERN"].params.p_idea == 0.0


def test_explanations_do_not_shift_non_explainers(tmp_path):
    """A learner who does not explain has exactly the timeline of a run without
    explanations (independent review: the slots used to shift everyone)."""
    from dataclasses import replace
    pops = (BY_NAME["LEARNS"],)
    a = simulate(3, 30, populations=pops, post_items=8,
                 items_per_concept=items_needed(8, SCRUM96), config=SCRUM96)
    b = simulate(3, 30, populations=pops, post_items=8,
                 items_per_concept=items_needed(8, SCRUM96),
                 config=replace(SCRUM96, explanation_share=1e-12))
    quiet = {t["learner_id"] for t in a["truth"] if not t["explains"]}
    assert quiet
    ta = [(x["learner_id"], x["record"]["occurred_at"]) for x in a["answers"] if x["learner_id"] in quiet]
    tb = [(x["learner_id"], x["record"]["occurred_at"]) for x in b["answers"] if x["learner_id"] in quiet]
    assert ta == tb
