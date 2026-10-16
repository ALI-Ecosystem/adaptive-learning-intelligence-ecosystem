"""Prerequisite links: per-link structural rules, the blind order question, the per-link
decision, RefD arithmetic. No Neo4j, no API key, no network.
Run: .venv/bin/python -m pytest tests/test_validation_prereq.py -q"""
from types import SimpleNamespace as NS

from tests.test_validation_structural import FakeView
from validation import prereq, refd
from validation.contract import Decision, Proposal

A = Decision.ACCEPT_PROVISIONAL


def P(**kw):
    return Proposal(id="P-new", name="Tail recursion", parent_ids=["REC"], **kw)


# ---- structural, per link ------------------------------------------------------
def test_good_links_pass():
    p = P(requires=["REC"], enables=["MEMO"])
    assert prereq.structural_edge(p, "requires", "REC", FakeView()) is None
    assert prereq.structural_edge(p, "enables", "MEMO", FakeView()) is None


def test_only_the_bad_link_fails():
    p = P(requires=["REC", "NOPE"])
    assert prereq.structural_edge(p, "requires", "REC", FakeView()) is None
    assert prereq.structural_edge(p, "requires", "NOPE", FakeView())


def test_prerequisite_of_own_ancestor_fails():
    p = P(enables=["ALG"])                         # ALG is above REC
    assert "ancestor" in prereq.structural_edge(p, "enables", "ALG", FakeView())


def test_cycle_through_new_concept_fails_both_links():
    p = P(requires=["MEMO"], enables=["DP"])       # existing DP -> MEMO
    v = FakeView()
    assert prereq.structural_edge(p, "requires", "MEMO", v)
    assert prereq.structural_edge(p, "enables", "DP", v)


# ---- per-link decision ---------------------------------------------------------
ORDER = {"before": ["REC"], "after": ["MEMO"]}


def test_decision_follows_the_concept_first():
    assert prereq.decide_edge("requires", "REC", None, Decision.REJECT, ORDER, 0.3)[1] == "E2"
    assert prereq.decide_edge("requires", "REC", None, Decision.NEEDS_REVIEW, ORDER, 0.3)[1] == "E3"
    assert prereq.decide_edge("requires", "REC", "bad", A, ORDER, 0.3)[1] == "E1"


def test_agreement_accepts_unless_wikipedia_reverses_it():
    assert prereq.decide_edge("requires", "REC", None, A, ORDER, 0.3) == (A, "E4")
    assert prereq.decide_edge("requires", "REC", None, A, ORDER, None) == (A, "E4")
    assert prereq.decide_edge("requires", "REC", None, A, ORDER, -0.3) == (Decision.NEEDS_REVIEW, "E4a")
    assert prereq.decide_edge("enables", "MEMO", None, A, ORDER, 0.1) == (A, "E4")


def test_opposite_direction_rejects():
    assert prereq.decide_edge("requires", "MEMO", None, A, ORDER, 0.5) == (Decision.REJECT, "E5")


def test_unmarked_link_needs_wikipedia_support_to_reach_teacher():
    assert prereq.decide_edge("requires", "SORT", None, A, ORDER, 0.3) == (Decision.NEEDS_REVIEW, "E6a")
    assert prereq.decide_edge("requires", "SORT", None, A, ORDER, 0.0) == (Decision.REJECT, "E6")
    # weak support (below the 0.10 rescue threshold) is not enough to bother the teacher
    assert prereq.decide_edge("requires", "SORT", None, A, ORDER, 0.05) == (Decision.REJECT, "E6")


def test_no_validator_answer_goes_to_teacher():
    assert prereq.decide_edge("requires", "REC", None, A, None, 0.3)[1] == "E7"


# ---- blind order question ------------------------------------------------------
class OrderClient:
    def __init__(self, before_names, after_names):
        self.before, self.after, self.messages, self.prompt = before_names, after_names, self, ""

    def create(self, model, max_tokens, tools, tool_choice, messages):
        self.prompt = messages[0]["content"]
        lines = [l for l in self.prompt.splitlines() if len(l) > 2 and l[1] == "."]
        pick = lambda names: [l[0] for l in lines if any(l[3:].startswith(n) for n in names)]
        return NS(content=[NS(type="tool_use", input={"before": pick(self.before),
                                                      "after": pick(self.after), "why": ""})],
                  usage=NS(input_tokens=1, output_tokens=1))


class G:
    def concept(self, cid):
        return {"id": cid, "name": {"REC": "Recursion", "MEMO": "Memoization",
                                    "SORT": "Sorting", "DS": "Data structure"}[cid],
                "description": ""}


def test_order_question_is_blind_and_mapped_back():
    client = OrderClient(["Recursion"], ["Memoization"])
    o = prereq.ask_order(client, P(), G(), ["REC", "MEMO"], ["SORT", "DS"])
    assert o["before"] == ["REC"] and o["after"] == ["MEMO"]
    assert "propos" not in client.prompt.lower()     # nothing marks which ones were proposed


def test_audit_priority_when_most_links_fail():
    rej = {"decision": "REJECT", "rule": "E6"}
    ok = {"decision": "ACCEPT_PROVISIONAL", "rule": "E4"}
    assert prereq.audit_priority([rej, rej, ok]) and not prereq.audit_priority([rej, ok, ok])


# ---- RefD arithmetic -----------------------------------------------------------
class FakeWiki:
    LINKS = {"A": ["X", "Y"], "B": ["A", "X", "Z", "Q"]}
    BACK = {"A": ["X", "Z"], "B": []}

    def links(self, t):
        return self.LINKS[t]

    def backlinks(self, t):
        return {"titles": self.BACK[t], "truncated": False}


def test_refd_sign_shows_direction():
    # B's links reference A 3/4 (A itself, X, Z); A's links reference B 0/2
    r = refd.refd(FakeWiki(), "A", "B")
    assert r["refd"] == 0.75 and refd.verdict(r["refd"]) == "supports"
    assert refd.verdict(refd.refd(FakeWiki(), "B", "A")["refd"]) == "reversed"
