"""SCRUM-94 - tests of the intervention verdict.

What each group proves:
  numerics     the standard-library Beta functions equal scipy; the stand-in equals the
               Learner State oracle; the grid model reproduces the evaluation architecture's
               Appendix B.4 table exactly
  gate         every exclusion rule fires, alone, with its recorded reason
  invariance   answers that fail the gate never change the verdict - outcome, P and BF
  boundaries   the verdict only reads Learner State (at delivery), never writes it
  decisions    INSUFFICIENT instead of a guess; mis-estimated baselines in both directions
  determinism  same inputs -> same verdict and the same input digest, in any input order
  simulator    the SCRUM-93 run is unchanged with the new parameters at their defaults
"""
import hashlib
import importlib.util
import math
import random
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness import adapter94                                     # noqa: E402
from harness.contaminate import EXPECTED, contaminate             # noqa: E402
from simulator.generator import simulate                          # noqa: E402
from simulator.records import write_run                           # noqa: E402
from verdict import betafn, engine, model, standin                # noqa: E402
from verdict.contracts import (AnswerRecord, Exclusion, Intervention, ItemShown,  # noqa: E402
                               Outcome)

MIN = 60.0
DAY = 86_400.0
LS_ORACLE = ROOT.parent / "learner-state" / "docs" / "verify_mastery_model.py"


# ---- helpers ------------------------------------------------------------------------------

def iv(delivered=1000.0, completed=None, target=0.70, iid="IV-1"):
    return Intervention(iid, "L1", "C1", "UNSPECIFIED", "INSTRUCT", target, delivered, completed)


def ans(rid, t, credit=1.0, item=None, prod="PROBE-1", **kw):
    base = dict(record_id=rid, learner_id="L1", concept_id="C1", cognitive_level="UNSPECIFIED",
                occurred_at=t, item_id=item or f"I-{rid}", chosen_option="A", credit=credit,
                attempt_number=1, help_before_answer=False, producing_intervention_id=prod,
                producing_intent="PROBE", item_b=0.0, item_b_se=0.3)
    base.update(kw)
    return AnswerRecord(**base)


class Reader:
    """A fixed baseline, read-only, that records every call."""
    def __init__(self, a=1.2, b=2.8):
        self.a, self.b, self.calls = a, b, []

    def config(self):
        return standin.LearnerStateStandIn().config()

    def baseline(self, learner_id, concept_id, as_of):
        self.calls.append(as_of)
        return standin.FixedBaselineReader(self.a, self.b).baseline(learner_id, concept_id, as_of)


def treatment(n=4, start=1100.0):
    return [ans(f"T{i}", start + i * MIN, credit=1.0, prod="IV-1", help_before_answer=(i == 0))
            for i in range(n)]


def outcome_answers(credits, start=2000.0):
    return [ans(f"O{i}", start + i * MIN, credit=c) for i, c in enumerate(credits)]


# ---- numerics -----------------------------------------------------------------------------

def test_beta_functions_equal_scipy():
    sp = pytest.importorskip("scipy.stats")
    for a, b in [(0.6, 1.4), (1.2, 2.8), (15, 15), (8, 2), (0.3, 0.5), (29, 1), (4.5, 25.5)]:
        for x in (0.01, 0.05, 0.3, 0.5, 0.7, 0.95, 0.99):
            assert abs(betafn.sf(x, a, b) - sp.beta.sf(x, a, b)) < 1e-12
        for q in (0.05, 0.5, 0.95):
            assert abs(betafn.ppf(q, a, b) - sp.beta.ppf(q, a, b)) < 1e-12


def test_standin_equals_the_learner_state_oracle():
    pytest.importorskip("scipy")
    pytest.importorskip("numpy")
    if not LS_ORACLE.exists():
        pytest.skip("Learner State oracle not found")
    spec = importlib.util.spec_from_file_location("ls_oracle", LS_ORACLE)
    orc = importlib.util.module_from_spec(spec)
    src = LS_ORACLE.read_text(encoding="utf-8").replace('if __name__ == "__main__":', "if False:")
    exec(compile(src, str(LS_ORACLE), "exec"), orc.__dict__)
    rng = random.Random(7)
    for _ in range(300):
        a, b = rng.uniform(0.3, 20), rng.uniform(0.3, 20)
        c = rng.choice([0.0, 1.0, 0.6])
        kw = dict(weight=rng.uniform(0.2, 1), slip=0.1, guess=rng.choice([0.25, 0.05]),
                  had_instruction=rng.random() < 0.5, dt_days=rng.uniform(0, 40))
        assert all(abs(x - y) < 1e-12 for x, y in
                   zip(standin.update(a, b, c, **kw), orc.update(a, b, c, **kw)))
        assert abs(standin.p_above(a, b) - orc.p_above(a, b)) < 1e-12
        assert all(abs(x - y) < 1e-12 for x, y in
                   zip(standin.credible_interval(a, b), orc.credible_interval(a, b)))


def _fisher_p(g=0.25, s=0.10):
    best = (0.0, 0.0)
    for i in range(160001):
        x = -8 + 16 * i / 160000
        sg = 1 / (1 + math.exp(-x))
        p = g + (1 - g - s) * sg
        info = ((1 - g - s) * sg * (1 - sg)) ** 2 / (p * (1 - p))
        best = max(best, (info, p))
    return best[1]


def test_grid_model_reproduces_architecture_appendix_b4():
    """Consecutive unaided answers to decide, from evaluation-validation-architecture.md
    section 3.7 / Appendix B.4 (computed there with numpy/scipy, grid step 0.005)."""
    expected = {("INSTRUCT", 0.8, 3.2): (7, 2, 4, 2), ("INSTRUCT", 1.2, 2.8): (7, 2, 4, 3),
                ("INSTRUCT", 4.5, 25.5): (35, 3, 18, 3), ("PRACTISE", 1.6, 2.4): (13, 2, 7, 2),
                ("PRACTISE", 2.0, 2.0): (9, 2, 5, 3), ("PRACTISE", 6.0, 4.0): (11, 3, 7, 4),
                ("PRACTISE", 15.0, 15.0): (54, 4, 29, 4)}
    p_probe = _fisher_p()
    assert abs(p_probe - 0.596) < 0.001
    for (intent, a, b), want in expected.items():
        mu = 0.40 if intent == "INSTRUCT" else 0.70
        pp = model.prior_params(a, b, standin.credible_interval(a, b), 0.10, 1)
        tt = model.logit(mu)
        got = []
        for p_star, credit in ((0.75, 1.0), (0.75, 0.0), (p_probe, 1.0), (p_probe, 0.0)):
            bb = pp["theta0"] - model.logit((p_star - 0.25) / 0.65)
            post = model.Posterior(pp["theta0"], pp["sd"])
            target = model.SUPPORTED if credit else model.NOT_SUPPORTED
            for n in range(1, 120):
                post.add(credit, bb, 1.0, 0.25, 0.10)
                p, bf, _ = post.read(tt)
                if model.status_from(p, bf, n) == target:
                    got.append(n)
                    break
        assert tuple(got) == want, (intent, a, b)


# ---- the gate -----------------------------------------------------------------------------

def test_every_exclusion_rule_fires_with_its_reason():
    I = iv(delivered=1000.0)
    t_end = 1100.0 + 3 * MIN
    rows = treatment() + [
        ans("pre", 500.0),                                                    # before
        ans("ok", t_end + 10, item="FRESH-1"),
        ans("help", t_end + 20, help_before_answer=True),
        ans("try2", t_end + 30, item="FRESH-1", attempt_number=2),
        ans("seen", t_end + 40, item="I-pre"),
        ans("shown", t_end + 50, item="SHOWN-1"),
        ans("nosrc", t_end + 60, prod=None),
        ans("flag", t_end + 70, item_flagged=True),
        ans("nob", t_end + 80, item_b=None),
        ans("prop", t_end + 90, propagated=True),
        ans("unapp", t_end + 100, applied=False),
        ans("late", t_end + 3 * DAY),                                         # retention
        ans("other", t_end + 110, concept_id="C2"),
    ]
    shown = [ItemShown("L1", "SHOWN-1", 1050.0)]
    v = engine.evaluate(I, Reader(), rows, shown, as_of=t_end + 5 * DAY)
    got = {j.record_id: j.exclusion for j in v.answers}
    assert got["ok"] is None
    assert got["T0"] == got["T3"] == "IN_TREATMENT"
    want = {"pre": "BEFORE_TREATMENT_END", "help": "ASSISTED", "try2": "NOT_FIRST_ATTEMPT",
            "seen": "ITEM_SEEN_BEFORE", "shown": "ITEM_SEEN_BEFORE",
            "nosrc": "UNKNOWN_PROVENANCE", "flag": "ITEM_FLAGGED", "nob": "NO_DIFFICULTY",
            "prop": "PROPAGATED", "unapp": "NOT_APPLIED", "late": "RETENTION_WINDOW"}
    for rid, reason in want.items():
        assert got[rid] == reason, rid
    assert "other" not in got                     # another concept is not this case's answer
    assert v.n_counted == 1
    v2 = engine.evaluate(I, Reader(), rows, shown, as_of=t_end + 15)
    assert {j.record_id: j.exclusion for j in v2.answers}["help"] == "AFTER_AS_OF"


def test_seen_before_is_decided_by_time_not_arrival_order():
    I = iv()
    rows = treatment() + [ans("a", 5000.0, item="X"), ans("b", 4000.0, item="X")]
    v = engine.evaluate(I, Reader(), list(reversed(rows)), [], as_of=9000.0)
    got = {j.record_id: j.exclusion for j in v.answers}
    assert got["b"] is None and got["a"] == "ITEM_SEEN_BEFORE"


def test_late_treatment_answer_reclassifies_instead_of_double_counting():
    I = iv()
    rows = treatment() + outcome_answers([1, 1, 1], start=3000.0)
    late = ans("T-late", 3100.0, prod="IV-1")
    v = engine.evaluate(I, Reader(), rows + [late], [], as_of=9000.0)
    got = {j.record_id: j.exclusion for j in v.answers}
    assert got["O0"] == "BEFORE_TREATMENT_END" and got["O2"] is None


def test_censor_lets_exactly_one_unaided_first_answer_through():
    I = iv()
    rows = treatment() + outcome_answers([1, 1, 1], start=3000.0)
    v = engine.evaluate(I, Reader(), rows, [], as_of=9000.0, censor_at=3000.0)
    got = {j.record_id: j.exclusion for j in v.answers}
    assert got["O0"] is None and got["O1"] == got["O2"] == "AFTER_CENSOR"


# ---- invariance ---------------------------------------------------------------------------

def _random_case(rng):
    credits = [float(rng.random() < rng.choice([0.2, 0.5, 0.9])) for _ in range(rng.randint(0, 9))]
    return treatment() + outcome_answers(credits)


@pytest.mark.parametrize("seed", range(40))
def test_excluded_answers_never_change_the_verdict(seed):
    rng = random.Random(seed)
    clean = _random_case(rng)
    reader = Reader(*rng.choice([(1.2, 2.8), (0.4, 3.6), (19.5, 10.5), (3, 27), (2, 2)]))
    base = engine.evaluate(iv(), reader, clean, [], as_of=9000.0)
    dirty = list(clean)
    for k in range(rng.randint(1, 8)):
        c = float(rng.random() < 0.5)
        t = 2000.0 + rng.uniform(0, 9 * MIN)
        dirty.append(rng.choice([
            ans(f"h{k}", t, c, help_before_answer=True),
            ans(f"r{k}", t, c, item=clean[0].item_id),
            ans(f"a{k}", t, c, attempt_number=2),
            ans(f"n{k}", t, c, prod=None),
            ans(f"f{k}", t, c, item_flagged=True),
            ans(f"p{k}", t, c, propagated=True),
            ans(f"x{k}", 9500.0, c)]))
    rng.shuffle(dirty)
    v = engine.evaluate(iv(), reader, dirty, [], as_of=9000.0)
    assert (v.outcome, v.p_target, v.bayes_factor) == (base.outcome, base.p_target,
                                                       base.bayes_factor)


@pytest.fixture(scope="module")
def small_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("sim94")
    write_run(simulate(2094, 12, post_items=5, items_per_concept=20), d)
    return d


def test_injected_answers_in_a_simulated_run_never_change_the_verdict(small_run):
    calib = {}
    run = adapter94.load_run(small_run, calib)
    for L in run.values():
        for a in L["answers"]:
            calib[a.item_id] = (0.0, 0.35)
    for L in run.values():
        for cid in L["interventions"]:
            for kind in ("HELP", "SHOWN", "NOSRC"):
                calib[f"FRESH-{kind}-{cid[:8]}"] = (0.0, 0.3)
    run = adapter94.load_run(small_run, calib)
    ls = adapter94.standin_for(run)
    checked = 0
    for credit in (1.0, 0.0):
        for lid in sorted(run):
            L = run[lid]
            dirty, shown, injected = contaminate(L, credit)
            for cid, I in sorted(L["interventions"].items()):
                a = engine.evaluate(I, ls, L["answers"], [], L["as_of"][cid])
                b = engine.evaluate(I, ls, dirty, shown, L["as_of"][cid])
                assert (a.outcome, a.p_target, a.bayes_factor) == (b.outcome, b.p_target,
                                                                   b.bayes_factor)
                for j in b.answers:
                    if j.record_id in injected:
                        assert j.exclusion == EXPECTED[injected[j.record_id]]
                checked += 1
    assert checked == 2 * 12 * 7 * 3


# ---- boundaries ---------------------------------------------------------------------------

def test_baseline_is_read_at_delivery_and_nothing_is_written():
    r = Reader()
    engine.evaluate(iv(delivered=1000.0), r, treatment() + outcome_answers([1, 1]), [], 9000.0)
    assert set(r.calls) == {1000.0}
    assert not hasattr(r, "ingest")              # the reader has no write path at all


def test_standin_baseline_ignores_evidence_at_or_after_delivery():
    ls = standin.LearnerStateStandIn()
    for i, c in enumerate([0.0, 0.0, 1.0]):
        ls.ingest({"learner_id": "L1", "concept_id": "C1", "occurred_at": 100.0 * i,
                   "credit": c})
    before = ls.baseline("L1", "C1", 1000.0)
    ls.ingest({"learner_id": "L1", "concept_id": "C1", "occurred_at": 1000.0, "credit": 1.0})
    ls.ingest({"learner_id": "L1", "concept_id": "C1", "occurred_at": 5000.0, "credit": 1.0})
    assert ls.baseline("L1", "C1", 1000.0) == before


def test_verdict_package_never_writes_to_learner_state():
    for p in (ROOT / "verdict").glob("*.py"):
        if p.name == "standin.py":
            continue
        src = p.read_text(encoding="utf-8")
        assert ".ingest(" not in src and "ADD_EVIDENCE" not in src and "ADD_EXPOSURE" not in src


def test_harness_reads_truth_only_in_the_scoring_loader():
    for name in ("calibrate.py", "contaminate.py", "baselines94.py"):
        assert "truth.jsonl" not in (ROOT / "harness" / name).read_text(encoding="utf-8")
    src = (ROOT / "harness" / "adapter94.py").read_text(encoding="utf-8")
    assert src.count('"truth.jsonl"') == 1 and "def load_truth" in src


# ---- decisions ----------------------------------------------------------------------------

def test_no_independent_answer_gives_insufficient_evidence():
    v = engine.evaluate(iv(), Reader(), treatment(), [], as_of=9000.0)
    assert v.outcome == Outcome.INSUFFICIENT_EVIDENCE and v.n_counted == 0
    assert v.p_target is None and "no independent answer" in v.reason


def test_one_answer_never_decides_demonstrated():
    for a, b in [(1.2, 2.8), (2, 2), (6, 4), (19.5, 10.5)]:
        v = engine.evaluate(iv(), Reader(a, b), treatment() + outcome_answers([1]), [], 9000.0)
        assert v.outcome != Outcome.DEMONSTRATED


def test_clear_evidence_decides_both_ways():
    good = engine.evaluate(iv(), Reader(), treatment() + outcome_answers([1] * 8), [], 9000.0)
    bad = engine.evaluate(iv(), Reader(), treatment() + outcome_answers([0] * 4), [], 9000.0)
    assert good.outcome == Outcome.DEMONSTRATED
    assert bad.outcome == Outcome.NOT_YET_DEMONSTRATED


@pytest.mark.parametrize("seed", range(10))
def test_underestimated_non_learner_is_not_called_demonstrated(seed):
    """Baseline far too low (mu0 0.10); the learner learned nothing and answers at chance
    level. The verdict must not read the rise from the baseline as reaching the target."""
    rng = random.Random(seed)
    for a, b in [(0.4, 3.6), (3.0, 27.0)]:
        credits = [float(rng.random() < 0.25) for _ in range(12)]
        v = engine.evaluate(iv(), Reader(a, b), treatment() + outcome_answers(credits), [],
                            9000.0)
        assert v.outcome != Outcome.DEMONSTRATED


@pytest.mark.parametrize("seed", range(10))
def test_overestimated_learner_below_target_is_not_confirmed(seed):
    """Baseline near the target (mu0 0.65, n 4 or 30); the learner is truly below it and
    answers at chance. A high starting estimate must not confirm the target."""
    rng = random.Random(100 + seed)
    for a, b in [(2.6, 1.4), (19.5, 10.5)]:
        credits = [float(rng.random() < 0.30) for _ in range(rng.choice([1, 3, 8]))]
        v = engine.evaluate(iv(), Reader(a, b), treatment() + outcome_answers(credits), [],
                            9000.0)
        assert v.outcome != Outcome.DEMONSTRATED


# ---- determinism --------------------------------------------------------------------------

def test_same_inputs_same_verdict_in_any_order():
    rows = treatment() + outcome_answers([1, 0, 1, 1, 1])
    a = engine.evaluate(iv(), Reader(), rows, [], 9000.0)
    shuffled = list(rows)
    random.Random(3).shuffle(shuffled)
    b = engine.evaluate(iv(), Reader(), shuffled, [], 9000.0)
    assert a.to_dict() == b.to_dict()
    assert a.inputs_sha256 == b.inputs_sha256 and len(a.inputs_sha256) == 64
    c = engine.evaluate(iv(), Reader(), rows[:-1], [], 9000.0)
    assert c.inputs_sha256 != a.inputs_sha256


# ---- simulator ----------------------------------------------------------------------------

def test_scrum93_run_is_unchanged_by_the_new_parameters(tmp_path):
    """Seed 93, 200 per population, defaults: the SCRUM-93 answers file, byte for byte."""
    m = write_run(simulate(93, 200), tmp_path)
    assert m["sha256"]["answers.jsonl"].startswith("9a5c0a8cad24d389")


def test_longer_post_test_needs_a_large_enough_bank():
    with pytest.raises(ValueError):
        simulate(1, 1, post_items=12, items_per_concept=20)
    r = simulate(1, 1, post_items=12, items_per_concept=22)
    seen = {}
    for b in r["answers"]:
        if b["operation"] == "ADD_EVIDENCE":
            key = (b["learner_id"], b["record"]["payload"]["item_id"])
            assert key not in seen, "an item was shown twice"
            seen[key] = 1


def test_answers_after_the_judged_moment_change_nothing():
    """Found by the independent review: a practice answer logged after as_of moved the
    treatment end past as_of and excluded every outcome answer."""
    rows = treatment() + outcome_answers([1, 1, 1, 1, 1, 1], start=2000.0)
    a = engine.evaluate(iv(), Reader(), rows, [], as_of=3000.0)
    late = [ans("T-after", 50_000.0, prod="IV-1"), ans("O-after", 60_000.0, credit=0.0)]
    b = engine.evaluate(iv(), Reader(), rows + late, [], as_of=3000.0)
    assert (a.outcome, a.p_target, a.bayes_factor, a.n_counted) == (
        b.outcome, b.p_target, b.bayes_factor, b.n_counted)


def test_censor_is_part_of_the_input_digest():
    rows = treatment() + outcome_answers([1, 1, 1])
    a = engine.evaluate(iv(), Reader(), rows, [], 9000.0)
    b = engine.evaluate(iv(), Reader(), rows, [], 9000.0, censor_at=2000.0)
    assert a.inputs_sha256 != b.inputs_sha256


def test_two_simultaneous_answers_to_one_item_count_once():
    rows = treatment() + [ans("s1", 3000.0, item="Z"), ans("s2", 3000.0, item="Z")]
    v = engine.evaluate(iv(), Reader(), rows, [], 9000.0)
    got = {j.record_id: j.exclusion for j in v.answers}
    assert got["s1"] is None and got["s2"] == "ITEM_SEEN_BEFORE"


def test_k_counts_every_answer_the_intervention_produced():
    rows = treatment() + [ans("T-unapplied", 1290.0, prod="IV-1", applied=False)]
    ev = engine.prepare(iv(), Reader(), rows, [], 9000.0)
    assert ev["k"] == 1 + 5
