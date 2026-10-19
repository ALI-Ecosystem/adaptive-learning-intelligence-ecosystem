"""SCRUM-92 command line. Normally run through ./scrum92.sh.

  python -m learner_graph.cli init                  create the schema (idempotent)
  python -m learner_graph.cli demo                  register demo senders, send the demo requests
  python -m learner_graph.cli submit FILE.json      apply one signed envelope
  python -m learner_graph.cli project               apply pending outbox rows to Neo4j
  python -m learner_graph.cli resolve               SCRUM-89/90 for concepts the DKG lacks (Claude)
  python -m learner_graph.cli show LEARNER          the learner graph, from the Neo4j view
  python -m learner_graph.cli log LEARNER           every request for the learner, from the log
  python -m learner_graph.cli audit [N]             last N attempts, rejected ones included
  python -m learner_graph.cli verify [LEARNER]      view == log ?
  python -m learner_graph.cli rebuild [LEARNER]     drop the view and rebuild it from the log
"""
import json
import sys
import uuid
from pathlib import Path

from placement import config

from . import db, projector, service, signing
from .client import SenderClient
from .concepts import Neo4jDirectory, resolve_tickets

KEYS = config.RUNS_DIR / "learner-graph" / "keys"
DEMO_LEARNER = str(uuid.uuid5(uuid.NAMESPACE_URL, "ali:scrum-92:demo-learner"))

DEMO_SENDERS = {   # sender -> (operations, may correct other senders' records)
    "evidence-module": (["ADD_EVIDENCE", "RETRACT", "SUPERSEDE"], False),
    "content-delivery": (["ADD_EXPOSURE", "RETRACT"], False),
    "teacher-console": (["RETRACT", "SUPERSEDE"], True),
}


def _neo():
    from placement.graph import Graph, connect
    driver = connect()
    return driver, Graph(driver)


def _sender(conn, name) -> SenderClient:
    """A demo sender with a key kept in runs/ (git-ignored), so reruns use the same key."""
    KEYS.mkdir(parents=True, exist_ok=True)
    path = KEYS / f"{name}.pem"
    if path.exists():
        key = signing.load_private(path.read_bytes())
    else:
        key = signing.new_key()
        path.write_bytes(signing.private_pem(key))
        path.chmod(0o600)
    ops, privileged = DEMO_SENDERS[name]
    db.register_sender(conn, name, signing.public_bytes(key), ops, privileged)
    return SenderClient(name, key)


def _concept_id(graph, name):
    rows = graph._read("MATCH (c:Concept {name: $n}) RETURN c.concept_id AS u LIMIT 1", n=name)
    if not rows or not rows[0]["u"]:
        raise SystemExit(f"concept {name!r} is not in the graph (or has no concept_id): "
                         f"run ./scrum90.sh setup first")
    return rows[0]["u"]


def _print_outcome(label, out):
    d = out.to_dict()
    code = f" {d['code']}" if "code" in d else ""
    print(f"  {label:<46} -> {d['status']}{code}: {d['message']}")


def demo(conn, graph):
    """The SCRUM-92 example, on the real Domain Knowledge Graph."""
    ev, cd, teacher = (_sender(conn, n) for n in DEMO_SENDERS)
    rec = _concept_id(graph, "Recursion (computer science)")
    stack = _concept_id(graph, "Stack (abstract data type)")
    directory = Neo4jDirectory(graph)
    L = DEMO_LEARNER
    t = lambda d, h: f"2026-10-{d:02d}T{h:02d}:00:00+03:00"

    def send(label, env):
        _print_outcome(label, service.apply(conn, env, directory))

    def evid(rid, day, hour, concept, outcome, req):
        return ev.add_evidence(L, concept_id=concept, source_record_id=rid,
                               occurred_at=t(day, hour), request_id=req,
                               payload={"item": rid, "outcome": outcome, "attempt": 1})

    print(f"learner {L}\n")
    print("1) the learner graph that already exists")
    send("exposure: lesson on recursion", cd.add_exposure(
        L, concept_id=rec, source_record_id="lesson-recursion-1", occurred_at=t(12, 9),
        request_id="demo-01", payload={"material": "Course unit 3 - Recursion"}))
    send("evidence A on Recursion", evid("attempt-A", 12, 10, rec, "CORRECT", "demo-02"))
    send("evidence B on Recursion", evid("attempt-B", 13, 10, rec, "WRONG", "demo-03"))

    print("\n2) new requests arriving over time")
    send("new evidence C for Recursion", evid("attempt-C", 19, 10, rec, "CORRECT", "demo-04"))
    send("the same request again (network retry)", evid("attempt-C", 19, 10, rec, "CORRECT", "demo-04"))
    send("record C again in a new request", evid("attempt-C", 19, 10, rec, "CORRECT", "demo-05"))
    send("request id demo-04 reused, other content", evid("attempt-C", 19, 10, rec, "WRONG", "demo-04"))
    send("evidence D on Stack (new for this learner)", evid("attempt-D", 19, 11, stack, "CORRECT", "demo-06"))
    send("evidence E on a concept not in the DKG", ev.add_evidence(
        L, name="Tail recursion", context="Learner asked why tail calls do not grow the stack",
        source_record_id="attempt-E", occurred_at=t(19, 12), request_id="demo-07",
        payload={"item": "attempt-E", "outcome": "PARTIAL"}))
    send("teacher retracts B (wrong answer key)", teacher.retract(
        L, "evidence-module", "attempt-B", "answer key for item B was wrong", request_id="demo-08"))
    send("evidence module regrades A", ev.supersede(
        L, "evidence-module", "attempt-A", "regraded after rubric fix", concept_id=rec,
        source_record_id="attempt-A-v2", occurred_at=t(12, 10), request_id="demo-09",
        payload={"item": "attempt-A", "outcome": "PARTIAL", "attempt": 1}))
    send("content-delivery tries to retract C", cd.retract(
        L, "evidence-module", "attempt-C", "not my record", request_id="demo-10"))
    tampered = evid("attempt-F", 19, 13, rec, "WRONG", "demo-11")
    tampered["body"]["record"]["payload"]["outcome"] = "CORRECT"
    send("evidence F changed after signing", tampered)
    print("\nnext: ./scrum92.sh project, then ./scrum92.sh show " + L)


def show(driver, learner):
    recs, _, _ = driver.execute_query(
        """MATCH (l:Learner {learner_id: $l})-[:HAS_CONCEPT]->(lc)-[:INSTANCE_OF]->(c:Concept)
           OPTIONAL MATCH (lc)-[:HAS_RECORD]->(r)
           OPTIONAL MATCH (r)-[:SUPERSEDED_BY]->(n)
           RETURN c.name AS concept, c.concept_id AS cid, lc.evidence_valid AS ev,
                  lc.exposure_valid AS ex, r.kind AS kind, r.source_record_id AS rid,
                  r.valid AS valid, r.occurred_at AS at, r.origin_sender AS sender,
                  r.request_id AS req, r.payload_json AS payload, r.changed_by AS change,
                  r.change_reason AS why, r.change_actor AS actor, n.source_record_id AS by
           ORDER BY concept, r.occurred_at, r.request_seq""", l=learner)
    if not recs:
        print("no learner graph in the view (did you run ./scrum92.sh project?)")
        return
    print(f"Learner {learner}")
    last = None
    for r in recs:
        if r["concept"] != last:
            last = r["concept"]
            print(f"  {r['concept']}  [{r['cid']}]  valid evidence {r['ev']}, valid exposure {r['ex']}")
        if r["rid"] is None:
            continue
        mark = "+" if r["valid"] else "x"
        line = (f"    {mark} {r['kind'].lower():<8} {r['rid']:<20} {r['at'][:16]}Z "
                f"{r['sender']} / {r['req']}  {r['payload']}")
        print(line)
        if not r["valid"]:
            print(f"        {r['change'].lower()} by {r['actor']}: {r['why']}"
                  + (f" -> {r['by']}" if r["by"] else ""))


def log(conn, learner):
    for r in conn.execute("""SELECT seq, received_at, sender_id, request_id, operation, outcome, detail
                             FROM update_request WHERE learner_id = %s ORDER BY seq""", (learner,)):
        print(f"  #{r['seq']:<4} {r['received_at']:%Y-%m-%d %H:%M:%S}  {r['sender_id']:<17} "
              f"{r['request_id']:<10} {r['operation']:<13} {r['outcome']:<16} {r['detail']}")
    pend = conn.execute("""SELECT r.source_record_id, t.name, t.state FROM learner_record r
                           JOIN concept_ticket t USING (ticket_id)
                           WHERE r.learner_id = %s AND t.state <> 'RESOLVED'""", (learner,)).fetchall()
    for p in pend:
        print(f"  waiting: {p['source_record_id']} on concept {p['name']!r} ({p['state']})")


def audit(conn, n):
    rows = conn.execute("SELECT * FROM request_audit ORDER BY id DESC LIMIT %s", (n,)).fetchall()
    for r in reversed(rows):
        print(f"  {r['received_at']:%H:%M:%S}  {str(r['sender_claimed']):<17} {str(r['request_id']):<10} "
              f"{str(r['operation']):<13} {r['outcome']:<16} {r['reason']}")


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    conn = db.connect()
    if cmd == "init":
        db.migrate(conn)
        print("schema learner_graph ready")
        return 0
    if cmd == "log":
        return log(conn, rest[0])
    if cmd == "audit":
        return audit(conn, int(rest[0]) if rest else 30)

    driver, graph = _neo()
    try:
        if cmd == "demo":
            projector.ensure_constraints(driver)
            demo(conn, graph)
        elif cmd == "submit":
            env = json.loads(Path(rest[0]).read_text())
            print(json.dumps(service.apply(conn, env, Neo4jDirectory(graph)).to_dict(), indent=2))
        elif cmd == "project":
            projector.ensure_constraints(driver)
            d = projector.drain(conn, driver, progress=print)
            for e in d["errors"]:
                print("  error:", e)
        elif cmd == "resolve":
            from placement.agent import make_client
            from validation import refd, wikidata
            wd = wikidata.WikidataClient(config.RUNS_DIR / "wikidata-cache.json")
            wp = refd.WikipediaClient(config.RUNS_DIR / "wikipedia-cache.json")
            directory = Neo4jDirectory(graph, make_client(), wd, wp)
            print(resolve_tickets(conn, directory))
            wd.save(); wp.save()
            projector.drain(conn, driver, progress=print)
        elif cmd == "show":
            show(driver, rest[0] if rest else DEMO_LEARNER)
        elif cmd == "verify":
            v = projector.verify(conn, driver, rest[0] if rest else None)
            print(json.dumps(v, indent=2, default=str))
            return 0 if v["ok"] else 2
        elif cmd == "rebuild":
            n = projector.rebuild(conn, driver, rest[0] if rest else None)
            print(f"rebuilt {n} learner-concept parts from the log")
        else:
            print(__doc__)
            return 1
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
