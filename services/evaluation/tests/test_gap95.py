"""SCRUM-95: the assisted-versus-unaided gap measure."""
import json
from dataclasses import replace

import pytest

from gap import assisted as G
from gap.betadiff import draws, gap_draws
from harness import adapter94 as A
from harness import adapter95 as A5
from simulator.config import SCRUM95, items_needed
from simulator.generator import simulate
from simulator.items import build_bank
from simulator.populations import ALL_POPULATIONS, BY_NAME
from simulator.records import write_run
from verdict import engine


def ri(unaided, assisted, rnd=1, verdict="NOT_YET_DEMONSTRATED"):
    return G.RoundInput(rnd, f"iv{rnd}", tuple(unaided), tuple(assisted), verdict)


def k_of_n(k, n):
    return [1] * k + [0] * (n - k)


# ---- the statistic ---------------------------------------------------------------------------

def test_draws_are_deterministic_and_slots_independent():
    assert draws(3, 8, "U1") == draws(3, 8, "U1")
    assert draws(3, 8, "U1") != draws(3, 8, "U3")
    g = gap_draws(2, 2, 2, 8, 1)
    assert len(g) == 20_000 and all(-1 < x < 1 for x in g)


def test_side_is_the_beta_posterior_of_a_uniform_prior():
    s = G._side((1, 1, 0, 0))
    assert s["mean"] == pytest.approx(3 / 6) and s["n"] == 4 and s["correct"] == 2
    lo, hi = s["interval90"]
    assert lo < 0.5 < hi


@pytest.mark.parametrize("u,a,status", [
    (k_of_n(0, 8), k_of_n(2, 2), G.CREDIBLE_GAP),        # alone fails, help carries
    (k_of_n(1, 8), k_of_n(2, 2), G.CREDIBLE_GAP),
    (k_of_n(8, 8), k_of_n(2, 2), G.NO_CREDIBLE_GAP),     # succeeds alone
    (k_of_n(7, 8), k_of_n(2, 2), G.NO_CREDIBLE_GAP),
    (k_of_n(4, 8), k_of_n(1, 2), G.INSUFFICIENT),        # the middle: says so
])
def test_gap_status(u, a, status):
    assert G.round_gap(ri(u, a))["gap"]["status"] == status


def test_missing_side_is_insufficient_with_a_reason():
    g = G.round_gap(ri([], k_of_n(2, 2)))["gap"]
    assert g["status"] == G.INSUFFICIENT and g["reason"] == "no unaided answer"
    g = G.round_gap(ri(k_of_n(2, 8), []))["gap"]
    assert g["status"] == G.INSUFFICIENT and g["reason"] == "no assisted answer"


def test_reduction_strong_learner_reduced_and_no_change_not_reduced():
    m = G.measure("l", "c", [ri(k_of_n(1, 8), k_of_n(2, 2), 1), ri(k_of_n(4, 8), k_of_n(2, 2), 2),
                             ri(k_of_n(8, 8), k_of_n(2, 2), 3)])
    r = m["reduction"]
    assert r["status"] == G.REDUCED and r["unaided_change"] > 0.5
    assert r["assisted_change"] == pytest.approx(0.0)
    assert r["status_path"] == [G.CREDIBLE_GAP, G.INSUFFICIENT, G.NO_CREDIBLE_GAP]
    same = G.measure("l", "c", [ri(k_of_n(1, 8), k_of_n(2, 2), 1), ri(k_of_n(1, 8), k_of_n(2, 2), 3)])
    assert same["reduction"]["status"] != G.REDUCED
    assert 0.3 < 1 - same["reduction"]["p_reduced"] < 0.8      # equal counts: not certain


def test_reduction_counts_a_drop_inside_credible_gap():
    """0.70 -> 0.30 is still CREDIBLE in both rounds: the status path says no change,
    the reduction measure must still see it (decision M3, against option C)."""
    m = G.measure("l", "c", [ri(k_of_n(0, 8), k_of_n(2, 2), 1), ri(k_of_n(5, 8), k_of_n(2, 2), 3)])
    assert m["reduction"]["p_reduced"] > 0.8


def test_output_is_a_measurement_not_a_label():
    m = G.measure("l", "c", [ri(k_of_n(0, 8), k_of_n(2, 2), 1)])
    text = json.dumps(m).lower()
    for word in ("illusion", "dependent", "depend", "recommend", "should", "learner_is"):
        assert word not in text
    assert set(m) == {"measure", "learner_id", "concept_id", "rounds", "reduction", "thresholds"}


# ---- the adapter on a SCRUM-95 run -----------------------------------------------------------

@pytest.fixture(scope="module")
def small95(tmp_path_factory):
    def make(cfg, name):
        d = tmp_path_factory.mktemp(name)
        bank = items_needed(8, cfg)
        write_run(simulate(7, 4, populations=ALL_POPULATIONS, post_items=8,
                           items_per_concept=bank, config=cfg), d)
        return d
    masked = make(SCRUM95, "masked")
    full = make(replace(SCRUM95, never_report=0.0, report_prob=(1.0,) * 5), "full")
    bank = build_bank(items_needed(8, SCRUM95))
    calib = {it.item_id: (0.0, 0.1) for items in bank.values() for it in items}
    return masked, full, calib


def _all_inputs(d, calib):
    run = A5.load_run95(d, calib)
    ls = A.standin_for(run)
    return {(lid, cid): A5.round_inputs(run[lid], cid, ls)
            for lid in sorted(run) for cid in sorted(run[lid]["rounds"])}, run, ls


def test_each_round_has_8_unaided_and_2_assisted_answers(small95):
    masked, _, calib = small95
    inputs, _, _ = _all_inputs(masked, calib)
    for ris in inputs.values():
        assert [r.round for r in ris] == [1, 2, 3]
        assert len({r.intervention_id for r in ris}) == 3
        for r in ris:
            assert len(r.unaided) == 8 and len(r.assisted) == 2 and not r.excluded


def test_round_verdict_is_the_engine_verdict_for_that_round(small95):
    masked, _, calib = small95
    inputs, run, ls = _all_inputs(masked, calib)
    (lid, cid), ris = next(iter(inputs.items()))
    for rd, r in zip(run[lid]["rounds"][cid], ris):
        v = engine.evaluate(rd["iv"], ls, run[lid]["answers"], [], rd["as_of"])
        assert v.outcome.value == r.verdict
        assert sum(j.counted for j in v.answers) == len(r.unaided)


def test_no_self_report_changes_nothing_in_the_assisted_gap(small95):
    """Task: with no self-report the prototype still reports the assisted gap."""
    masked, full, calib = small95
    a, _, _ = _all_inputs(masked, calib)
    b, _, _ = _all_inputs(full, calib)
    assert a == b
    ma = [G.measure(l, c, r) for (l, c), r in sorted(a.items())]
    mb = [G.measure(l, c, r) for (l, c), r in sorted(b.items())]
    assert ma == mb


def test_truth_expected_shares_match_the_simulator_model(small95):
    masked, _, _ = small95
    truth = A5.load_truth95(masked)
    for (lid, cid), t in truth.items():
        p = BY_NAME[t["population"]].params
        for r in t["rounds"].values():
            assert 0 <= r["true_unaided"] <= 1 and 0 <= r["true_assisted"] <= 1
            assert r["true_assisted"] >= p.p_help_correct - 1e-9    # help carries at least this
