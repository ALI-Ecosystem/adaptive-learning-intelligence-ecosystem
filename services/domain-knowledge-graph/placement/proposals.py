"""List the proposed concepts waiting for the validation gate (SCRUM-90).

Usage: python -m placement.proposals
"""
from .graph import Graph, connect


def main():
    graph = Graph(connect())
    rows = graph._read(
        """MATCH (p:ProposedConcept)-[e:PROPOSED_CHILD_OF]->(par:Concept)
           RETURN p.id AS id, p.name AS name, p.name_original AS original, p.status AS status,
                  p.created_at AS created, par.id AS parent_id, par.name AS parent,
                  e.confidence AS confidence, e.reasoning AS reasoning
           ORDER BY p.created_at""")
    if not rows:
        print("no proposed concepts yet")
    for r in rows:
        path = " > ".join(c["name"] for c in reversed(graph.path_to_root(r["parent_id"])))
        print(f"{r['id']}  {r['name']}  ({r['original'] or '-'})  status={r['status']}  "
              f"confidence={r['confidence']}  created={r['created']}")
        print(f"   under: {path} > {r['name']}")
        print(f"   why:   {r['reasoning']}\n")
    graph.driver.close()


if __name__ == "__main__":
    main()
