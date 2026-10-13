"""Smoke tests against a running Neo4j with the SCRUM-88 graph and the vector index.
Run: .venv/bin/python -m pytest tests -q   (skipped when Neo4j is not reachable)"""
import pytest

from placement import config
from placement.agent import run_agent
from placement.evaluate import conversation_for, evaluate_one
from placement.graph import Graph, connect
from tests.fake_claude import FakeClient


@pytest.fixture(scope="module")
def graph():
    if not config.NEO4J_PASSWORD:
        pytest.skip("NEO4J_PASSWORD not set")
    try:
        d = connect(); d.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j not reachable: {e}")
    yield Graph(d)
    d.close()


def test_hidden_concept_is_invisible(graph):
    item = graph.eligible_test_concepts()[0]
    g = graph.with_hidden({item["id"]})
    assert g.concept(item["id"]) is None
    assert item["id"] not in {h["id"] for h in g.search(item["name"], 25)}
    assert item["id"] not in {k["id"] for k in g.children(item["parent_id"], 500)}


def test_agent_loop_with_fake_client(graph):
    res = run_agent(conversation_for("Tail recursion", "recursion whose last action is a call"),
                    graph, FakeClient())
    assert res.error is None and res.decision["decision"] == "new"
    assert graph.concept_exists(res.decision["parent_id"])
    assert [e["event"] for e in res.trace][:2] == ["input", "thinking"]


def test_evaluate_one_all_methods(graph, tmp_path):
    item = graph.eligible_test_concepts()[0]
    row = evaluate_one(graph, item, ["baseline", "agent", "llm_only"], FakeClient(),
                       "fake", tmp_path)
    for m in ("baseline", "agent", "llm_only"):
        assert row[m]["outcome"] in {"exact", "too_general", "too_specific", "wrong", "none"}


def test_proposal_is_not_a_concept(graph):
    parent = graph.eligible_test_concepts()[0]["parent_id"]
    pid = graph.write_proposal(name="ZZ smoke test concept", name_original="", description="t",
                               parent_id=parent, confidence=0.1, reasoning="test",
                               method="test", model="fake", trace_id="test")
    try:
        assert graph.pending_proposals("zz smoke test concept")[0]["id"] == pid
        assert pid not in {h["id"] for h in graph.search("ZZ smoke test concept", 25)}
        with pytest.raises(ValueError):
            graph.write_proposal(name="x", name_original="", description="", parent_id="C0",
                                 confidence=0, reasoning="", method="t", model="t", trace_id="t")
    finally:
        graph.driver.execute_query("MATCH (p:ProposedConcept {id: $id}) DETACH DELETE p", id=pid)
