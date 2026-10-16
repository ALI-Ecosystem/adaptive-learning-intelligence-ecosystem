"""Layer 3 (Wikidata) with a scripted Wikidata and a tiny graph. No network, no Neo4j.
Run: .venv/bin/python -m pytest tests/test_validation_wikidata.py -q

Wikidata (made up):  Q_TAIL -P279-> Q_REC -P279-> Q_ALG -P2579-> Q_CS
                     Q_CELL -P279-> Q_BIO
                     "Public information" is an alias of Q_PR
Our graph:           REC (Q_REC) and ALG (Q_ALG) under CS; BIO (Q_BIO) under LIFE;
                     PR (Q_PR) under SOC; MATH has no Wikidata path to anything
"""
from validation import wikidata
from validation.contract import Proposal, Result

SEARCH = {
    "Tail recursion": [{"id": "Q_TAIL", "label": "tail recursion", "match_type": "label",
                        "match_text": "tail recursion", "description": ""}],
    "Public information": [{"id": "Q_PR", "label": "public relations", "match_type": "alias",
                            "match_text": "public information", "description": ""}],
    "Coproduct": [{"id": "Q_COLLAB", "label": "collaboration", "match_type": "alias",
                   "match_text": "coproduction", "description": ""}],
    "Indeterminate": [{"id": "Q_TAIL", "label": "x", "match_type": "label",
                       "match_text": "indeterminate", "description": ""}],
    "Stack": [{"id": "Q_PR", "label": "stack", "match_type": "label", "match_text": "stack",
               "description": ""},
              {"id": "Q_OTHER", "label": "stack", "match_type": "label", "match_text": "stack",
               "description": ""}],
    "Cell wall": [{"id": "Q_CELL", "label": "cell wall", "match_type": "label",
                   "match_text": "cell wall", "description": ""}],
}
CLAIMS = {"Q_TAIL": {"P279": ["Q_REC"]}, "Q_REC": {"P279": ["Q_ALG"]},
          "Q_ALG": {"P2579": ["Q_CS"]}, "Q_CELL": {"P279": ["Q_BIO"]}}
GRAPH = {"REC": ("Q_REC", "CS"), "ALG": ("Q_ALG", "CS"), "CS": ("Q_CS", "CS"),
         "BIO": ("Q_BIO", "LIFE"), "PR": ("Q_PR", "SOC"), "MATH": (None, "MATH"),
         "DS": (None, "CS")}


class FakeClient:
    def search(self, text, lang="en"):
        return SEARCH.get(text, [])

    def claims(self, qids):
        return {q: CLAIMS.get(q, {}) for q in qids}


class FakeView:
    def wikidata_of(self, cid):
        return GRAPH[cid][0]

    def concepts_by_qids(self, qids):
        return [{"id": c, "concept_id": "uuid-" + c, "name": c, "wikidata": q}
                for c, (q, _) in GRAPH.items() if q in qids]

    def field_of(self, cid):
        return GRAPH[cid][1]


def run(name, parent):
    return wikidata.run(Proposal(id="P-new", name=name, parent_ids=[parent]), FakeView(), FakeClient())


def results(checks):
    return {c.check: c.result for c in checks}


def test_right_parent_supported():
    checks, dup, s = run("Tail recursion", "REC")
    assert dup is None and s["support"] == 1
    assert results(checks)["wikidata_parent"] is Result.PASS


def test_grandparent_supported_with_distance():
    _, _, s = run("Tail recursion", "ALG")
    assert s["support"] == 2


def test_wrong_field_contradicted():
    checks, _, s = run("Cell wall", "MATH")
    # recorded but informational: calibration showed it fires on right placements as often
    assert results(checks)["wikidata_domain"] is Result.INFO and s["contradict"] == ["LIFE"]


def test_studied_by_counts_as_a_path():
    _, _, s = run("Tail recursion", "CS")           # reached through P2579 'studied by'
    assert s["support"] == 3


def test_same_field_other_parent_is_no_evidence():
    checks, dup, s = run("Tail recursion", "DS")    # same field, not on the Wikidata path
    assert s["support"] is None and s["contradict"] is None and dup is None
    assert results(checks)["wikidata_parent"] is Result.SKIP


def test_not_in_wikidata_is_no_evidence_not_rejection():
    checks, dup, s = run("Quantum gardening", "REC")
    assert dup is None and results(checks)["wikidata_found"] is Result.SKIP
    assert not any(c.result is Result.FAIL for c in checks)


def test_alias_of_existing_concept_is_duplicate():
    checks, dup, _ = run("Public information", "REC")
    assert dup == "uuid-PR" and results(checks)["wikidata_duplicate"] is Result.FAIL


def test_prefix_match_is_not_a_resolution():
    checks, dup, s = run("Coproduct", "REC")        # 'coproduction' is not 'coproduct'
    assert s["resolved"] is None and dup is None


def test_qualifier_is_dropped_when_searching():
    _, _, s = run("Indeterminate (variable)", "REC")
    assert s["resolved"] == "Q_TAIL"


def test_homonym_only_warns():
    checks, dup, _ = run("Stack", "REC")             # two items are exactly 'stack'
    assert dup is None and results(checks)["wikidata_duplicate"] is Result.WARN


def test_shared_wikidata_id_only_warns():
    GRAPH["PR2"] = ("Q_PR", "SOC")                  # OpenAlex maps one item to two concepts
    try:
        checks, dup, _ = run("Public information", "REC")
        assert dup is None and results(checks)["wikidata_duplicate"] is Result.WARN
    finally:
        del GRAPH["PR2"]
