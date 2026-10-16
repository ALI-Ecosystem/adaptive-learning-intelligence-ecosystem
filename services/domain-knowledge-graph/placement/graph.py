"""Read-only views of the Domain Knowledge Graph used by the placement methods,
plus the single write path for a proposed concept.

`hidden` is a set of concept ids that every read pretends do not exist. The
hide-and-replace evaluation uses it so a test concept, its embedding and its
edges are invisible while the system tries to place it again.
"""
import re
import uuid
from datetime import datetime, timezone

from neo4j import GraphDatabase

from . import config
from .embedder import concept_text, embed
from .ids import new_concept_uuid

_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def connect():
    return GraphDatabase.driver(config.NEO4J_URI,
                                auth=(config.NEO4J_USER, config.require_neo4j_password()),
                                notifications_min_severity="OFF")


def _short(text: str | None, n: int = 160) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


class Graph:
    def __init__(self, driver, hidden: frozenset[str] = frozenset()):
        self.driver = driver
        self.hidden = list(hidden)

    def with_hidden(self, hidden) -> "Graph":
        return Graph(self.driver, frozenset(hidden))

    def _read(self, query: str, **params):
        records, _, _ = self.driver.execute_query(query, hidden=self.hidden, **params,
                                                  routing_="r")
        return [r.data() for r in records]

    # ---- search ---------------------------------------------------------
    def vector_search(self, text: str, k: int = 10):
        vec = embed([text])[0].tolist()
        return self._read(
            f"""CALL db.index.vector.queryNodes('{config.VECTOR_INDEX}', $kk, $vec)
                YIELD node, score WHERE NOT node.id IN $hidden
                RETURN node.id AS id, node.name AS name, node.level AS level,
                       node.description AS description, score
                LIMIT $k""",
            vec=vec, k=k, kk=k + len(self.hidden))

    def text_search(self, text: str, k: int = 10):
        q = _LUCENE_SPECIAL.sub(r"\\\1", text).strip()
        if not q:
            return []
        return self._read(
            f"""CALL db.index.fulltext.queryNodes('{config.FULLTEXT_INDEX}', $q, {{limit: $kk}})
                YIELD node, score WHERE NOT node.id IN $hidden
                RETURN node.id AS id, node.name AS name, node.level AS level,
                       node.description AS description, score
                LIMIT $k""",
            q=q, k=k, kk=k + len(self.hidden))

    def search(self, text: str, k: int = 10):
        """Hybrid search: semantic (vector) and lexical (full-text) hits, merged."""
        merged = {}
        for source, hits in (("semantic", self.vector_search(text, k)),
                             ("lexical", self.text_search(text, k))):
            for rank, h in enumerate(hits):
                m = merged.setdefault(h["id"], {"id": h["id"], "name": h["name"],
                                                "level": h["level"],
                                                "description": _short(h["description"]),
                                                "found_by": [], "rrf": 0.0})
                m["found_by"].append(source)
                m["rrf"] += 1.0 / (60 + rank)
        out = sorted(merged.values(), key=lambda m: -m["rrf"])[:k]
        for m in out:
            m.pop("rrf")
        return out

    def pending_proposals(self, name: str):
        """Proposed concepts (not yet validated) with the same name, to avoid duplicates."""
        return self._read(
            """MATCH (p:ProposedConcept) WHERE toLower(p.name) = toLower($name)
               OPTIONAL MATCH (p)-[:PROPOSED_CHILD_OF]->(par:Concept)
               RETURN p.id AS id, p.name AS name, par.id AS parent_id, par.name AS parent_name""",
            name=name)

    # ---- navigation -----------------------------------------------------
    def concept(self, cid: str):
        rows = self._read(
            """MATCH (c:Concept {id: $cid}) WHERE NOT c.id IN $hidden
               OPTIONAL MATCH (c)-[e:CHILD_OF]->(p:Concept) WHERE NOT p.id IN $hidden
               WITH c, p, e ORDER BY e.primary DESC, e.similarity DESC
               WITH c, collect(CASE WHEN p IS NULL THEN NULL ELSE
                    {id: p.id, name: p.name, level: p.level, primary: e.primary} END) AS parents
               OPTIONAL MATCH (k:Concept)-[:CHILD_OF]->(c) WHERE NOT k.id IN $hidden
               RETURN c.id AS id, c.name AS name, c.level AS level,
                      c.description AS description, parents, count(k) AS child_count""",
            cid=cid)
        return rows[0] if rows else None

    def children(self, cid: str, limit: int = 40):
        return self._read(
            """MATCH (k:Concept)-[:CHILD_OF]->(c:Concept {id: $cid})
               WHERE NOT k.id IN $hidden AND NOT c.id IN $hidden
               OPTIONAL MATCH (g:Concept)-[:CHILD_OF]->(k) WHERE NOT g.id IN $hidden
               WITH k, count(g) AS child_count
               RETURN k.id AS id, k.name AS name, k.level AS level, child_count
               ORDER BY k.works_count DESC LIMIT $limit""",
            cid=cid, limit=limit)

    def path_to_root(self, cid: str):
        """Follow primary parents to a top-level field."""
        path, seen, cur = [], set(), cid
        while cur and cur not in seen and len(path) < 8:
            seen.add(cur)
            c = self.concept(cur)
            if not c:
                break
            path.append({"id": c["id"], "name": c["name"], "level": c["level"]})
            cur = c["parents"][0]["id"] if c["parents"] else None
        return path

    def parents_of(self, cid: str):
        c = self.concept(cid)
        return c["parents"] if c else []

    def concept_exists(self, cid: str) -> bool:
        return bool(self._read("MATCH (c:Concept {id: $cid}) WHERE NOT c.id IN $hidden "
                               "RETURN c.id AS id", cid=cid))

    def find_by_name(self, name: str):
        return self._read(
            """MATCH (c:Concept) WHERE toLower(c.name) = toLower($name) AND NOT c.id IN $hidden
               RETURN c.id AS id, c.name AS name ORDER BY c.works_count DESC""", name=name)

    # ---- evaluation set -------------------------------------------------
    def eligible_test_concepts(self):
        """Concepts whose correct parent is a plain fact of the source: exactly one parent,
        an unflagged link, no children, not a disambiguation page."""
        return self._read(
            """MATCH (c:Concept)-[e:CHILD_OF]->(p:Concept)
               WHERE NOT ()-[:CHILD_OF]->(c) AND NOT c.disambiguation_suspect
               WITH c, collect(e) AS es, collect(p) AS ps
               WHERE size(es) = 1 AND size(es[0].flags) = 0
               RETURN c.id AS id, c.name AS name, c.description AS description,
                      c.level AS level, ps[0].id AS parent_id, ps[0].name AS parent_name
               ORDER BY c.id""")

    # ---- the only write -------------------------------------------------
    def write_proposal(self, *, name: str, name_original: str, description: str,
                       parent_id: str, confidence: float, reasoning: str,
                       method: str, model: str, trace_id: str,
                       requires: list[str] = (), enables: list[str] = (),
                       prerequisite_reasoning: str = "") -> str:
        """Add a concept as PROPOSED, never as a validated :Concept. It is not returned by
        the search indexes until the validation gate (SCRUM-90) promotes it."""
        if not self.concept_exists(parent_id):
            raise ValueError(f"parent {parent_id} does not exist")
        pid = "P-" + uuid.uuid4().hex[:12]
        self.driver.execute_query(
            """MATCH (par:Concept {id: $parent_id})
               CREATE (p:ProposedConcept {id: $pid, concept_id: $concept_id,
                       name: $name, name_original: $name_original,
                       description: $description, status: 'proposed', created_at: $now,
                       method: $method, model: $model, trace_id: $trace_id})
               CREATE (p)-[:PROPOSED_CHILD_OF {confidence: $confidence, reasoning: $reasoning,
                       created_at: $now, method: $method, trace_id: $trace_id}]->(par)""",
            pid=pid, concept_id=new_concept_uuid(), name=name[:200], name_original=name_original[:200],
            description=description[:1000], parent_id=parent_id,
            confidence=float(confidence), reasoning=reasoning[:2000], method=method,
            model=model, trace_id=trace_id, now=datetime.now(timezone.utc).isoformat())
        # SCRUM-90: prerequisite links, also only PROPOSED until the gate decides each one.
        # (r)-[:PROPOSED_PREREQUISITE_OF]->(p): r must be learned before the new concept p.
        for direction, ids in (("requires", requires), ("enables", enables)):
            for cid in ids:
                self.driver.execute_query(
                    ("MATCH (p:ProposedConcept {id: $pid}), (c:Concept {id: $cid}) "
                     + ("CREATE (c)-[:PROPOSED_PREREQUISITE_OF {reasoning: $why, created_at: $now, "
                        "trace_id: $trace_id}]->(p)" if direction == "requires" else
                        "CREATE (p)-[:PROPOSED_PREREQUISITE_OF {reasoning: $why, created_at: $now, "
                        "trace_id: $trace_id}]->(c)")),
                    pid=pid, cid=cid, why=prerequisite_reasoning[:1000], trace_id=trace_id,
                    now=datetime.now(timezone.utc).isoformat())
        return pid


def concept_query_text(name: str, description: str | None) -> str:
    return concept_text(name, description)
