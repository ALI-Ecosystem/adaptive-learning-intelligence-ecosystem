"""Layer 1 (deterministic rules) on a small in-memory graph. No Neo4j, no API key.
Run: .venv/bin/python -m pytest tests/test_validation_structural.py -q

The graph:
    CS (0) <- Algorithms (1) <- Recursion (computer science) (2)
    CS (0) <- Data structure (1) <- Stack (abstract data type) (2)
    ME (0) <- Stack (mechanical) (1)
    Deep (5) under Recursion's branch, Amb (2) is a disambiguation page
    prerequisites: Recursion -> Dynamic programming -> Memoization
"""
from validation.contract import Decision, Proposal, Result, base_name, normalize_name
from validation.structural import run
from placement.ids import concept_uuid, new_concept_uuid

CONCEPTS = {
    "CS": ("Computer science", 0, None), "ALG": ("Algorithms", 1, "CS"),
    "REC": ("Recursion (computer science)", 2, "ALG"), "DS": ("Data structure", 1, "CS"),
    "STK": ("Stack (abstract data type)", 2, "DS"), "ME": ("Mechanical engineering", 0, None),
    "STKM": ("Stack (mechanical)", 1, "ME"), "DP": ("Dynamic programming", 2, "ALG"),
    "MEMO": ("Memoization", 3, "DP"), "DEEP": ("Very deep concept", 5, "REC"),
    "AMB": ("Mercury", 2, "CS"),
}
PREREQ = {("REC", "DP"), ("DP", "MEMO")}


class FakeView:
    def __init__(self, proposals=()):
        self.proposals = list(proposals)

    def get_concept(self, cid):
        if cid not in CONCEPTS:
            return None
        name, level, _ = CONCEPTS[cid]
        return {"id": cid, "concept_id": concept_uuid(cid), "name": name, "level": level,
                "trust": "provisional" if cid == "DP" else "trusted",
                "disambiguation_suspect": cid == "AMB"}

    def ancestors(self, cid):
        out, cur = set(), CONCEPTS[cid][2]
        while cur:
            out.add(cur); cur = CONCEPTS[cur][2]
        return out

    def prereq_reachable(self, src, dst):
        frontier, seen = [src], set()
        while frontier:
            n = frontier.pop()
            for a, b in PREREQ:
                if a == n and b not in seen:
                    if b == dst:
                        return True
                    seen.add(b); frontier.append(b)
        return False

    def concepts_named_like(self, name):
        return [{"id": k, "concept_id": concept_uuid(k), "name": v[0]} for k, v in CONCEPTS.items()]

    def proposals_named_like(self, name, exclude_id):
        return [q for q in self.proposals if q["id"] != exclude_id]


def P(name="Tail recursion", parents=("REC",), **kw):
    return Proposal(id="P-new", name=name, parent_ids=list(parents), **kw)


def results(checks):
    return {c.check: c.result for c in checks}


# ---- a correct placement passes layer 1 and goes on -------------------------
def test_correct_placement_continues():
    checks, decision, dup = run(P(requires=["REC"]), FakeView())
    assert decision is None and dup is None
    assert all(c.result is Result.PASS for c in checks)


# ---- parent rules -----------------------------------------------------------
def test_unknown_parent_rejected():
    checks, decision, _ = run(P(parents=["NOPE"]), FakeView())
    assert decision is Decision.REJECT and results(checks)["parent_exists"] is Result.FAIL


def test_two_parents_rejected():
    _, decision, _ = run(P(parents=["REC", "ALG"]), FakeView())
    assert decision is Decision.REJECT


def test_new_top_level_field_needs_teacher():
    checks, decision, _ = run(P(name="Quantum gardening", parents=[]), FakeView())
    assert decision is Decision.NEEDS_REVIEW and results(checks)["parent_count"] is Result.REVIEW


def test_too_deep_and_ambiguous_and_provisional_parents_warn():
    assert results(run(P(parents=["DEEP"]), FakeView())[0])["depth"] is Result.WARN
    assert results(run(P(parents=["AMB"]), FakeView())[0])["parent_ambiguous"] is Result.WARN
    assert results(run(P(parents=["DP"]), FakeView())[0])["parent_exists"] is Result.WARN
    assert run(P(parents=["DEEP"]), FakeView())[1] is None     # warnings do not decide


# ---- prerequisite rules -----------------------------------------------------
def test_unknown_prerequisite_rejected():
    _, decision, _ = run(P(requires=["NOPE"]), FakeView())
    assert decision is Decision.REJECT


def test_self_prerequisite_rejected():
    checks, decision, _ = run(P(requires=["P-new"]), FakeView())
    assert decision is Decision.REJECT and results(checks)["prereq_self"] is Result.FAIL


def test_two_cycle_rejected():
    checks, decision, _ = run(P(requires=["DP"], enables=["DP"]), FakeView())
    assert decision is Decision.REJECT and results(checks)["prereq_cycle"] is Result.FAIL


def test_longer_cycle_rejected():
    # existing REC -> DP -> MEMO; new concept requires MEMO and enables REC: a loop
    checks, decision, _ = run(P(parents=["ALG"], requires=["MEMO"], enables=["REC"]), FakeView())
    assert decision is Decision.REJECT and results(checks)["prereq_cycle"] is Result.FAIL


def test_prerequisite_of_own_parent_or_ancestor_rejected():
    for target in ("REC", "ALG"):
        checks, decision, _ = run(P(enables=[target]), FakeView())
        assert decision is Decision.REJECT
        assert results(checks)["prereq_vs_hierarchy"] is Result.FAIL


def test_too_many_prerequisites_rejected():
    _, decision, _ = run(P(requires=["CS", "ALG", "DS", "STK", "DP", "MEMO"]), FakeView())
    assert decision is Decision.REJECT


# ---- duplicates -------------------------------------------------------------
def test_exact_duplicate_rejected_with_pointer():
    checks, decision, dup = run(P(name="memoization ", parents=["DP"]), FakeView())
    assert decision is Decision.REJECT and dup == concept_uuid("MEMO")   # Learner State's id


def test_same_name_other_field_only_warns():
    # Stack (abstract data type) vs Stack (mechanical): node identity decides, not the name
    checks, decision, dup = run(P(name="Stack (computing)", parents=["DS"]), FakeView())
    assert decision is None and dup is None
    assert results(checks)["duplicate_concept"] is Result.WARN


def test_duplicate_of_pending_proposal_rejected():
    old_uuid = new_concept_uuid()
    view = FakeView([{"id": "P-old", "concept_id": old_uuid, "name": "Tail recursion",
                      "status": "proposed", "parent_id": "REC"}])
    _, decision, dup = run(P(), view)
    assert decision is Decision.REJECT and dup == old_uuid


def test_rejected_before_same_parent_rejected_other_parent_warns():
    old = {"id": "P-old", "name": "Tail recursion", "status": "rejected", "parent_id": "ALG"}
    assert run(P(parents=["ALG"]), FakeView([old]))[1] is Decision.REJECT
    checks, decision, _ = run(P(parents=["REC"]), FakeView([old]))
    assert decision is None and results(checks)["duplicate_proposal"] is Result.WARN


def test_name_normalisation():
    assert normalize_name("  Tail-Recursion ") == "tail recursion"
    assert base_name("Stack (abstract data type)") == "stack"
    assert normalize_name("רקורסיית  זנב") == "רקורסיית זנב"


# ---- public ids (Learner State keys its rows by a UUID concept_id) -----------
def test_concept_ids_are_stable_uuids():
    import uuid
    a = concept_uuid("C41008148")
    assert a == concept_uuid("C41008148")              # same on every rebuild
    assert a != concept_uuid("C41008149")
    assert uuid.UUID(a).version == 5
    assert uuid.UUID(new_concept_uuid()).version == 4  # a proposal keeps its own for life
