"""The only write path from a proposal to the trusted graph (SCRUM-90).

Nothing here changes or deletes an existing Concept or CHILD_OF edge: every write adds a
node or a link that starts or ends at the new concept (append-only, as Eden set).

    gate result                     what is written
    ACCEPT_PROVISIONAL     new :Concept {trust:'provisional'} + CHILD_OF + accepted links
    NEEDS_REVIEW           proposal status 'needs_review' (the teacher's queue)
    REJECT                 proposal status 'rejected' (+ duplicate_of / suggested_parent)

Every gate run is also stored as a :ValidationRun node with the full result, linked to the
proposal, so any decision can be explained later (audit trail).

Trust levels on Concept: absent = SCRUM-88 source ('trusted'), 'provisional' = accepted by
the gate, 'trusted' = confirmed by a teacher or the audit, 'flagged' = the audit found it
wrong; a flagged concept goes to a separate, explicitly governed correction process and is
never deleted here (other ALI services may already hold its concept_id).
"""
import json
import uuid
from datetime import datetime, timezone

from placement.embedder import concept_text, embed
from placement.graph import Graph

from .contract import Decision, Proposal, ValidationResult


def _now():
    return datetime.now(timezone.utc).isoformat()


def record_run(graph: Graph, res: ValidationResult) -> str:
    rid = "V-" + uuid.uuid4().hex[:12]
    graph.driver.execute_query(
        """MATCH (p:ProposedConcept {id: $pid})
           CREATE (v:ValidationRun {id: $rid, gate_version: $ver, decision: $dec, rule: $rule,
                   created_at: $now, result: $json})-[:VALIDATES]->(p)""",
        pid=res.proposal_id, rid=rid, ver=res.gate_version, dec=res.decision.value,
        rule=res.rule, now=_now(), json=json.dumps(res.to_dict(), ensure_ascii=False, default=str))
    return rid


def _promote(tx, p: Proposal, parent_id: str, trust: str, links: list[dict], by: str,
             qid: str | None, audit_priority: bool):
    vec = embed([concept_text(p.name, p.description)])[0].tolist()
    tx.run("""MATCH (p:ProposedConcept {id: $pid}), (par:Concept {id: $parent})
              CREATE (c:Concept {id: $pid, concept_id: p.concept_id, name: p.name,
                      name_original: p.name_original, description: p.description,
                      level: par.level + 1, wikidata: $qid, works_count: 0,
                      disambiguation_suspect: false, trust: $trust, accepted_by: $by,
                      accepted_at: $now, audit_priority: $prio,
                      source: 'ALI proposal ' + $pid})
              CREATE (c)-[:CHILD_OF {primary: true, similarity: null, flags: [], trust: $trust,
                      source: 'ALI gate'}]->(par)
              CREATE (p)-[:BECAME]->(c)
              SET p.status = 'accepted', p.decided_at = $now
              WITH c CALL db.create.setNodeVectorProperty(c, 'embedding', $vec)""",
           pid=p.id, parent=parent_id, qid=qid or "", trust=trust, by=by, now=_now(),
           prio=audit_priority, vec=vec)
    for e in links:
        tx.run("""MATCH (a:Concept {id: $a}), (b:Concept {id: $b})
                  MERGE (a)-[r:PREREQUISITE_OF]->(b)
                  SET r.trust = $trust, r.source = 'ALI gate', r.created_at = $now""",
               a=e["from"], b=e["to"], trust=trust, now=_now())


def _mark_links(tx, pid: str, links: list[dict]):
    for e in links:
        tx.run("""MATCH (a {id: $a})-[r:PROPOSED_PREREQUISITE_OF]->(b {id: $b})
                  WHERE a.id = $pid OR b.id = $pid
                  SET r.status = $status, r.rule = $rule""",
               a=e["from"], b=e["to"], pid=pid, status=e["decision"].lower(), rule=e["rule"])


def apply(graph: Graph, p: Proposal, res: ValidationResult) -> str:
    """Write the gate's decision. Returns a one-line summary."""
    qid = (res.signals.get("external") or {}).get("resolved")
    accepted_links = [e for e in res.edges if e["decision"] == Decision.ACCEPT_PROVISIONAL.value]
    with graph.driver.session() as s:
        if res.decision is Decision.ACCEPT_PROVISIONAL:
            s.execute_write(_promote, p, p.parent_ids[0], "provisional", accepted_links,
                            f"gate {res.gate_version} rule {res.rule}", qid, res.audit_priority)
            s.execute_write(_mark_links, p.id, res.edges)
            return f"{p.id} is now a provisional Concept ({len(accepted_links)} prerequisite links)"
        status = "needs_review" if res.decision is Decision.NEEDS_REVIEW else "rejected"
        s.run("""MATCH (p:ProposedConcept {id: $pid})
                 SET p.status = $st, p.decided_at = $now, p.duplicate_of = $dup,
                     p.suggested_parent = $sug, p.review = $review""",
              pid=p.id, st=status, now=_now(), dup=res.duplicate_of, sug=res.suggested_parent,
              review=json.dumps(res.review, ensure_ascii=False) if res.review else None)
        s.execute_write(_mark_links, p.id, res.edges)
    return f"{p.id} is {status}" + (f" (duplicate of {res.duplicate_of})" if res.duplicate_of else "")


def teacher_accept(graph: Graph, p: Proposal, parent_id: str, teacher: str,
                   link_ids: list[str]) -> str:
    """The teacher picked a parent (the agent's or the validator's) and the links to keep."""
    links = []
    for cid in link_ids:
        if cid in p.requires:
            links.append({"from": cid, "to": p.id, "decision": "ACCEPT_PROVISIONAL", "rule": "T"})
        elif cid in p.enables:
            links.append({"from": p.id, "to": cid, "decision": "ACCEPT_PROVISIONAL", "rule": "T"})
    with graph.driver.session() as s:
        s.execute_write(_promote, p, parent_id, "trusted", links, f"teacher {teacher}", None, False)
        s.execute_write(_mark_links, p.id, links)
    return f"{p.id} is now a trusted Concept under {parent_id}"


def teacher_reject(graph: Graph, pid: str, teacher: str) -> str:
    graph.driver.execute_query(
        """MATCH (p:ProposedConcept {id: $pid}) SET p.status = 'rejected', p.decided_at = $now,
                  p.decided_by = $who""", pid=pid, now=_now(), who=f"teacher {teacher}")
    return f"{pid} is rejected by the teacher"


def audit_set(graph: Graph, cid: str, verdict: str, who: str) -> str:
    """verdict: 'trusted' (confirmed) or 'flagged' (wrong: for the governed correction process)."""
    assert verdict in ("trusted", "flagged")
    graph.driver.execute_query(
        """MATCH (c:Concept {id: $cid}) WHERE c.trust = 'provisional'
           SET c.trust = $v, c.audited_by = $who, c.audited_at = $now
           WITH c MATCH (c)-[r:CHILD_OF|PREREQUISITE_OF]-() WHERE r.trust = 'provisional'
           SET r.trust = $v""", cid=cid, v=verdict, who=who, now=_now())
    return f"{cid} is now {verdict}"
