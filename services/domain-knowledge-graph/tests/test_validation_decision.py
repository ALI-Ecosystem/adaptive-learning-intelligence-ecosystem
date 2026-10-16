"""Layer 5 (decision rules). Pure logic, no graph, no model.
Run: .venv/bin/python -m pytest tests/test_validation_decision.py -q"""
from validation.contract import Check, Decision, Result
from validation.decision import decide


def C(layer, name, result):
    return Check(layer, name, result, "")


OK = [C("structural", "parent_exists", Result.PASS)]


def blind(role, same_as=None, picked="X"):
    return {"picked_role": role, "picked_id": picked, "same_as": same_as}


def test_structural_fail_and_review():
    assert decide([C("structural", "prereq_cycle", Result.FAIL)], {})[:2] == (Decision.REJECT, 1)
    assert decide([C("structural", "parent_count", Result.REVIEW)], {})[:2] == (Decision.NEEDS_REVIEW, 2)


def test_semantic_reject():
    assert decide(OK + [C("semantic", "semantic_reject", Result.FAIL)], {})[1] == 3


def test_wikidata_duplicate():
    d, rule, extra = decide(OK + [C("external", "wikidata_duplicate", Result.FAIL)],
                            {"external": {"duplicate_of": "uuid-1"}})
    assert (d, rule, extra["duplicate_of"]) == (Decision.REJECT, 4, "uuid-1")


def test_validator_duplicate_beats_agreement():
    d, rule, extra = decide(OK, {"blind": blind("proposed", same_as="C9")})
    assert (d, rule, extra["duplicate_of"]) == (Decision.REJECT, 5, "C9")


def test_agreement_accepts_provisionally():
    assert decide(OK, {"blind": blind("proposed")})[:2] == (Decision.ACCEPT_PROVISIONAL, 6)


def test_disagreement_with_direct_wikidata_support_goes_to_teacher():
    d, rule, extra = decide(OK, {"blind": blind("alternative", picked="ALT"),
                                 "external": {"support": 1}})
    assert (d, rule, extra["validator_parent"]) == (Decision.NEEDS_REVIEW, 7, "ALT")


def test_disagreement_goes_to_teacher_with_both_parents():
    d, rule, extra = decide(OK, {"blind": blind("broader", picked="GP"), "external": {}})
    assert (d, rule, extra["validator_parent"]) == (Decision.NEEDS_REVIEW, 8, "GP")


def test_wikidata_support_through_grandparent_is_not_a_conflict():
    # Wikidata reaches the proposed parent 2 steps up: an ancestor, not direct support
    d, rule, _ = decide(OK, {"blind": blind("narrower"), "external": {"support": 2}})
    assert (d, rule) == (Decision.NEEDS_REVIEW, 8)


def test_no_validator_answer_goes_to_teacher():
    assert decide(OK, {"blind": blind("invalid")})[:2] == (Decision.NEEDS_REVIEW, 9)
    assert decide(OK, {})[:2] == (Decision.NEEDS_REVIEW, 9)
