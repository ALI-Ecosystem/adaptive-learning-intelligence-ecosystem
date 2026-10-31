"""SCRUM-96: the outcome engine (retention, near transfer, error repetition).

The acceptance list of the task, as tests:
  * later independent answers update the verdict into retention / transfer / repetition outcomes
  * NOT_RETAINED is never issued without an earlier demonstrated success
  * practice errors never count against the learner
  * missing checks are reported as coverage, not guessed
plus: the decision table, the retention clock, versions (every version kept, each equal to a
fresh evaluation at its moment), explanations reported only, the module stays a measurement.
"""
import math
from dataclasses import replace
from pathlib import Path

import pytest

from harness import adapter96 as A6
from outcome import engine as E
from outcome.misconception import (PRIOR, R0, AnswerBuiltMisconceptions, Repetition,
                                   option_map)
from simulator.concepts import CONCEPTS
from simulator.config import SCRUM96, items_needed
from simulator.generator import simulate
from simulator.items import build_bank, TRANSFER_BANK
from simulator.populations import POPULATIONS_96
from simulator.records import write_run
from verdict.contracts import AnswerRecord, Intervention
from verdict.standin import LearnerStateStandIn

DAY = 86_400.0
S, N, I = E.SUP, E.NOT, E.INS


# ---- the decision table ------------------------------------------------------------------------

def dims(a, r, t):
    return {E.ACQ: {"status": a, "p": 0.9}, E.RET: {"status": r, "p": 0.9},
            E.TRF: {"status": t, "p": 0.1}}


@pytest.mark.parametrize("a, r, t, err, want", [
    (N, I, I, E.NA, E.NOT_YET),            # failed alone
    (I, N, I, E.NA, E.NOT_YET),            # nothing earlier, failed at the review point
    (N, S, I, E.NA, E.RETAINED),           # failed early, passed later: not a failure
    (S, N, I, E.NA, E.NOT_RETAINED),
    (S, N, N, S, E.NOT_RETAINED),          # forgetting first
    (S, I, I, S, E.PERSISTS),
    (S, I, N, S, E.PERSISTS),              # 3b before SHALLOW (decision 3a)
    (S, I, N, I, E.SHALLOW),
    (I, S, N, E.NA, E.SHALLOW),
    (S, S, I, E.NA, E.RETAINED),
    (S, S, S, N, E.RETAINED),
    (S, I, I, I, E.DEMONSTRATED),
    (S, I, S, E.NA, E.DEMONSTRATED),
    (I, I, N, E.NA, E.INSUFFICIENT),       # transfer failure alone is not SHALLOW
    (I, I, I, S, E.INSUFFICIENT),          # repetition alone is not PERSISTS
])
def test_decision_table(a, r, t, err, want):
    assert E.decide(dims(a, r, t), err, None)[1] == want


def test_not_retained_requires_acquisition_supported():
    for r_ in (S, N, I):
        for t in (S, N, I):
            for err in (S, N, I, E.NA):
                for a in (N, I):
                    assert E.decide(dims(a, r_, t), err, None)[1] != E.NOT_RETAINED


def test_illusion_rule_needs_the_perceived_input():
    assert E.decide(dims(N, I, I), E.NA, "HIGH")[1] == E.ILLUSION
    assert E.decide(dims(N, I, I), E.NA, None)[1] == E.NOT_YET
    assert E.decide(dims(S, I, I), E.NA, "HIGH")[1] == E.DEMONSTRATED


# ---- the error-repetition measure ----------------------------------------------------------------

def test_repetition_threshold_and_rule():
    assert R0 == pytest.approx(0.1 / 3)
    r = Repetition("M", *PRIOR)
    assert r.read()["status"] == I and r.read()["n"] == 0
    for c in (1, 0, 1, 0, 1, 0):
        r.add(c)
    assert r.read()["status"] == S                 # 3 picks in 6: far above slip/3
    r2 = Repetition("M", *PRIOR)
    for _ in range(20):
        r2.add(0)
    assert r2.read()["status"] == N                # never picked in 20


def test_misconception_state_from_answers_before_delivery():
    imap = {"I1": {"A": None, "B": "M1", "C": "M2", "D": "M3"},
            "I2": {"A": "M1", "B": None, "C": "M2", "D": "M4"}}
    ms = AnswerBuiltMisconceptions({"C": ["M1", "M2", "M3", "M4"]}, imap)
    ans = [rec("r1", 10, "I1", "B", 0), rec("r2", 20, "I2", "A", 0),
           rec("r3", 500, "I1", "C", 0)]                         # after delivery: ignored
    st = ms.state("L", "C", ans, as_of=100)
    assert st["M1"][:2] == (2.5, 1.5) and st["M1"][2]           # picked twice
    assert st["M2"][:2] == (0.5, 3.5) and not st["M2"][2]       # carried, never picked
    assert st["M3"][:2] == (0.5, 2.5) and not st["M3"][2]
    assert st["M4"][:2] == (0.5, 2.5)


# ---- the retention clock --------------------------------------------------------------------------

def rec(rid, t, item, opt, credit, prod="PROBE:L", phase=None, help_=False, attempt=1,
        concept="C", b=0.0):
    return AnswerRecord(record_id=rid, learner_id="L", concept_id=concept,
                        cognitive_level="UNSPECIFIED", occurred_at=float(t), item_id=item,
                        chosen_option=opt, credit=float(credit), attempt_number=attempt,
                        help_before_answer=help_, producing_intervention_id=prod,
                        producing_intent="PROBE", item_b=b, item_b_se=0.05)


IV = Intervention("IV", "L", "C", "UNSPECIFIED", "INSTRUCT", 0.70, delivered_at=1000.0,
                  completed_at=2000.0)
OPTS = ("A", "B", "C", "D")


def synthetic_case(blocks, meta=None, practice=(), horizon=None, **kw):
    """blocks: [(start_time, n, n_correct, activity_type or None)] -> a Case on a fresh
    stand-in (baseline from no evidence)."""
    ans, meta = list(practice), dict(meta or {})
    imap = {}
    k = 0
    for t0, n, n_ok, kind in blocks:
        for j in range(n):
            k += 1
            item = f"X{k}"
            imap[item] = {"A": None, "B": "M1", "C": "M2", "D": "M3"}
            ok = j < n_ok
            ans.append(rec(f"r{k:04d}", t0 + 60 * j, item, "A" if ok else "C", ok))
            if kind:
                meta[f"r{k:04d}"] = {"activity_type": kind}
    ls = LearnerStateStandIn()
    mr = AnswerBuiltMisconceptions({"C": ["M1", "M2", "M3"]}, imap)
    end = horizon or (max(a.occurred_at for a in ans) + 30 * DAY)
    return E.Case(IV, ls, mr, ans, [], meta, imap, end, **kw)


def test_retention_point_and_overdue():
    case = synthetic_case([(3000, 8, 8, None)])
    r = E.run_case(case)
    h = case.reader.config()["h_base_days"]
    assert r.t_end == 2000.0
    assert (r.t_r - r.t_end) / DAY == pytest.approx(h * math.log2(1 / 0.9))   # 2.13 days
    assert (r.overdue_at - r.t_end) / DAY == pytest.approx(2 * h * math.log2(1 / 0.9))


def test_dimension_by_time_and_declared_type():
    t_r = 2000 + 14 * math.log2(1 / 0.9) * DAY
    case = synthetic_case([(3000, 8, 8, None), (3000 + 3600, 4, 0, "TRANSFER_PROBLEM"),
                           (t_r + 3600, 8, 8, None)])
    obs = {rid: d for rid, _, d in E.run_case(case).observations}
    dims_ = [obs[f"r{k:04d}"] for k in range(1, 21)]
    assert dims_ == [E.ACQ] * 8 + [E.TRF] * 4 + [E.RET] * 8
    # the same answers with no declared type are acquisition: novelty is never guessed
    plain = synthetic_case([(3000, 8, 8, None), (3000 + 3600, 4, 0, None)])
    assert {d for _, _, d in E.run_case(plain).observations} == {E.ACQ}


def test_the_three_main_outcomes():
    t_r = 2000 + 14 * math.log2(1 / 0.9) * DAY
    good = E.run_case(synthetic_case([(3000, 8, 8, None), (t_r + 3600, 8, 8, None)])).final
    assert good["outcome"] == E.RETAINED
    gone = E.run_case(synthetic_case([(3000, 8, 8, None), (t_r + 3600, 8, 0, None)])).final
    assert gone["outcome"] == E.NOT_RETAINED
    shallow = E.run_case(synthetic_case([(3000, 8, 8, None),
                                         (3600 * 2, 8, 0, "TRANSFER_PROBLEM")])).final
    assert shallow["outcome"] == E.SHALLOW
    never = E.run_case(synthetic_case([(3000, 8, 0, None), (t_r + 3600, 8, 0, None)])).final
    assert never["outcome"] == E.NOT_YET


def test_missing_checks_are_reported_not_guessed():
    r = E.run_case(synthetic_case([(3000, 8, 8, None)]))
    f = r.final
    assert f["outcome"] == E.DEMONSTRATED           # provisional, not RETAINED
    checks = {c["dimension"]: c["state"] for c in f["checks"]}
    assert checks[E.RET] == E.OVERDUE and checks[E.TRF] == E.OVERDUE
    assert checks[E.ACQ] == E.RESOLVED
    assert {m["dimension"] for m in f["missing"]} == {E.RET, E.TRF}
    triggers = [v["trigger"] for v in r.versions]
    assert "TIME:OVERDUE" in triggers                 # time alone issues a version


def test_late_check_is_resolved_late():
    late = 2000 + 3 * 14 * math.log2(1 / 0.9) * DAY
    f = E.run_case(synthetic_case([(3000, 8, 8, None), (late, 8, 8, None)])).final
    checks = {c["dimension"]: c["state"] for c in f["checks"]}
    assert checks[E.RET] == E.RESOLVED_LATE and f["outcome"] == E.RETAINED


def test_practice_errors_never_count():
    """Answers produced by the intervention are IN_TREATMENT. Their NUMBER is the treatment
    length k (SCRUM-94: it widens the prior); their CORRECTNESS and the options picked never
    count: six wrong practice answers, all on one misconception's option, give exactly what
    six right ones give."""
    imap_p = {f"P{j}": {"A": None, "B": "M1", "C": "M2", "D": "M3"} for j in range(6)}

    def with_practice(opt, ok):
        pr = [replace(rec(f"p{j}", 1100 + 60 * j, "x", opt, ok, prod="IV"), item_id=f"P{j}")
              for j in range(6)]
        c = synthetic_case([(3000, 8, 8, None)], practice=pr)
        c.item_map.update(imap_p)
        return E.run_case(c).final

    right, wrong = with_practice("A", 1), with_practice("C", 0)
    for k in ("outcome", "dimensions", "error_repetition", "checks"):
        assert right[k] == wrong[k], k


def test_explanations_are_reported_only():
    t0 = 3000
    case = synthetic_case([(t0, 8, 8, None)])
    expl = [replace(rec(f"x{j}", t0 + 900 + j, f"EXP{j}", None, 0.1), item_b=0.0, item_b_se=0.0)
            for j in range(3)]
    meta = {f"x{j}": {"activity_type": "EXPLANATION", "grade": 0.1} for j in range(3)}
    with_x = replace(case, answers=case.answers + expl, meta={**case.meta, **meta})
    a, b = E.run_case(case).final, E.run_case(with_x).final
    assert b["explanation"]["n"] == 3 and b["explanation"]["mean_grade"] == 0.1
    assert a["outcome"] == b["outcome"] and a["dimensions"] == b["dimensions"]


def test_versions_kept_and_equal_to_fresh_evaluation():
    t_r = 2000 + 14 * math.log2(1 / 0.9) * DAY
    case = synthetic_case([(3000, 8, 8, None), (6000, 4, 1, "TRANSFER_PROBLEM"),
                           (t_r + 3600, 8, 2, None)])
    r = E.run_case(case)
    assert [v["version"] for v in r.versions] == list(range(1, len(r.versions) + 1))
    assert all(v["previous"] == v["version"] - 1 for v in r.versions[1:])
    assert len({v["fingerprint"] for v in r.versions}) == len(r.versions)
    for v in r.versions:
        snap = E.snapshot(case, v["as_of"])
        for k in ("outcome", "rule", "dimensions", "error_repetition", "checks"):
            assert snap[k] == v[k], (v["version"], k)


# ---- on a simulator run ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sim96(tmp_path_factory):
    d = tmp_path_factory.mktemp("sim96")
    write_run(simulate(12, 12, populations=POPULATIONS_96, post_items=8,
                       items_per_concept=items_needed(8, SCRUM96), config=SCRUM96), d)
    bank = build_bank(items_needed(8, SCRUM96))
    calib = {it.item_id: (0.0, 0.1) for items in bank.values() for it in items}
    calib.update({it.item_id: (0.3, 0.1) for items in TRANSFER_BANK.values() for it in items})
    run = A6.load_run96(d, calib)
    items = A6.load_items(d)
    imap = option_map(items)
    cm = A6.concept_misconceptions(items, {c.source_id: c.concept_id for c in CONCEPTS})
    return d, run, A6.standin_for96(run), imap, AnswerBuiltMisconceptions(cm, imap)


def cases(sim):
    d, run, ls, imap, mr = sim
    for lid in sorted(run):
        L = run[lid]
        for cid in sorted(L["interventions"]):
            yield lid, cid, L, E.Case(L["interventions"][cid], ls, mr, L["answers"], [],
                                      L["meta"], imap, L["horizon"])


def test_on_run_not_retained_only_after_shown(sim96):
    n = 0
    for _, _, _, case in cases(sim96):
        for v in E.run_case(case).versions:
            if v["outcome"] == E.NOT_RETAINED:
                n += 1
                assert v["dimensions"][E.ACQ]["status"] == E.SUP
    assert n > 0


def test_on_run_never_checked_learners(sim96):
    _, run, *_ = sim96
    seen = 0
    for lid, cid, L, case in cases(sim96):
        if not L["never_checked"]:
            continue
        seen += 1
        assert L["removed"] > 0
        f = E.run_case(case).final
        assert f["outcome"] not in (E.RETAINED, E.NOT_RETAINED)
        assert {c["dimension"]: c["state"] for c in f["checks"]}[E.RET] == E.OVERDUE
    assert seen > 0


def test_never_checked_is_keyed_and_near_the_share():
    ids = [f"learner-{i}" for i in range(4000)]
    share = sum(A6.never_checked(x) for x in ids) / len(ids)
    assert abs(share - A6.NEVER_SHARE) < 3.29 * math.sqrt(0.16 / 4000)
    assert [A6.never_checked(x) for x in ids[:50]] == [A6.never_checked(x) for x in ids[:50]]


def test_reader_is_never_written(sim96, monkeypatch):
    _, _, ls, _, _ = sim96
    monkeypatch.setattr(ls, "ingest", lambda *_: (_ for _ in ()).throw(AssertionError("write")))
    for _, _, _, case in list(cases(sim96))[:6]:
        E.run_case(case)


def test_outcome_package_reads_no_truth_and_writes_nothing():
    root = Path(__file__).resolve().parents[1] / "outcome"
    for p in root.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "truth" not in src.replace("truth decides", "").replace("the truth", "") or \
            p.name == "misconception.py"
        assert ".ingest(" not in src and "ADD_EVIDENCE" not in src
        assert "import simulator" not in src and "from simulator" not in src


def test_output_is_a_measurement_not_a_diagnosis():
    f = E.run_case(synthetic_case([(3000, 8, 8, None)])).final
    import json
    text = json.dumps(f).lower()
    for word in ("because", "recommend", "should", "schedule", "next_activity"):
        assert word not in text


# ---- regressions from the independent review ---------------------------------------------------

def test_versions_equal_snapshot_with_ties():
    case = synthetic_case([(3000, 8, 6, None)])
    tied = [replace(a, occurred_at=3000.0 + 60 * (i // 2)) for i, a in enumerate(case.answers)]
    case = replace(case, answers=tied)
    for v in E.run_case(case).versions:
        snap = E.snapshot(case, v["as_of"])
        assert snap["dimensions"] == v["dimensions"] and snap["outcome"] == v["outcome"]


def test_late_treatment_answer_uses_fresh_evaluation():
    case = synthetic_case([(3000, 8, 8, None)])
    late = replace(rec("late", 3000 + DAY, "LATE", "A", 1, prod="IV"))
    case = replace(case, answers=case.answers + [late])
    r = E.run_case(case)
    early = [v for v in r.versions if v["as_of"] < 3000 + DAY]
    assert early and early[-1]["outcome"] == E.DEMONSTRATED     # data of that moment only
    for v in r.versions:
        assert E.snapshot(case, v["as_of"])["outcome"] == v["outcome"]


def test_error_check_resolved_only_through_in_scope_observations():
    """Failed acquisition: discriminating answers exist but none is in scope, so the
    error-repetition check stays open (listed as missing)."""
    imap_pre = {"PRE": {"A": None, "B": "M1", "C": "M2", "D": "M3"}}
    pre = [replace(rec("pre", 500, "PRE", "C", 0), producing_intervention_id="PRE:L")]
    case = synthetic_case([(3000, 8, 0, None)], practice=pre)
    case.item_map.update(imap_pre)
    f = E.run_case(case).final
    assert f["dimensions"][E.ACQ]["status"] == E.NOT
    assert "M2" in f["error_repetition"] and f["error_repetition"]["M2"]["n"] == 0
    checks = {c["dimension"]: c["state"] for c in f["checks"]}
    assert checks[E.ERR] == E.OVERDUE
    assert E.ERR in {m["dimension"] for m in f["missing"]}


def test_answer_exactly_at_overdue_is_late():
    r0 = E.run_case(synthetic_case([(3000, 8, 8, None)]))
    case = synthetic_case([(3000, 8, 8, None), (r0.overdue_at, 1, 1, None)])
    f = E.run_case(case).final
    assert {c["dimension"]: c["state"] for c in f["checks"]}[E.RET] == E.RESOLVED_LATE
