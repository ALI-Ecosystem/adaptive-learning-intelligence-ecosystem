"""The GraphView of layer 1 on the real Neo4j graph, and loading a stored proposal.

Trust: the SCRUM-88 concepts have no `trust` property and count as trusted. A concept
promoted by the gate gets trust='provisional' until the audit or a teacher confirms it.
"""
import numpy as np

from placement.graph import Graph

from .contract import Proposal, base_name


class Neo4jView:
    def __init__(self, graph: Graph):
        self.g = graph

    def get_concept(self, cid):
        rows = self.g._read(
            """MATCH (c:Concept {id: $cid})
               RETURN c.id AS id, c.concept_id AS concept_id, c.name AS name, c.level AS level,
                      coalesce(c.trust, 'trusted') AS trust,
                      coalesce(c.disambiguation_suspect, false) AS disambiguation_suspect""",
            cid=cid)
        return rows[0] if rows else None

    def ancestors(self, cid):
        rows = self.g._read(
            """MATCH (:Concept {id: $cid})-[:CHILD_OF*1..10]->(a:Concept)
               RETURN collect(DISTINCT a.id) AS ids""", cid=cid)
        return set(rows[0]["ids"]) if rows else set()

    def prereq_reachable(self, src, dst):
        rows = self.g._read(
            """MATCH (a:Concept {id: $src}), (b:Concept {id: $dst})
               RETURN EXISTS { (a)-[:PREREQUISITE_OF*1..15]->(b) } AS hit""",
            src=src, dst=dst)
        return bool(rows and rows[0]["hit"])

    def concepts_named_like(self, name):
        ids = {c["id"] for c in self.g.find_by_name(name)}
        ids |= {h["id"] for h in self.g.text_search(base_name(name), 25)}
        return self.g._read(
            """MATCH (c:Concept) WHERE c.id IN $ids
               RETURN c.id AS id, c.concept_id AS concept_id, c.name AS name""", ids=list(ids))

    def proposals_named_like(self, name, exclude_id):
        # proposals are few; filter by name in Python with the same normalisation
        return self.g._read(
            """MATCH (p:ProposedConcept) WHERE p.id <> $exclude
               OPTIONAL MATCH (p)-[:PROPOSED_CHILD_OF]->(par:Concept)
               RETURN p.id AS id, p.concept_id AS concept_id, p.name AS name,
                      p.status AS status, par.id AS parent_id""",
            exclude=exclude_id)


def load_proposal(graph: Graph, pid: str) -> Proposal | None:
    rows = graph._read(
        """MATCH (p:ProposedConcept {id: $pid})
           OPTIONAL MATCH (p)-[pc:PROPOSED_CHILD_OF]->(par:Concept)
           OPTIONAL MATCH (p)-[:PROPOSED_PREREQUISITE_OF]->(en:Concept)
           OPTIONAL MATCH (rq:Concept)-[:PROPOSED_PREREQUISITE_OF]->(p)
           RETURN p.id AS id, p.concept_id AS concept_id, p.name AS name,
                  p.name_original AS name_original,
                  p.description AS description,
                  collect(DISTINCT par.id) AS parents, max(pc.confidence) AS confidence,
                  collect(DISTINCT en.id) AS enables, collect(DISTINCT rq.id) AS requires""",
        pid=pid)
    if not rows:
        return None
    r = rows[0]
    return Proposal(id=r["id"], name=r["name"], concept_id=r["concept_id"] or "",
                    name_original=r["name_original"] or "",
                    description=r["description"] or "", parent_ids=r["parents"],
                    confidence=r["confidence"], requires=r["requires"], enables=r["enables"])


class Neo4jSemanticView:
    """Layer 2's view of the graph. Cosine similarities are computed here from the stored
    embeddings (unit vectors), the same way SCRUM-88 computed CHILD_OF.similarity, so the
    numbers are comparable with the real links."""

    def __init__(self, graph: Graph):
        self.g = graph
        self._levels: dict[int, list[float]] = {}

    def embed_text(self, text):
        from placement.embedder import embed
        return embed([text])[0]

    def neighbours(self, vec, k):
        from placement import config
        rows = self.g._read(
            f"""CALL db.index.vector.queryNodes('{config.VECTOR_INDEX}', $kk, $vec)
                YIELD node WHERE NOT node.id IN $hidden
                RETURN node.id AS id, node.name AS name, node.embedding AS e LIMIT $k""",
            vec=[float(x) for x in vec], k=k, kk=k + len(self.g.hidden))
        out = [{"id": r["id"], "name": r["name"], "sim": float(np.asarray(r["e"]) @ vec)}
               for r in rows]
        return sorted(out, key=lambda h: -h["sim"])

    def embeddings(self, ids):
        rows = self.g._read(
            """MATCH (c:Concept) WHERE c.id IN $ids AND NOT c.id IN $hidden
               RETURN c.id AS id, c.embedding AS e""", ids=list(set(ids)))
        return {r["id"]: np.asarray(r["e"], dtype=np.float32) for r in rows if r["e"]}

    def parents(self, cid):
        return self.g.parents_of(cid)

    def children(self, cid):
        return [k["id"] for k in self.g.children(cid, 300)]

    def level_of(self, cid):
        c = self.g.concept(cid)
        return c["level"] if c else 0

    def link_sims(self, child_level):
        if child_level not in self._levels:
            rows = self.g._read(
                """MATCH (c:Concept {level: $lv})-[e:CHILD_OF]->(:Concept)
                   RETURN collect(e.similarity) AS s""", lv=child_level)
            self._levels[child_level] = sorted(rows[0]["s"]) if rows else []
        return self._levels[child_level]


class Neo4jExternalView:
    """Layer 3's view: Wikidata ids of our concepts and the top-level field above them."""

    def __init__(self, graph: Graph):
        self.g = graph
        self._fields: dict[str, str | None] = {}

    def wikidata_of(self, cid):
        rows = self.g._read("MATCH (c:Concept {id: $cid}) RETURN c.wikidata AS q", cid=cid)
        return rows[0]["q"] if rows and rows[0]["q"] else None

    def concepts_by_qids(self, qids):
        if not qids:
            return []
        return self.g._read(
            """MATCH (c:Concept) WHERE c.wikidata IN $q AND NOT c.id IN $hidden
               RETURN c.id AS id, c.concept_id AS concept_id, c.name AS name,
                      c.wikidata AS wikidata""", q=list(qids))

    def field_of(self, cid):
        if cid not in self._fields:
            path = self.g.path_to_root(cid)
            self._fields[cid] = path[-1]["id"] if path and path[-1]["level"] == 0 else None
        return self._fields[cid]


def ensure_indexes(graph: Graph):
    graph.driver.execute_query(
        "CREATE INDEX concept_wikidata IF NOT EXISTS FOR (c:Concept) ON (c.wikidata)")
    graph.driver.execute_query("CALL db.awaitIndexes(300)")
