"""SCRUM-95 extensions of the learner simulator.

1. With the defaults nothing changes: the files are byte-identical to SCRUM-93/94 runs
   (hashes taken BEFORE the extension was written).
2. Each extension does what the SCRUM-95 decisions say, and only that.
Statistical checks use a 99.9% interval (|observed - expected| <= 3.29 standard errors).
"""
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import replace

import pytest

from simulator.concepts import CONCEPTS
from simulator.config import DEFAULT, SCRUM95, SCRUM95_POST_ITEMS, SimConfig, items_needed
from simulator.draws import Draws
from simulator.generator import simulate
from simulator.items import BANK
from simulator.learner import DAY, ConceptState, Learner
from simulator.populations import ALL_POPULATIONS, BY_NAME, POPULATIONS, Params
from simulator.records import write_run

Z999 = 3.29


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def single_learner(params: Params, known: bool, seed=1):
    c = CONCEPTS[0]
    lrn = Learner({c.source_id: params}, Draws(seed, 0))
    lrn.states[c.source_id] = ConceptState(known, None, forget_at=None)
    return lrn, c


# ---- 1. defaults are byte-identical to SCRUM-93/94 -----------------------------------------
# (answers.jsonl, truth.jsonl) sha256 prefixes recorded before any SCRUM-95 change.
GOLDEN = [
    ((11, 12), {}, "21f1aafca4307ac4", "9bd908de69532f18"),
    ((11, 12), {"post_items": 8}, "2354e0c46039f95a", "019bb2b7d3b06a8d"),
    ((5, 6), {"post_items": 16, "items_per_concept": 26}, "8b176f43cae880a8", "4f5589c67ab021f7"),
    ((93, 200), {}, "9a5c0a8cad24d389", "eaf57bdcbdfb8d0f"),           # the SCRUM-93 run
    ((93, 200), {"post_items": 8}, "bee8081fc9f45e1d", "1afb9abd8dfb6d80"),   # SCRUM-94 L8
]


@pytest.mark.parametrize("args,kw,ans,tru", GOLDEN)
def test_defaults_reproduce_scrum93_and_94_files(tmp_path, args, kw, ans, tru):
    m = write_run(simulate(*args, **kw), tmp_path)
    assert m["sha256"]["answers.jsonl"][:16] == ans
    assert m["sha256"]["truth.jsonl"][:16] == tru
    assert "config" not in m


def test_default_config_is_not_extended_and_scrum95_is():
    assert not DEFAULT.extended and not DEFAULT.masks_confidence
    assert SCRUM95.extended and SCRUM95.masks_confidence
    assert POPULATIONS == ALL_POPULATIONS[:7]          # SCRUM-93 order untouched


def test_new_populations_keep_twin_coupling_and_old_ones_have_help_off():
    for p in ALL_POPULATIONS:
        assert p.params.p_T_after >= p.params.p_T
    for p in POPULATIONS:
        assert p.params.p_T_help == 0 and p.params.help_conf_boost == 0


# ---- 2. a SCRUM-95 run -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def run95(tmp_path_factory):
    d = tmp_path_factory.mktemp("sim95")
    bank = items_needed(SCRUM95_POST_ITEMS, SCRUM95)
    m = write_run(simulate(2095, 150, populations=ALL_POPULATIONS, post_items=SCRUM95_POST_ITEMS,
                           items_per_concept=bank, config=SCRUM95), d)
    answers = read_jsonl(d / "answers.jsonl")
    truth = read_jsonl(d / "truth.jsonl")
    payload = {b["record"]["source_record_id"]: b["record"]["payload"]
               for b in answers if b["operation"] == "ADD_EVIDENCE"}
    rows = [(t["population"], r, payload[r["source_record_id"]], t)
            for t in truth for r in t["trace"]]
    return {"dir": d, "manifest": m, "answers": answers, "truth": truth, "rows": rows}


def test_scrum95_run_is_reproducible(run95, tmp_path):
    bank = items_needed(SCRUM95_POST_ITEMS, SCRUM95)
    m = write_run(simulate(2095, 150, populations=ALL_POPULATIONS, post_items=SCRUM95_POST_ITEMS,
                           items_per_concept=bank, config=SCRUM95), tmp_path)
    assert m["sha256"] == run95["manifest"]["sha256"]
    assert run95["manifest"]["config"]["rounds"] == 3


def test_no_item_shown_twice_and_bank_size_checked(run95):
    seen = defaultdict(set)
    for b in run95["answers"]:
        if b["operation"] == "ADD_EVIDENCE":
            key = (b["learner_id"], b["record"]["payload"]["item_id"])
            assert key not in seen["x"]
            seen["x"].add(key)
    with pytest.raises(ValueError):
        simulate(1, 1, config=SCRUM95, post_items=8, items_per_concept=20)


def test_three_rounds_each_a_new_intervention_in_time_order(run95):
    for t in run95["truth"]:
        rounds = t["rounds"]
        assert [r["round"] for r in rounds] == [1, 2, 3]
        assert len({r["intervention_id"] for r in rounds}) == 3
        assert rounds[0]["intervention_id"] == t["intervention_id"]
        ats = [r["intervention_at"] for r in rounds]
        assert ats == sorted(ats)
        assert set(t["checkpoints"]) == {"immediate", "immediate_r2", "immediate_r3", "delayed"}
        cps = [t["checkpoints"][k]["at"] for k in ("immediate", "immediate_r2", "immediate_r3", "delayed")]
        assert cps == sorted(cps)


def test_round_gap_is_about_one_day(run95):
    from datetime import datetime
    for t in run95["truth"][:200]:
        a = [datetime.fromisoformat(r["intervention_at"]) for r in t["rounds"]]
        for x, y in zip(a, a[1:]):
            gap = (y - x).total_seconds() / DAY
            assert 0.75 < gap < 1.25 + 0.2          # + the length of a round (< 3 hours)


def test_assisted_items_always_helped_after_the_unaided_ones_and_never_teach(run95):
    by_learner_round = defaultdict(lambda: {"U": [], "A": []})
    for pop, r, p, t in run95["rows"]:
        if r["phase"] != "POST_TEST":
            continue
        if r["assisted"]:
            assert p["had_help"] is True
        else:
            assert p["had_help"] is False           # unaided post-test items: no help offered
        by_learner_round[(t["learner_id"], r["round"])]["A" if r["assisted"] else "U"].append(
            r["source_record_id"])
    times = {b["record"]["source_record_id"]: b["record"]["occurred_at"] for b in run95["answers"]}
    for v in by_learner_round.values():
        assert len(v["A"]) == 2 * len(CONCEPTS) and len(v["U"]) == 8 * len(CONCEPTS)
        assert max(times[x] for x in v["U"]) < min(times[x] for x in v["A"])
    learned_events = {"LEARNED_AT_INTERVENTION", "LEARNED_IN_PRACTICE", "LEARNED_FROM_HELP"}
    for t in run95["truth"]:
        post_times = {times[r["source_record_id"]] for r in t["trace"] if r["phase"] == "POST_TEST"}
        assert not [e for e in t["transitions"] if e["event"] in learned_events and e["at"] in post_times]


def test_only_learns_from_help_learns_from_help(run95):
    counts = defaultdict(int)
    for t in run95["truth"]:
        counts[t["population"]] += sum(e["event"] == "LEARNED_FROM_HELP" for e in t["transitions"])
    assert counts["LEARNS_FROM_HELP"] > 100
    assert all(v == 0 for k, v in counts.items() if k != "LEARNS_FROM_HELP")


def test_twin_coupling_holds_at_every_checkpoint(run95):
    for t in run95["truth"]:
        for cp in t["checkpoints"].values():
            for c in cp["concepts"].values():
                assert c["known"] or not c["twin_known"]


def _known(run95, pop, name):
    xs = [c["known"] for t in run95["truth"] if t["population"] == pop
          for c in t["checkpoints"][name]["concepts"].values()]
    return sum(xs) / len(xs)


def test_learns_from_help_gains_across_rounds_and_help_dependent_stays_low(run95):
    a = [_known(run95, "LEARNS_FROM_HELP", n) for n in ("immediate", "immediate_r2", "immediate_r3")]
    assert a[0] < a[1] < a[2] and a[2] - a[0] > 0.2
    for pop in ("HELP_DEPENDENT", "HELP_INFLATED"):
        assert _known(run95, pop, "immediate_r3") < 0.45          # "learns a little"


def test_help_boost_raises_confidence_of_help_inflated_only_and_fades(run95):
    conf = defaultdict(list)
    boost = defaultdict(list)
    for pop, r, p, t in run95["rows"]:
        if pop in ("HELP_INFLATED", "HELP_DEPENDENT") and not r["known"] and not r["had_help"]:
            stage = "post" if r["phase"] == "POST_TEST" else ("delayed" if r["phase"] == "DELAYED_TEST" else None)
            if stage:
                conf[(pop, stage)].append(r["confidence_true"])
                boost[(pop, stage)].append(r["confidence_boost"])
        elif pop not in ("HELP_INFLATED",):
            assert r["confidence_boost"] == 0
    m = lambda xs: sum(xs) / len(xs)
    assert m(conf[("HELP_INFLATED", "post")]) - m(conf[("HELP_DEPENDENT", "post")]) > 1.0
    assert m(boost[("HELP_DEPENDENT", "post")]) == 0
    assert m(boost[("HELP_INFLATED", "delayed")]) < m(boost[("HELP_INFLATED", "post")]) / 4


def test_boost_is_from_the_latest_help_and_halves_each_half_life():
    p = Params(help_conf_boost=1.5, boost_half_life_days=1.0)
    lrn, c = single_learner(p, known=False)
    lrn.help_times[c.source_id] = [0.0, 0.5 * DAY]
    # at t = 0.5 day only the help at t = 0 is strictly earlier: half a half-life ago
    assert lrn.confidence_boost(c.source_id, 0.5 * DAY) == pytest.approx(1.5 * 2 ** -0.5)
    assert lrn.confidence_boost(c.source_id, 1.5 * DAY) == pytest.approx(0.75)
    assert lrn.confidence_boost(c.source_id, 3.5 * DAY) == pytest.approx(0.1875)


def test_help_forced_always_helps_and_teaches_nothing():
    lrn, c = single_learner(Params(p_help=0.0, p_T_help=1.0), known=False)
    item = BANK[c.source_id][0]
    for i in range(50):
        ans, had = lrn.answer(item, i * 60.0, help_allowed=False, key=f"k{i}", help_forced=True)
        assert had
    assert not lrn.states[c.source_id].known                 # answer() never changes the state


def test_missing_confidence_never_reporters_and_not_at_random(run95):
    by_true = defaultdict(lambda: [0, 0])
    for pop, r, p, t in run95["rows"]:
        if t["never_reports_confidence"]:
            assert p["confidence"] is None
            continue
        reported = p["confidence"] is not None
        assert reported == r["confidence_reported"]
        if reported:
            assert p["confidence"] == r["confidence_true"]
        by_true[r["confidence_true"]][0] += reported
        by_true[r["confidence_true"]][1] += 1
    for conf, expected in enumerate(SCRUM95.report_prob, start=1):
        k, n = by_true[conf]
        assert abs(k / n - expected) <= Z999 * math.sqrt(expected * (1 - expected) / n)
    share = sum(t["never_reports_confidence"] for t in run95["truth"]) / len(run95["truth"])
    assert abs(share - 0.20) <= Z999 * math.sqrt(0.2 * 0.8 / len(run95["truth"]))


def test_without_masking_every_answer_has_confidence(tmp_path):
    cfg = replace(SCRUM95, never_report=0.0, report_prob=(1.0,) * 5)
    bank = items_needed(SCRUM95_POST_ITEMS, cfg)
    r = simulate(3, 5, populations=ALL_POPULATIONS, post_items=8, items_per_concept=bank, config=cfg)
    assert all(b["record"]["payload"]["confidence"] is not None
               for b in r["answers"] if b["operation"] == "ADD_EVIDENCE")
