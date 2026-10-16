"""Give the graph that is already loaded in Neo4j its public UUID concept ids, without
reloading it. Safe to run again: only nodes without a concept_id are touched, and the
UUID of a source concept is always the same (placement/ids.py).

Usage: python -m placement.assign_concept_ids
"""
from .graph import connect
from .ids import concept_uuid, new_concept_uuid

BATCH = 5000


def main():
    d = connect()
    for q in ("CREATE CONSTRAINT concept_uuid IF NOT EXISTS FOR (c:Concept) "
              "REQUIRE c.concept_id IS UNIQUE",
              "CREATE CONSTRAINT proposed_uuid IF NOT EXISTS FOR (p:ProposedConcept) "
              "REQUIRE p.concept_id IS UNIQUE"):
        d.execute_query(q)

    recs, _, _ = d.execute_query("MATCH (c:Concept) WHERE c.concept_id IS NULL RETURN c.id AS id")
    rows = [{"id": r["id"], "u": concept_uuid(r["id"])} for r in recs]
    for i in range(0, len(rows), BATCH):
        d.execute_query("UNWIND $rows AS r MATCH (c:Concept {id: r.id}) SET c.concept_id = r.u",
                        rows=rows[i:i + BATCH])

    props, _, _ = d.execute_query(
        "MATCH (p:ProposedConcept) WHERE p.concept_id IS NULL RETURN p.id AS id")
    for r in props:
        d.execute_query("MATCH (p:ProposedConcept {id: $id}) SET p.concept_id = $u",
                        id=r["id"], u=new_concept_uuid())

    recs, _, _ = d.execute_query(
        """CALL { MATCH (c:Concept) RETURN count(c) AS concepts,
                  count(c.concept_id) AS concepts_with_uuid }
           CALL { MATCH (p:ProposedConcept) RETURN count(p) AS proposals,
                  count(p.concept_id) AS proposals_with_uuid }
           RETURN concepts, concepts_with_uuid, proposals, proposals_with_uuid""")
    print(f"assigned now: {len(rows)} concepts, {len(props)} proposals")
    print(f"graph state:  {dict(recs[0])}")
    d.close()


if __name__ == "__main__":
    main()
