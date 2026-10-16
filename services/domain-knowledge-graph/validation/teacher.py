"""The teacher's side of the gate: the review queue and the periodic audit.

Usage:
  python -m validation.teacher queue                         proposals waiting for a teacher
  python -m validation.teacher accept P-x --parent C123 [--links all|C1,C2]
  python -m validation.teacher reject P-x
  python -m validation.teacher audit [--n 5]                 a sample of provisional concepts
  python -m validation.teacher confirm P-x                   audit: it is right -> trusted
  python -m validation.teacher flag P-x                      audit: it is wrong -> flagged

The queue is ordered by the agent's confidence, lowest first (the least certain cases are
the most useful for a person). The audit sample takes concepts whose proposed links mostly
failed first (audit_priority), then the rest at random.
"""
import argparse
import getpass
import json
import random

from placement.graph import Graph, connect

from . import store
from .neo4j_view import load_proposal


def _path(graph, cid):
    return " > ".join(x["name"] for x in reversed(graph.path_to_root(cid)))


def queue(graph: Graph):
    rows = graph._read("""MATCH (p:ProposedConcept {status: 'needs_review'})
                          OPTIONAL MATCH (p)-[pc:PROPOSED_CHILD_OF]->(par:Concept)
                          RETURN p.id AS id, p.name AS name, p.name_original AS original,
                                 p.description AS description, p.review AS review,
                                 pc.confidence AS confidence
                          ORDER BY coalesce(pc.confidence, 0.5), p.created_at""")
    if not rows:
        print("the queue is empty")
    for r in rows:
        review = json.loads(r["review"]) if r["review"] else {}
        print(f"{r['id']}  {r['name']}  ({r['original'] or '-'})  agent confidence={r['confidence']}")
        print(f"   {r['description']}")
        print(f"   question: {review.get('question')}   (rule {review.get('rule')})")
        for o in review.get("options", []):
            print(f"     option {o['id']}: {o['path']} > {r['name']}")
        links = graph._read(
            """MATCH (a)-[l:PROPOSED_PREREQUISITE_OF]->(b) WHERE a.id = $pid OR b.id = $pid
               RETURN a.name AS a, b.name AS b, a.id AS aid, b.id AS bid, l.status AS st""",
            pid=r["id"])
        for l in links:
            other = l["aid"] if l["bid"] == r["id"] else l["bid"]
            print(f"     link {l['a']} -> {l['b']}  [{l['st']}]  id for --links: {other}")
        print()


def audit(graph: Graph, n: int):
    rows = graph._read("""MATCH (c:Concept {trust: 'provisional'})-[:CHILD_OF]->(par:Concept)
                          RETURN c.id AS id, c.name AS name, c.description AS description,
                                 par.id AS parent, coalesce(c.audit_priority, false) AS prio""")
    first = [r for r in rows if r["prio"]]
    rest = [r for r in rows if not r["prio"]]
    random.shuffle(rest)
    for r in (first + rest)[:n]:
        print(f"{r['id']}  {r['name']}{'  [priority: most links failed]' if r['prio'] else ''}")
        print(f"   {r['description']}")
        print(f"   under: {_path(graph, r['parent'])} > {r['name']}\n")
    if not rows:
        print("no provisional concepts to audit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("queue", "accept", "reject", "audit", "confirm", "flag"))
    ap.add_argument("id", nargs="?")
    ap.add_argument("--parent")
    ap.add_argument("--links", default="")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--teacher", default=getpass.getuser())
    a = ap.parse_args()
    graph = Graph(connect())
    if a.action == "queue":
        queue(graph)
    elif a.action == "audit":
        audit(graph, a.n)
    elif a.action in ("confirm", "flag"):
        print(store.audit_set(graph, a.id, "trusted" if a.action == "confirm" else "flagged", a.teacher))
    elif a.action == "reject":
        print(store.teacher_reject(graph, a.id, a.teacher))
    else:
        p = load_proposal(graph, a.id)
        if p is None or not a.parent:
            raise SystemExit("accept needs a proposal id and --parent")
        links = (p.requires + p.enables) if a.links == "all" else [x for x in a.links.split(",") if x]
        print(store.teacher_accept(graph, p, a.parent, a.teacher, links))
    graph.driver.close()


if __name__ == "__main__":
    main()
