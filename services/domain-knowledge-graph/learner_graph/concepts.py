"""The learner graph's view of the Domain Knowledge Graph (DKG): which canonical concept a
request means, and the background resolver for concepts the DKG does not have yet.

Identity is the DKG's public concept_id (UUID, placement/ids.py). A name is never used as
identity: a request that names a concept instead of giving its id waits on a ticket until
the SCRUM-89 placement agent and the SCRUM-90 gate say which concept it is
(decision 2026-10-19, option B). The LLM runs only in resolve_tickets(), never on the
write path, so a slow or failing model call never blocks or loses an update.

    agent: already_exists          -> RESOLVED to that concept
    gate:  ACCEPT_PROVISIONAL      -> RESOLVED to the promoted concept (same concept_id)
    gate:  REJECT, duplicate_of X  -> RESOLVED to X (two names, one concept)
    gate:  NEEDS_REVIEW            -> PROPOSED: waits for the teacher, re-checked each run
    gate / teacher: REJECT         -> REJECTED: records stay in the log, never shown
"""
import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from .contract import name_key


@dataclass
class ConceptInfo:
    state: str                  # concept | proposed | rejected
    concept_id: str | None = None
    proposal_id: str | None = None
    name: str | None = None
    note: str = ""


class ConceptDirectory(Protocol):
    def lookup(self, concept_id: str) -> ConceptInfo | None: ...
    def proposal_status(self, proposal_id: str) -> ConceptInfo: ...
    def propose(self, name: str, context: str) -> ConceptInfo: ...


class Neo4jDirectory:
    """The real DKG in Neo4j. propose() needs a Claude client (it runs the SCRUM-89 agent
    and the SCRUM-90 gate); lookup() and proposal_status() are plain reads."""

    def __init__(self, graph, client=None, wd_client=None, wp_client=None, model=None):
        from placement import config
        self.graph, self.client = graph, client
        self.wd, self.wp = wd_client, wp_client
        self.model = model or config.CLAUDE_MODEL

    def _proposal(self, where: str, **params) -> ConceptInfo | None:
        rows = self.graph._read(
            f"""MATCH (p:ProposedConcept) WHERE {where}
                OPTIONAL MATCH (p)-[:BECAME]->(c:Concept)
                RETURN p.id AS pid, p.name AS name, p.status AS status,
                       p.duplicate_of AS dup, c.concept_id AS became
                ORDER BY p.created_at DESC LIMIT 1""", **params)
        if not rows:
            return None
        r = rows[0]
        if r["became"]:
            return ConceptInfo("concept", r["became"], r["pid"], r["name"])
        if r["status"] == "rejected" and r["dup"]:
            return ConceptInfo("concept", r["dup"], r["pid"], r["name"],
                               note=f"duplicate of {r['dup']}")
        if r["status"] == "rejected":
            return ConceptInfo("rejected", None, r["pid"], r["name"])
        return ConceptInfo("proposed", None, r["pid"], r["name"], note=r["status"])

    def lookup(self, concept_id):
        rows = self.graph._read(
            "MATCH (c:Concept {concept_id: $u}) RETURN c.concept_id AS u, c.name AS name",
            u=concept_id)
        if rows:
            return ConceptInfo("concept", rows[0]["u"], name=rows[0]["name"])
        return self._proposal("p.concept_id = $u", u=concept_id)

    def proposal_status(self, proposal_id):
        info = self._proposal("p.id = $pid", pid=proposal_id) or ConceptInfo(
            "rejected", proposal_id=proposal_id, note="proposal not found")
        if self._never_gated(info) and self.client is not None:
            return self._gate(proposal_id)
        return info

    @staticmethod
    def _never_gated(info) -> bool:
        """A ProposedConcept still in status 'proposed' was written but never validated
        (e.g. by ./scrum89.sh add, before SCRUM-90 existed). Nobody else will ever run the
        gate on it, so waiting for it would wait forever: the resolver runs the gate."""
        return info.state == "proposed" and info.note == "proposed"

    def _gate(self, pid) -> ConceptInfo:
        from validation import gate, store
        from validation.neo4j_view import ensure_indexes, load_proposal
        ensure_indexes(self.graph)
        p = load_proposal(self.graph, pid)
        v = gate.validate(p, self.graph, self.client, self.wd, wp_client=self.wp)
        store.record_run(self.graph, v)
        store.apply(self.graph, p, v)
        info = self._proposal("p.id = $pid", pid=pid)
        info.note = f"gate {v.decision.value}" + (f" rule {v.rule}" if v.rule else "")
        return info

    def _public(self, internal_id):
        rows = self.graph._read("MATCH (c:Concept {id: $i}) RETURN c.concept_id AS u",
                                i=internal_id)
        return rows[0]["u"] if rows else None

    def propose(self, name, context):
        from placement.agent import run_agent
        from placement.traces import save_trace
        from validation.contract import prompt_text
        from validation.neo4j_view import ensure_indexes

        earlier = self._proposal("toLower(p.name) = toLower($n)", n=name)
        if earlier:                          # never propose the same concept twice
            if self._never_gated(earlier) and self.client is not None:
                info = self._gate(earlier.proposal_id)
                info.note = f"reused earlier proposal {earlier.proposal_id}, {info.note}"
                return info
            earlier.note = f"reused earlier proposal {earlier.proposal_id} ({earlier.note})"
            return earlier
        if self.client is None:
            raise RuntimeError("propose() needs a Claude client (ANTHROPIC_API_KEY)")
        ensure_indexes(self.graph)
        text = (f"An ALI component recorded learner evidence about the concept "
                f"\"{prompt_text(name, 200)}\", which it could not find in the graph.\n"
                f"Context it gave: {prompt_text(context, 1000) or '(none)'}")
        res = run_agent(text, self.graph, self.client, model=self.model)
        save_trace(res)
        d = res.decision
        if d is None:
            raise RuntimeError(f"placement agent failed: {res.error}")
        if d["decision"] == "already_exists":
            u = self._public(d["existing_id"])
            return ConceptInfo("concept", u, name=name, note="agent: already in graph")
        pid = self.graph.write_proposal(
            name=d["concept_name"], name_original=d.get("concept_name_original") or name,
            description=d["description"], parent_id=d["parent_id"],
            confidence=d["confidence"], reasoning=d["reasoning"], method="scrum92-learner",
            model=self.model, trace_id=res.trace_id,
            requires=d.get("prerequisite_ids") or [], enables=d.get("enables_ids") or [],
            prerequisite_reasoning=d.get("prerequisite_reasoning") or "")
        return self._gate(pid)


# ---- tickets (Postgres side) ------------------------------------------------------------

def ticket_for_name(conn, name: str, context: str) -> dict:
    """The ticket for a concept name; a new one (WAITING) if none exists. Caller holds the
    transaction."""
    key = name_key(name)
    row = conn.execute("SELECT * FROM concept_ticket WHERE name_key = %s", (key,)).fetchone()
    if row:
        return row
    tid = str(uuid.uuid4())
    conn.execute("""INSERT INTO concept_ticket (ticket_id, name_key, name, context, state)
                    VALUES (%s, %s, %s, %s, 'WAITING') ON CONFLICT (name_key) DO NOTHING""",
                 (tid, key, name, context))
    row = conn.execute("SELECT * FROM concept_ticket WHERE name_key = %s", (key,)).fetchone()
    if str(row["ticket_id"]) == tid:
        _event(conn, tid, "WAITING", {"name": name})
    return row


def ticket_for_proposal(conn, info: ConceptInfo) -> dict:
    """A request gave the concept_id of a ProposedConcept still in the gate/teacher queue."""
    key = f"proposal:{info.proposal_id}"
    row = conn.execute("SELECT * FROM concept_ticket WHERE name_key = %s", (key,)).fetchone()
    if row:
        return row
    tid = str(uuid.uuid4())
    conn.execute("""INSERT INTO concept_ticket (ticket_id, name_key, name, state, proposal_id)
                    VALUES (%s, %s, %s, 'PROPOSED', %s) ON CONFLICT (name_key) DO NOTHING""",
                 (tid, key, info.name or info.proposal_id, info.proposal_id))
    _event(conn, tid, "PROPOSED", {"proposal_id": info.proposal_id, "from": "concept_id"})
    return conn.execute("SELECT * FROM concept_ticket WHERE name_key = %s", (key,)).fetchone()


def _event(conn, ticket_id, state, detail):
    conn.execute("INSERT INTO concept_ticket_event (ticket_id, state, detail) VALUES (%s, %s, %s)",
                 (ticket_id, state, json.dumps(detail, ensure_ascii=False)))


def _set_state(conn, ticket, info: ConceptInfo):
    state = {"concept": "RESOLVED", "proposed": "PROPOSED", "rejected": "REJECTED"}[info.state]
    if state == ticket["state"] and info.proposal_id == ticket["proposal_id"]:
        return state
    conn.execute("""UPDATE concept_ticket SET state = %s, proposal_id = COALESCE(%s, proposal_id),
                    concept_id = %s WHERE ticket_id = %s""",
                 (state, info.proposal_id, info.concept_id, ticket["ticket_id"]))
    _event(conn, ticket["ticket_id"], state,
           {"proposal_id": info.proposal_id, "concept_id": info.concept_id, "note": info.note})
    if state == "RESOLVED":                 # every waiting record can now be shown
        conn.execute("""INSERT INTO outbox (learner_id, concept_id, request_seq)
                        SELECT DISTINCT ON (learner_id) learner_id, %s, request_seq
                        FROM learner_record WHERE ticket_id = %s
                        ORDER BY learner_id, request_seq""",
                     (info.concept_id, ticket["ticket_id"]))
    return state


def resolve_tickets(conn, directory: ConceptDirectory, progress=print) -> dict:
    """One background pass: send WAITING tickets to SCRUM-89/90, re-check PROPOSED ones.
    Each ticket is its own transaction, so one failure does not undo the others."""
    progress = progress or (lambda *_: None)
    counts = {"RESOLVED": 0, "PROPOSED": 0, "REJECTED": 0, "FAILED": 0}
    todo = conn.execute("""SELECT * FROM concept_ticket WHERE state IN ('WAITING', 'PROPOSED')
                           ORDER BY created_at""").fetchall()
    for t in todo:
        try:
            info = (directory.propose(t["name"], t["context"]) if t["state"] == "WAITING"
                    else directory.proposal_status(t["proposal_id"]))
            if info.state == "concept" and not info.concept_id:
                raise RuntimeError("resolved without a concept_id")
            with conn.transaction():
                cur = conn.execute("SELECT * FROM concept_ticket WHERE ticket_id = %s FOR UPDATE",
                                   (t["ticket_id"],)).fetchone()
                state = _set_state(conn, cur, info)
            counts[state] += 1
            progress(f"  ticket {t['name']!r}: {state}"
                     + (f" -> {info.concept_id}" if info.concept_id else "")
                     + (f" ({info.note})" if info.note else ""))
        except Exception as e:                       # stays WAITING/PROPOSED, retried next run
            counts["FAILED"] += 1
            with conn.transaction():
                _event(conn, t["ticket_id"], "ERROR", {"error": str(e)[:500]})
            progress(f"  ticket {t['name']!r}: failed, will retry ({e})")
    return counts
