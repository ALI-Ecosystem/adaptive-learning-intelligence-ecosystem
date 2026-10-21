"""SCRUM-93 validation of the learner simulator.

Every statistical check compares an observed rate with the value the truth sets, using a
99.9% interval (|observed - expected| <= 3.29 standard errors) or a 95% Wilson interval.
The runs are seeded, so the tests are deterministic: a pass is not luck on a re-run.
"""
import importlib.util
import json
import math
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import pytest

from harness import rules as rules_mod
from harness.score import score, wilson
from simulator.concepts import CONCEPTS
from simulator.draws import Draws
from simulator.generator import simulate
from simulator.items import BANK, OPTIONS
from simulator.learner import DAY, ConceptState, Learner
from simulator.populations import POPULATIONS, Params
from simulator.records import write_run

Z999 = 3.29
DKG = Path(__file__).resolve().parents[2] / "domain-knowledge-graph"


def within(k, n, p, z=Z999):
    return abs(k / n - p) <= z * math.sqrt(p * (1 - p) / n)


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture(scope="module")
def answers(run_dir):
    return read_jsonl(run_dir / "answers.jsonl")


@pytest.fixture(scope="module")
def truth(run_dir):
    return read_jsonl(run_dir / "truth.jsonl")


@pytest.fixture(scope="module")
def joined(answers, truth):
    """Each evidence answer with its truth-trace row and population (tests only)."""
    by_rec = {}
    for t in truth:
        for r in t["trace"]:
            by_rec[r["source_record_id"]] = (t["population"], r)
    out = []
    for b in answers:
        if b["operation"] == "ADD_EVIDENCE":
            pop, r = by_rec[b["record"]["source_record_id"]]
            out.append((pop, r, b["record"]["payload"]))
    return out


def single_learner(params: Params, known: bool, misconception=None, seed=1):
    c = CONCEPTS[0]
    lrn = Learner({c.source_id: params}, Draws(seed, 0))
    lrn.states[c.source_id] = ConceptState(known, misconception, forget_at=None)
    return lrn, c


# ---- 1. reproducibility ---------------------------------------------------------------------

def test_same_seed_gives_identical_output(tmp_path):
    a = write_run(simulate(11, 12), tmp_path / "a")
    b = write_run(simulate(11, 12), tmp_path / "b")
    c = write_run(simulate(12, 12), tmp_path / "c")
    assert a["sha256"] == b["sha256"]
    assert (tmp_path / "a" / "answers.jsonl").read_bytes() == (tmp_path / "b" / "answers.jsonl").read_bytes()
    assert a["sha256"]["answers.jsonl"] != c["sha256"]["answers.jsonl"]


# ---- 2. answers match the truth that produced them ------------------------------------------

def test_learner_set_to_succeed_80_percent_answers_about_80_percent():
    lrn, c = single_learner(Params(p_S=0.20, p_help=0.0), known=True)
    items, n = BANK[c.source_id], 4000
    k = sum(lrn.answer(items[i % len(items)], 0.0, False, f"k{i}")[0].correct for i in range(n))
    p, lo, hi = wilson(k, n)
    assert within(k, n, 0.80), f"{p:.3f} [{lo:.3f}, {hi:.3f}]"


def test_unaided_known_answers_in_run_match_one_minus_slip(joined):
    rows = [(r, p) for pop, r, p in joined
            if r["known"] and not r["misconception"] and not p["had_help"]]
    k = sum(p["correct"] for _, p in rows)
    assert len(rows) > 5000 and within(k, len(rows), 0.90)


# ---- 3. learning, forgetting, guessing and slips --------------------------------------------

def _rate(joined, pop, phase):
    rows = [p["correct"] for q, r, p in joined if q == pop and p["activity"] == phase]
    return sum(rows), len(rows)


def test_learning_raises_correct_answers(joined):
    pre, post = _rate(joined, "LEARNS", "PRE_TEST"), _rate(joined, "LEARNS", "POST_TEST")
    assert wilson(*post)[1] > wilson(*pre)[2] + 0.30          # intervals far apart
    pre0, post0 = _rate(joined, "DOES_NOT_LEARN", "PRE_TEST"), _rate(joined, "DOES_NOT_LEARN", "POST_TEST")
    assert within(*pre0, 0.25) and within(*post0, 0.25)


def test_intervention_effect_is_in_the_truth(truth):
    def due(pop):
        v = [s["learned_due_to_intervention"] for t in truth if t["population"] == pop
             for s in t["checkpoints"]["immediate"]["concepts"].values()]
        return sum(v) / len(v)
    assert due("LEARNS") > 0.5 and due("DOES_NOT_LEARN") == 0.0


def test_forgetting_lowers_retention(truth):
    def known(pop, cp):
        v = [s["known"] for t in truth if t["population"] == pop
             for s in t["checkpoints"][cp]["concepts"].values()]
        return sum(v) / len(v)
    fast_drop = known("LEARNS_THEN_FORGETS", "immediate") - known("LEARNS_THEN_FORGETS", "delayed")
    slow_drop = known("LEARNS", "immediate") - known("LEARNS", "delayed")
    assert fast_drop > 0.3 and fast_drop > slow_drop + 0.2


def test_forgetting_grows_with_delay(truth):
    rows = [(t["times"]["delay_days"], s["known"]) for t in truth
            if t["population"] == "LEARNS_THEN_FORGETS"
            for s in t["checkpoints"]["delayed"]["concepts"].values()]
    rows.sort()
    short, long_ = rows[:len(rows) // 2], rows[len(rows) // 2:]
    assert sum(k for _, k in short) / len(short) > sum(k for _, k in long_) / len(long_)


def test_forgetting_curve_is_the_power_law():
    p = Params(tau_days=2.0, d=1.0)
    lrn, c = single_learner(p, known=True)
    n, t = 20000, 2.0 * DAY
    alive = 0
    for i in range(n):
        lrn._draw_forget(c.source_id, 0.0, "curve", i)
        alive += lrn.states[c.source_id].forget_at > t
    assert within(alive, n, (1 + 2.0 / 2.0) ** -1.0)        # S(tau) = 2^-d = 0.5


def test_guessing_picks_options_uniformly():
    lrn, c = single_learner(Params(p_help=0.0), known=False)
    items, n = BANK[c.source_id], 4000
    ans = [lrn.answer(items[i % len(items)], 0.0, False, f"g{i}")[0] for i in range(n)]
    assert within(sum(a.correct for a in ans), n, 0.25)
    pos = Counter(OPTIONS.index(a.chosen_option) for a in ans)
    assert all(within(pos[i], n, 0.25) for i in range(4))


@pytest.mark.parametrize("slip", [0.05, 0.30])
def test_slip_rate_sets_errors_of_a_knowing_learner(slip):
    lrn, c = single_learner(Params(p_S=slip, p_help=0.0), known=True)
    items, n = BANK[c.source_id], 4000
    k = sum(not lrn.answer(items[i % len(items)], 0.0, False, f"s{i}")[0].correct for i in range(n))
    assert within(k, n, slip)


def test_help_raises_correctness_only_where_given(joined):
    assert all(not p["had_help"] for _, _, p in joined if p["activity"] != "PRACTICE")
    helped = [p["correct"] for _, r, p in joined if not r["known"] and p["had_help"]]
    alone = [p["correct"] for _, r, p in joined if not r["known"] and not p["had_help"]]
    assert wilson(sum(helped), len(helped))[1] > wilson(sum(alone), len(alone))[2]


def test_confidence_follows_state_and_bias(joined):
    def med(pop, known):
        v = sorted(p["confidence"] for q, r, p in joined if q == pop and r["known"] == known)
        return v[len(v) // 2]
    assert med("DOES_NOT_LEARN", False) <= 2 and med("CONFIDENT_RIGHT", True) >= 4
    # calibrated but not a give-away: some overlap between known and unknown answers
    hi_unknown = [p["confidence"] >= 4 for q, r, p in joined
                  if q == "DOES_NOT_LEARN" and not r["known"]]
    assert 0.05 < sum(hi_unknown) / len(hi_unknown) < 0.25
    assert med("CONFIDENT_WRONG", False) >= 4          # confident and wrong


# ---- 4. misconceptions -----------------------------------------------------------------------

def test_misconception_pulls_to_its_own_distractor(answers, truth):
    held = {t["learner_id"]: t["misconceptions_at_start"] for t in truth
            if t["population"] == "HOLDS_MISCONCEPTION"}
    items = {it.item_id: it for v in BANK.values() for it in v}
    match = other = 0
    per_other = Counter()
    for b in answers:
        p = b["record"]["payload"] if b["operation"] == "ADD_EVIDENCE" else None
        if not p or b["learner_id"] not in held or p["activity"] != "PRE_TEST" or p["correct"]:
            continue
        mis = held[b["learner_id"]][b["concept"]["concept_id"]]
        opt = items[p["item_id"]].option_for(mis)
        if opt is None:
            continue
        if p["chosen_option"] == opt:
            match += 1
        else:
            other += 1
            per_other[p["chosen_option"]] += 1
    n = match + other
    assert wilson(match, n)[1] > 1 / 3                 # more than chance among 3 distractors
    assert match > max(per_other.values()) * 3          # far above any single other option


def test_partial_learners_learn_one_or_two_concepts(truth):
    chosen_known = chosen = 0
    for t in truth:
        if t["population"] != "LEARNS_PARTIALLY":
            continue
        assert len(t["set_to_learn"]) in (1, 2)
        for cid, s in t["checkpoints"]["immediate"]["concepts"].items():
            if cid in t["set_to_learn"]:
                chosen += 1
                chosen_known += s["learned_due_to_intervention"]
            else:
                assert not s["known"]
    assert chosen_known / chosen > 0.7                  # the chosen concepts ARE learned


# ---- 5. the twin -----------------------------------------------------------------------------

def test_twin_equals_learner_before_the_intervention(truth):
    for t in truth:
        for r in t["trace"]:
            if r["phase"] == "PRE_TEST":
                assert r["known"] == r["twin_known"]
        if t["population"] == "DOES_NOT_LEARN":
            assert all(r["known"] == r["twin_known"] for r in t["trace"])


@pytest.mark.parametrize("pop", ["LEARNS_THEN_FORGETS", "CONFIDENT_RIGHT", "HOLDS_MISCONCEPTION"])
def test_intervention_never_takes_knowledge_away(pop):
    """twin knows => learner knows, everywhere. The intervention can only add."""
    from simulator.populations import BY_NAME
    from simulator.generator import simulate as sim
    out = sim(5, 400, populations=(BY_NAME[pop],))
    for t in out["truth"]:
        for r in t["trace"]:
            assert r["known"] or not r["twin_known"]
        for cp in t["checkpoints"].values():
            for s in cp["concepts"].values():
                assert s["known"] or not s["twin_known"]


def test_tests_do_not_teach(truth):
    """No learning inside a test phase: the state a test begins with is the state it measures
    (only forgetting can happen within a test)."""
    for t in truth:
        last = {}
        for r in t["trace"]:
            k = (r["concept_id"], r["phase"])
            if r["phase"] != "PRACTICE" and k in last:
                assert not (r["known"] and not last[k])
            last[k] = r["known"]


# ---- 6. no leakage ---------------------------------------------------------------------------

TOP = {"schema", "request_id", "sender", "learner_id", "operation", "sent_at", "concept", "record"}
PAYLOAD = {"activity", "item_id", "chosen_option", "correct", "had_help", "attempt_number",
           "confidence", "intervention_id", "kind"}


def test_truth_never_appears_in_the_answer_stream(run_dir, answers, truth):
    for b in answers:
        assert set(b) == TOP
        assert set(b["record"]) == {"source_record_id", "occurred_at", "payload"}
        assert set(b["record"]["payload"]) <= PAYLOAD
    text = (run_dir / "answers.jsonl").read_text(encoding="utf-8")
    banned = [p.name for p in POPULATIONS] + ["twin", "known", "misconception", "p_T", "p_L0",
                                               "tau", "path", "GUESS", "SLIP", "KNOWS"]
    banned += [m.misconception_id for c in CONCEPTS for m in c.misconceptions]
    for word in banned:
        assert word not in text, word


def test_file_order_does_not_reveal_population(answers, truth):
    pop = {t["learner_id"]: t["population"] for t in truth}
    order = list(dict.fromkeys(b["learner_id"] for b in answers))
    same = sum(pop[a] == pop[b] for a, b in zip(order, order[1:])) / (len(order) - 1)
    assert same < 0.25                                   # about 1/7 when populations are mixed


# ---- 7. compatibility with the Learner Graph contract (SCRUM-92) ----------------------------

def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not (DKG / "learner_graph" / "contract.py").exists(),
                    reason="Domain Knowledge Graph service not next to this one")
def test_answer_records_pass_the_learner_graph_contract(answers):
    contract = _load(DKG / "learner_graph" / "contract.py", "lg_contract")
    for b in answers[::50]:
        r = contract.parse({"body": b, "signature": "AAAA"})
        assert r.operation.value in ("ADD_EVIDENCE", "ADD_EXPOSURE") and r.concept_id


@pytest.mark.skipif(not (DKG / "placement" / "ids.py").exists(),
                    reason="Domain Knowledge Graph service not next to this one")
def test_concept_ids_are_the_dkg_ids():
    ids = _load(DKG / "placement" / "ids.py", "dkg_ids")
    for c in CONCEPTS:
        assert c.concept_id == ids.concept_uuid(c.source_id)


# ---- 8. the naive baseline, scored end to end ------------------------------------------------

def test_rules_module_never_reads_the_truth():
    """Static check on the code (docstrings excluded): no name or string mentions truth,
    and the only file it opens is answers.jsonl."""
    import ast
    tree = ast.parse(Path(rules_mod.__file__).read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    words = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    words += [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    words += [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert not any("truth" in w.lower() for w in words)
    assert sorted(w for w in words if w.endswith(".jsonl")) == ["answers.jsonl", "decisions.jsonl"]


def test_naive_rule_is_scored_against_the_truth(run_dir):
    from conftest import N
    rules_mod.run(run_dir)
    rows = score(run_dir)["rows"]
    main = [r for r in rows if r["target"] == "learned_due_to_intervention"]
    for rule in rules_mod.RULES:
        for cp in ("immediate", "delayed"):
            sel = {r["population"]: r for r in main if r["rule"] == rule and r["checkpoint"] == cp}
            assert set(sel) == {"ALL"} | {p.name for p in POPULATIONS}
            assert sel["ALL"]["n"] == N * len(POPULATIONS) * len(CONCEPTS)
            assert sum(v["n"] for k, v in sel.items() if k != "ALL") == sel["ALL"]["n"]
            assert sel["DOES_NOT_LEARN"]["positives"] == 0
            for r in sel.values():
                assert r["tp"] + r["fp"] + r["fn"] + r["tn"] == r["n"]
            d = sel["DOES_NOT_LEARN"]          # nobody learned: every "learned" is an error
            assert d["error"][0] == d["false_learned"][0]
            lo, hi = sel["ALL"]["error_cluster_ci"]
            assert lo < sel["ALL"]["error"][0] < hi
