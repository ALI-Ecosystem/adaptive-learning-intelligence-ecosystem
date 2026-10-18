"""Storage of a Course Material Graph: an overlay on the global graph, not a copy.

    (:MaterialGraph {material_graph_id, title, source, content_hash, version, status, ...})
        -[:HAS_UNIT]->        (:MaterialUnit {key, seq, title, source_ref, words})
                                 -[:COVERS {role, importance, evidence, name_in_material}]-> (:Concept)
        -[:INCLUDES {role, scoped_parent, ...}]->  (:Concept)            reused, never copied
        -[:INCLUDES_PENDING {role}]->              (:ProposedConcept)    waiting for the teacher

What is reused from the global graph: the Concept nodes themselves (names, definitions,
ids, embeddings) and their CHILD_OF / PREREQUISITE_OF / RELATED_TO edges. The material
graph's tree is "INCLUDES.scoped_parent": the id of one of the concept's existing parents,
so every tree edge is an edge that exists in the global graph.

What is stored only for the material: which units cover which concept and in what role
(taught / prerequisite), the evidence quote, the unit order, the material-level role
(taught / prerequisite / context) and which existing parent the course uses.

Nothing here writes to a Concept, a CHILD_OF edge or any other global edge.
"""
import json
import uuid
from datetime import datetime, timezone

from .link import MaterialConcept
from .scope import ScopedGraph


def _now():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(graph):
    for q in ("CREATE CONSTRAINT material_graph_uuid IF NOT EXISTS FOR (m:MaterialGraph) "
              "REQUIRE m.material_graph_id IS UNIQUE",
              "CREATE INDEX material_graph_hash IF NOT EXISTS FOR (m:MaterialGraph) ON (m.content_hash)"):
        graph.driver.execute_query(q)


def find_existing(graph, content_hash: str, config_key: str):
    rows = graph._read(
        """MATCH (m:MaterialGraph {content_hash: $h, config_key: $k, status: 'active'})
           RETURN m.material_graph_id AS id, m.version AS version""", h=content_hash, k=config_key)
    return rows[0] if rows else None


def save(graph, material, concepts: list[MaterialConcept], sg: ScopedGraph, *,
         config_key: str, run_info: dict) -> dict:
    ensure_schema(graph)
    mid = str(uuid.uuid4())
    h = material.content_hash()
    prev = graph._read("""MATCH (m:MaterialGraph {content_hash: $h}) RETURN max(m.version) AS v""", h=h)
    version = (prev[0]["v"] or 0) + 1 if prev else 1
    by_cid = {mc.concept_id: mc for mc in concepts if mc.concept_id}
    with graph.driver.session() as s:
        def tx_fn(tx):
            tx.run("""MATCH (m:MaterialGraph {content_hash: $h, status: 'active'})
                      SET m.status = 'superseded', m.superseded_at = $now""", h=h, now=_now())
            tx.run("""CREATE (m:MaterialGraph {material_graph_id: $mid, title: $title, source: $src,
                              language: $lang, license: $lic, content_hash: $h, config_key: $ck,
                              version: $ver, status: 'active', created_at: $now,
                              stats: $stats, run: $run})""",
                   mid=mid, title=material.title[:300], src=material.source[:500],
                   lang=material.language, lic=material.license, h=h, ck=config_key,
                   ver=version, now=_now(), stats=json.dumps(sg.stats),
                   run=json.dumps(run_info, ensure_ascii=False, default=str))
            tx.run("""MATCH (m:MaterialGraph {material_graph_id: $mid})
                      UNWIND $units AS u
                      CREATE (m)-[:HAS_UNIT]->(:MaterialUnit {material_graph_id: $mid, key: u.key,
                              seq: u.seq, title: u.title, source_ref: u.ref, words: u.words})""",
                   mid=mid, units=[{"key": u.key[:300], "seq": u.seq, "title": u.title[:300],
                                    "ref": u.source_ref[:500], "words": u.words}
                                   for u in material.units])
            rows = []
            for cid, n in sg.nodes.items():
                mc = by_cid.get(cid)
                rows.append({"cid": cid, "role": n["role"], "parent": n.get("scoped_parent"),
                             "primary": n.get("scoped_parent_primary"),
                             "importance": n.get("importance"),
                             "first": n.get("first_taught_seq"),
                             "conf": mc.link_confidence if mc else None,
                             "method": mc.link_method if mc else "scope"})
            tx.run("""MATCH (m:MaterialGraph {material_graph_id: $mid})
                      UNWIND $rows AS r MATCH (c:Concept {id: r.cid})
                      CREATE (m)-[:INCLUDES {role: r.role, scoped_parent: r.parent,
                              scoped_parent_primary: r.primary, importance: r.importance,
                              first_taught_seq: r.first, link_confidence: r.conf,
                              link_method: r.method}]->(c)""", mid=mid, rows=rows)
            cov = []
            for mc in concepts:
                target = mc.concept_id if mc.concept_id in sg.nodes else None
                pend = mc.proposal_id if (not target and mc.proposal_id) else None
                if not target and not pend:
                    continue
                for o in mc.occurrences:
                    cov.append({"seq": o["unit_seq"], "cid": target, "pid": pend, "role": o["role"],
                                "imp": o["importance"], "ev": (o.get("evidence") or "")[:300],
                                "name": mc.name[:120],
                                "orig": (mc.names_original[0] if mc.names_original else mc.name)[:120]})
            tx.run("""MATCH (m:MaterialGraph {material_graph_id: $mid})-[:HAS_UNIT]->(u:MaterialUnit)
                      UNWIND $cov AS r WITH u, r WHERE u.seq = r.seq
                      OPTIONAL MATCH (c:Concept {id: r.cid})
                      OPTIONAL MATCH (p:ProposedConcept {id: r.pid})
                      WITH u, r, coalesce(c, p) AS t WHERE t IS NOT NULL
                      CREATE (u)-[:COVERS {role: r.role, importance: r.imp, evidence: r.ev,
                              name_in_material: r.orig, name: r.name}]->(t)""", mid=mid, cov=cov)
            tx.run("""MATCH (m:MaterialGraph {material_graph_id: $mid})
                      UNWIND $pend AS r MATCH (p:ProposedConcept {id: r.pid})
                      CREATE (m)-[:INCLUDES_PENDING {role: r.role, proposed_parent: r.parent}]->(p)""",
                   mid=mid, pend=[{"pid": p["proposal_id"], "role": p.get("role", "taught"),
                                   "parent": p.get("parent_id")} for p in sg.pending])
        s.execute_write(tx_fn)
    return {"material_graph_id": mid, "version": version}


def load(graph, mid: str) -> dict | None:
    """The scoped graph as other ALI services see it: public concept ids (UUIDs) only.
    A pending concept the teacher has since accepted is returned as a normal node."""
    head = graph._read("MATCH (m:MaterialGraph {material_graph_id: $mid}) RETURN m {.*} AS m", mid=mid)
    if not head:
        return None
    m = head[0]["m"]
    nodes = graph._read(
        """MATCH (:MaterialGraph {material_graph_id: $mid})-[i:INCLUDES]->(c:Concept)
           OPTIONAL MATCH (par:Concept {id: i.scoped_parent})
           OPTIONAL MATCH (u:MaterialUnit {material_graph_id: $mid})-[cv:COVERS]->(c)
           WITH c, i, par, collect(DISTINCT {seq: u.seq, role: cv.role}) AS units
           RETURN c.id AS id, c.concept_id AS concept_id, c.name AS name, c.level AS level,
                  i.role AS role, par.id AS parent_id, par.concept_id AS parent_concept_id,
                  i.scoped_parent_primary AS parent_is_primary, i.importance AS importance,
                  i.first_taught_seq AS first_taught_seq, c.trust AS trust,
                  [x IN units WHERE x.seq IS NOT NULL] AS units""", mid=mid)
    pending = graph._read(
        """MATCH (:MaterialGraph {material_graph_id: $mid})-[i:INCLUDES_PENDING]->(p:ProposedConcept)
           OPTIONAL MATCH (p)-[:BECAME]->(c:Concept)
           OPTIONAL MATCH (par:Concept {id: i.proposed_parent})
           RETURN p.id AS proposal_id, p.concept_id AS concept_id, p.name AS name, p.status AS status,
                  i.role AS role, c.id AS accepted_as, par.id AS parent_id,
                  par.concept_id AS parent_concept_id""", mid=mid)
    ids = [n["id"] for n in nodes]
    edges = graph._read(
        """MATCH (a:Concept)-[e:CHILD_OF|PREREQUISITE_OF|RELATED_TO]->(b:Concept)
           WHERE a.id IN $ids AND b.id IN $ids
           RETURN a.id AS src, b.id AS dst, a.concept_id AS src_concept_id,
                  b.concept_id AS dst_concept_id, type(e) AS type, e.flags AS flags""", ids=ids)
    units = graph._read(
        """MATCH (:MaterialGraph {material_graph_id: $mid})-[:HAS_UNIT]->(u:MaterialUnit)
           RETURN u.seq AS seq, u.key AS key, u.title AS title ORDER BY u.seq""", mid=mid)
    return {"material_graph": m, "units": units, "nodes": nodes, "pending": pending, "edges": edges}


def list_graphs(graph) -> list[dict]:
    return graph._read(
        """MATCH (m:MaterialGraph) OPTIONAL MATCH (m)-[:INCLUDES]->(c)
           RETURN m.material_graph_id AS id, m.title AS title, m.version AS version,
                  m.status AS status, m.created_at AS created_at, count(c) AS concepts
           ORDER BY m.created_at DESC""")
