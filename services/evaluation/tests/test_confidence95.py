"""SCRUM-95: the perceived-versus-demonstrated (confidence) gap."""
import json

import pytest

from gap import confidence as C
from gap.confnorm import build, load

NORM = {1: 0.26, 2: 0.35, 3: 0.55, 4: 0.71, 5: 0.77}


def gap(pairs, n0=C.PRIOR_WEIGHT):
    return C.round_gap(C.ConfRound(1, tuple(pairs)), NORM, n0=n0)["gap"]


def test_one_wrong_answer_is_not_enough_four_are():
    """The proposal's risk section: a single question does not decide (decision C4)."""
    assert gap([(0, 5)])["status"] == C.INSUFFICIENT
    assert gap([(0, 5)] * 3)["status"] == C.INSUFFICIENT
    assert gap([(0, 5)] * 4)["status"] == C.ABOVE
    assert gap([(0, 5)], n0=1e-9)["status"] == C.ABOVE        # a flat prior would decide at once


def test_both_directions_and_no_gap():
    assert gap([(1, 1)] * 10)["status"] == C.BELOW
    assert gap([(1, 4), (1, 4), (0, 4), (1, 4)] * 6)["status"] == C.NONE


def test_exact_probability_matches_the_beta_cdf():
    from verdict import betafn
    g = gap([(0, 5), (1, 5), (0, 5)])
    e = 0.77
    a, b = e * 4 + 1, (1 - e) * 4 + 2
    assert g["p_above"] == pytest.approx(betafn.cdf(e - 0.2, a, b))


def test_answers_without_confidence_are_skipped_and_never_invented():
    r = C.round_gap(C.ConfRound(1, ((0, None), (1, None))), NORM)
    assert r["gap"]["status"] == C.INSUFFICIENT and r["perceived"] is None
    m = C.measure("l", "c", [C.ConfRound(1, ((0, None),)), C.ConfRound(3, ((1, None),))], NORM)
    assert m["status"] == C.NO_SELF_REPORT and m["rounds"] == [] and m["reduction"] is None


def test_discrimination_index():
    r = C.round_gap(C.ConfRound(1, ((1, 5), (1, 3), (0, 2), (0, 2))), NORM)
    assert r["discrimination"] == pytest.approx(4.0 - 2.0)
    assert C.round_gap(C.ConfRound(1, ((1, 5),)), NORM)["discrimination"] is None


def test_reduction_exact_and_deterministic():
    rs = [C.ConfRound(1, ((0, 5),) * 5), C.ConfRound(3, ((1, 4),) * 5)]
    a, b = C.measure("l", "c", rs, NORM), C.measure("l", "c", rs, NORM)
    assert a == b and a["reduction"]["status"] == C.REDUCED
    same = C.measure("l", "c", [C.ConfRound(1, ((0, 5), (1, 4))), C.ConfRound(3, ((0, 5), (1, 4)))], NORM)
    assert same["reduction"]["status"] != C.REDUCED
    assert 0.1 < same["reduction"]["p_reduced"] < 0.5


def test_answers_to_detect():
    assert C.answers_to_detect(((0, 5),) * 6, NORM) == 4
    assert C.answers_to_detect(((1, 4),) * 6, NORM) is None


def test_output_is_a_measurement_not_a_label():
    m = C.measure("l", "c", [C.ConfRound(1, ((0, 5),) * 6)], NORM)
    text = json.dumps(m).lower()
    for word in ("illusion", "overconfident", "recommend", "should", "deceiv"):
        assert word not in text


def test_norm_from_answers_only(tmp_path):
    from simulator.config import SCRUM95, items_needed
    from simulator.generator import simulate
    from simulator.populations import ALL_POPULATIONS
    from simulator.records import write_run
    write_run(simulate(5, 6, populations=ALL_POPULATIONS, post_items=8,
                       items_per_concept=items_needed(8, SCRUM95), config=SCRUM95), tmp_path)
    (tmp_path / "truth.jsonl").unlink()                 # the norm must not need the truth
    d = build(tmp_path)
    (tmp_path / "norm.json").write_text(json.dumps(d))
    norm = load(tmp_path / "norm.json")
    assert set(norm) == {1, 2, 3, 4, 5} and all(0 < v < 1 for v in norm.values())
    assert norm[5] > norm[1]
