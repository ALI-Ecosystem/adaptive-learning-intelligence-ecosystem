"""The Neo4j view of the learner graph, built only from the Postgres log.

    (:Learner {learner_id})
      -[:HAS_CONCEPT]-> (:LearnerConcept {key, learner_id, concept_id, counts...})
                          -[:INSTANCE_OF]-> (:Concept {concept_id})        the canonical DKG node
                          -[:HAS_RECORD]->  (:LearnerRecord:Evidence | :LearnerRecord:Exposure)
    (:LearnerRecord) -[:SUPERSEDED_BY]-> (:LearnerRecord)

Each outbox row names one (learner, concept). The projector re-reads that part of the log
and makes the view match it exactly, so applying a row twice, or after a crash, gives the
same result (idempotent), and only that part of the graph is touched.

Retracted and superseded records stay in the view with valid = false: the history is
visible; queries that want the current state filter on valid. Records waiting for their
concept (SCRUM-89/90) are not shown until the concept is accepted.

The view holds no learner state of its own: drop it and `rebuild` gives it back.
"""
import json

CONSTRAINTS = [
    "CREATE CONSTRAINT learner_id IF NOT EXISTS FOR (l:Learner) REQUIRE l.learner_id IS UNIQUE",
    "CREATE CONSTRAINT learner_concept_key IF NOT EXISTS FOR (lc:LearnerConcept) REQUIRE lc.key IS UNIQUE",
    "CREATE CONSTRAINT learner_record_uid IF NOT EXISTS FOR (r:LearnerRecord) REQUIRE r.record_uid IS UNIQUE",
]


class ProjectionError(RuntimeError):
    pass


def ensure_constraints(driver):
    for q in CONSTRAINTS:
        driver.execute_query(q)


def _iso(t):
    return t.isoformat() if t else None


def _records(conn, learner_id, concept_id):
    return conn.execute(
        """SELECT s.*, u.request_id, u.sender_id AS request_sender, u.received_at
           FROM record_state s JOIN update_request u ON u.seq = s.request_seq
           WHERE s.learner_id = %s AND s.effective_concept_id = %s
           ORDER BY s.occurred_at, s.request_seq""", (learner_id, concept_id)).fetchall()


def _props(r) -> dict:
    return {
        "uid": str(r["record_uid"]), "kind": r["kind"],
        "p": {"learner_id": str(r["learner_id"]), "kind": r["kind"], "valid": r["valid"],
              "origin_sender": r["origin_sender"], "source_record_id": r["source_record_id"],
              "occurred_at": _iso(r["occurred_at"]), "recorded_at": _iso(r["recorded_at"]),
              "request_seq": r["request_seq"], "request_id": r["request_id"],
              "payload_json": json.dumps(r["payload"], ensure_ascii=False, sort_keys=True),
              "via_ticket": str(r["ticket_id"]) if r["ticket_id"] else None,
              "changed_by": r["changed_by"], "change_reason": r["change_reason"],
              "change_actor": r["change_actor"], "changed_at": _iso(r["changed_at"])}}


def project_one(conn, driver, learner_id, concept_id) -> int:
    """Make the view of one (learner, concept) equal to the log. Returns records shown."""
    learner_id, concept_id = str(learner_id), str(concept_id)
    rows = _records(conn, learner_id, concept_id)
    recs = [_props(r) for r in rows]
    uids = [r["uid"] for r in recs]
    links = conn.execute(
        """SELECT r.record_uid AS old, c.replacement_uid AS new FROM record_change c
           JOIN learner_record r ON r.origin_sender = c.target_sender
                AND r.source_record_id = c.target_source_record_id AND r.learner_id = c.learner_id
           WHERE c.change = 'SUPERSEDE' AND (r.record_uid = ANY(%s::uuid[])
                                             OR c.replacement_uid = ANY(%s::uuid[]))""",
        (uids, uids)).fetchall()
    valid = [r for r in rows if r["valid"]]
    summary = {
        "evidence_total": sum(1 for r in rows if r["kind"] == "EVIDENCE"),
        "evidence_valid": sum(1 for r in valid if r["kind"] == "EVIDENCE"),
        "exposure_total": sum(1 for r in rows if r["kind"] == "EXPOSURE"),
        "exposure_valid": sum(1 for r in valid if r["kind"] == "EXPOSURE"),
        "first_occurred_at": _iso(min((r["occurred_at"] for r in rows), default=None)),
        "last_occurred_at": _iso(max((r["occurred_at"] for r in rows), default=None)),
        "last_request_seq": max((r["request_seq"] for r in rows), default=None),
    }
    with driver.session() as s:
        s.execute_write(_write, learner_id, concept_id, recs, uids, summary,
                        [{"old": str(l["old"]), "new": str(l["new"])} for l in links])
    return len(recs)


def _write(tx, learner_id, concept_id, recs, uids, summary, links):
    found = tx.run("MATCH (c:Concept {concept_id: $c}) RETURN c.name AS name",
                   c=concept_id).single()
    if found is None:
        raise ProjectionError(f"concept {concept_id} is not in the Domain Knowledge Graph")
    tx.run("""MERGE (l:Learner {learner_id: $l})
              WITH l MATCH (c:Concept {concept_id: $c})
              MERGE (lc:LearnerConcept {key: $l + '|' + $c})
                ON CREATE SET lc.learner_id = $l, lc.concept_id = $c, lc.created_at = datetime()
              MERGE (l)-[:HAS_CONCEPT]->(lc)
              MERGE (lc)-[:INSTANCE_OF]->(c)
              SET lc += $summary, lc.concept_name = c.name, lc.projected_at = datetime()""",
           l=learner_id, c=concept_id, summary=summary)
    tx.run("""MATCH (lc:LearnerConcept {key: $key})
              UNWIND $recs AS r
              MERGE (n:LearnerRecord {record_uid: r.uid})
              SET n += r.p
              FOREACH (_ IN CASE WHEN r.kind = 'EVIDENCE' THEN [1] ELSE [] END | SET n:Evidence)
              FOREACH (_ IN CASE WHEN r.kind = 'EXPOSURE' THEN [1] ELSE [] END | SET n:Exposure)
              MERGE (lc)-[:HAS_RECORD]->(n)""",
           key=f"{learner_id}|{concept_id}", recs=recs)
    # the view must not keep anything the log does not have
    tx.run("""MATCH (:LearnerConcept {key: $key})-[:HAS_RECORD]->(n:LearnerRecord)
              WHERE NOT n.record_uid IN $uids DETACH DELETE n""",
           key=f"{learner_id}|{concept_id}", uids=uids)
    tx.run("""UNWIND $links AS e
              MATCH (a:LearnerRecord {record_uid: e.old}), (b:LearnerRecord {record_uid: e.new})
              MERGE (a)-[:SUPERSEDED_BY]->(b)""", links=links)


def run_once(conn, driver, batch: int = 500, progress=None) -> dict:
    """Project pending outbox rows. Rows stay pending if Neo4j fails, and are retried."""
    done = {"rows": 0, "parts": 0, "errors": []}
    with conn.transaction():
        rows = conn.execute("""SELECT seq, learner_id, concept_id FROM outbox
                               WHERE projected_at IS NULL ORDER BY seq LIMIT %s
                               FOR UPDATE SKIP LOCKED""", (batch,)).fetchall()
        parts = list(dict.fromkeys((str(r["learner_id"]), str(r["concept_id"])) for r in rows))
        ok = set()
        for learner_id, concept_id in parts:
            try:
                project_one(conn, driver, learner_id, concept_id)
                ok.add((learner_id, concept_id))
            except ProjectionError as e:
                done["errors"].append(str(e))
        seqs = [r["seq"] for r in rows if (str(r["learner_id"]), str(r["concept_id"])) in ok]
        if seqs:
            conn.execute("UPDATE outbox SET projected_at = clock_timestamp() WHERE seq = ANY(%s)",
                         (seqs,))
        done["rows"], done["parts"] = len(seqs), len(ok)
    if progress:
        progress(f"projected {done['rows']} outbox rows into {done['parts']} learner-concept parts"
                 + (f", {len(done['errors'])} errors" if done["errors"] else ""))
    return done


def drain(conn, driver, progress=None) -> dict:
    total = {"rows": 0, "parts": 0, "errors": []}
    while True:
        d = run_once(conn, driver, progress=progress)
        total["rows"] += d["rows"]; total["parts"] += d["parts"]; total["errors"] += d["errors"]
        if d["rows"] == 0:
            return total


def rebuild(conn, driver, learner_id: str | None = None) -> int:
    """Drop the view (of one learner, or all) and build it again from the log."""
    if learner_id:
        driver.execute_query("""MATCH (l:Learner {learner_id: $l})
                                OPTIONAL MATCH (l)-[:HAS_CONCEPT]->(lc)
                                OPTIONAL MATCH (lc)-[:HAS_RECORD]->(r)
                                DETACH DELETE r, lc, l""", l=str(learner_id))
        parts = conn.execute("""SELECT DISTINCT learner_id, effective_concept_id FROM record_state
                                WHERE learner_id = %s AND effective_concept_id IS NOT NULL""",
                             (learner_id,)).fetchall()
    else:
        driver.execute_query("MATCH (n) WHERE n:Learner OR n:LearnerConcept OR n:LearnerRecord "
                             "DETACH DELETE n")
        parts = conn.execute("""SELECT DISTINCT learner_id, effective_concept_id FROM record_state
                                WHERE effective_concept_id IS NOT NULL""").fetchall()
    for p in parts:
        project_one(conn, driver, p["learner_id"], p["effective_concept_id"])
    return len(parts)


def verify(conn, driver, learner_id: str | None = None) -> dict:
    """Compare the view with the log: every shown record, its concept and its validity."""
    where, args = ("AND learner_id = %s", (learner_id,)) if learner_id else ("", ())
    log = {(str(r["record_uid"]), str(r["learner_id"]), str(r["effective_concept_id"]), r["valid"])
           for r in conn.execute(f"""SELECT record_uid, learner_id, effective_concept_id, valid
                                     FROM record_state WHERE effective_concept_id IS NOT NULL
                                     {where}""", args).fetchall()}
    q = """MATCH (l:Learner)-[:HAS_CONCEPT]->(lc:LearnerConcept)-[:HAS_RECORD]->(r:LearnerRecord)
           MATCH (lc)-[:INSTANCE_OF]->(c:Concept)
           WHERE $l IS NULL OR l.learner_id = $l
           RETURN r.record_uid AS u, l.learner_id AS l, c.concept_id AS c, r.valid AS v"""
    recs, _, _ = driver.execute_query(q, l=str(learner_id) if learner_id else None)
    view = {(r["u"], r["l"], r["c"], r["v"]) for r in recs}
    pending = conn.execute("SELECT count(*) AS n FROM outbox WHERE projected_at IS NULL").fetchone()["n"]
    return {"log_records": len(log), "view_records": len(view),
            "missing_in_view": sorted(log - view), "extra_in_view": sorted(view - log),
            "outbox_pending": pending, "ok": log == view and pending == 0}
