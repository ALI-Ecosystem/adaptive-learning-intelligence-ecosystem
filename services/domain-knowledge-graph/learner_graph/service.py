"""UPDATE LEARNER GRAPH (existing learner graph, explicit requested change) - the write path.

    apply(conn, envelope, directory) -> Outcome

Order of checks, cheapest and most security-relevant first:
  1 shape (contract.parse)          INVALID
  2 sender registered and active    UNKNOWN_SENDER
  3 Ed25519 signature               BAD_SIGNATURE
  4 sender may use the operation    FORBIDDEN
  then one Postgres transaction, serialised per learner:
  5 idempotency key (sender, request_id): same content -> DUPLICATE, else CONFLICT
  6 the operation itself (concept, record natural key, correction rules)
  7 log rows + outbox row, committed together

The component executes and stores; it never decides what the evidence means. Nothing here
reads the payload, and no LLM runs on this path.
"""
from datetime import datetime, timezone

import psycopg

from . import signing
from .concepts import ConceptDirectory, ticket_for_name, ticket_for_proposal
from .contract import (InvalidRequest, Operation, Outcome, Reject, Request, Status,
                       name_key, parse)
import json
import uuid


class _Stop(Exception):
    """Ends the transaction with a rejection (rolled back) or a no-op (committed)."""

    def __init__(self, outcome: Outcome, commit: bool = False):
        self.outcome, self.commit = outcome, commit


def _reject(code: Reject, msg: str) -> Outcome:
    return Outcome(Status.REJECTED, code, msg)


def _audit(conn, req_or_body, outcome: Outcome, fingerprint=None):
    b = req_or_body.body if isinstance(req_or_body, Request) else (
        req_or_body if isinstance(req_or_body, dict) else {})
    s = lambda k: str(b.get(k))[:200] if b.get(k) is not None else None
    conn.execute(
        """INSERT INTO request_audit (sender_claimed, request_id, learner_id, operation,
                                      outcome, reason, fingerprint, request_seq)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (s("sender"), s("request_id"), s("learner_id"), s("operation"),
         outcome.code.value if outcome.code else outcome.status.value,
         outcome.message[:500], fingerprint, outcome.request_seq))


def apply(conn: psycopg.Connection, envelope, directory: ConceptDirectory,
          now: datetime | None = None) -> Outcome:
    body = envelope.get("body") if isinstance(envelope, dict) else None
    try:
        req = parse(envelope, now)
    except InvalidRequest as e:
        out = _reject(Reject.INVALID, str(e))
        _audit(conn, body, out)
        return out

    sender = conn.execute("SELECT * FROM sender WHERE sender_id = %s AND active",
                          (req.sender,)).fetchone()
    if sender is None:
        out = _reject(Reject.UNKNOWN_SENDER, f"{req.sender} is not a registered sender")
    elif not signing.verify(req.body, req.signature, sender["public_key"]):
        out = _reject(Reject.BAD_SIGNATURE, "signature does not match the sender's key")
    elif req.operation.value not in sender["operations"]:
        out = _reject(Reject.FORBIDDEN, f"{req.sender} may not {req.operation.value}")
    else:
        out = None
    if out:
        _audit(conn, req, out)
        return out

    for attempt in range(2):        # a unique-key race with a concurrent request: retry once
        try:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 92))",
                             (req.learner_id,))
                try:
                    out = _apply_locked(conn, req, sender, directory)
                except _Stop as stop:
                    if stop.commit:
                        out = stop.outcome
                    else:
                        raise
                _audit(conn, req, out, req.fingerprint)
            return out
        except _Stop as stop:
            out = stop.outcome
            break
        except psycopg.errors.UniqueViolation:
            if attempt == 1:
                out = _reject(Reject.CONFLICT, "a concurrent request used the same key")
    _audit(conn, req, out, req.fingerprint)
    return out


# ---- inside the transaction -------------------------------------------------------------

def _apply_locked(conn, req: Request, sender: dict, directory) -> Outcome:
    prev = conn.execute("SELECT * FROM update_request WHERE sender_id = %s AND request_id = %s",
                        (req.sender, req.request_id)).fetchone()
    if prev:
        if prev["fingerprint"] != req.fingerprint:
            raise _Stop(_reject(Reject.CONFLICT, f"request_id {req.request_id} was already used "
                                                 f"with different content (seq {prev['seq']})"))
        rec = conn.execute("SELECT record_uid FROM learner_record WHERE request_seq = %s",
                           (prev["seq"],)).fetchone()
        original = {"status": prev["outcome"], "request_seq": prev["seq"],
                    "received_at": prev["received_at"].isoformat(), "detail": prev["detail"]}
        if rec:
            original["record_uid"] = str(rec["record_uid"])
        return Outcome(Status.DUPLICATE, message="same request already received; nothing changed",
                       request_seq=prev["seq"], original=original)

    if req.operation in (Operation.RETRACT, Operation.SUPERSEDE):
        if req.target_sender != req.sender and not sender["can_correct_others"]:
            raise _Stop(_reject(Reject.FORBIDDEN, f"{req.sender} may only correct its own records"))

    if req.operation is Operation.RETRACT:
        return _retract(conn, req)
    if req.operation is Operation.SUPERSEDE:
        return _supersede(conn, req, directory)
    return _add(conn, req, directory)


def _log_request(conn, req: Request, outcome: Status, detail: str = "") -> int:
    row = conn.execute(
        """INSERT INTO update_request (sender_id, request_id, learner_id, operation, fingerprint,
                                       body, signature, outcome, detail)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING seq""",
        (req.sender, req.request_id, req.learner_id, req.operation.value, req.fingerprint,
         json.dumps(req.body, ensure_ascii=False), req.signature, outcome.value, detail)).fetchone()
    return row["seq"]


def _outbox(conn, learner_id, concept_id, seq):
    if concept_id:
        conn.execute("INSERT INTO outbox (learner_id, concept_id, request_seq) VALUES (%s, %s, %s)",
                     (learner_id, concept_id, seq))


def _resolve_concept(conn, req: Request, directory) -> tuple[str | None, dict | None]:
    """-> (concept_id, None) when the canonical concept is known, (None, ticket) when the
    record must wait for SCRUM-89/90."""
    if req.concept_id:
        info = directory.lookup(req.concept_id)
        if info is None:
            raise _Stop(_reject(Reject.UNKNOWN_CONCEPT,
                                f"{req.concept_id} is not a Domain Knowledge Graph concept"))
        if info.state == "concept":
            return info.concept_id, None        # may differ: a proposal that became a duplicate
        if info.state == "rejected":
            raise _Stop(_reject(Reject.CONCEPT_REJECTED, f"concept {req.concept_id} was rejected"))
        return None, ticket_for_proposal(conn, info)
    t = ticket_for_name(conn, req.concept_name, req.concept_context)
    if t["state"] == "RESOLVED":
        return str(t["concept_id"]), None
    if t["state"] == "REJECTED":
        raise _Stop(_reject(Reject.CONCEPT_REJECTED,
                            f"concept {req.concept_name!r} was not accepted into the graph"))
    return None, t


def _same_concept(existing: dict, req: Request, concept_id) -> bool:
    if req.concept_id:
        return req.concept_id in (str(existing["concept_id"] or ""),
                                  str(existing["effective_concept_id"] or "")) or (
            concept_id and str(existing["effective_concept_id"] or "") == concept_id)
    t_key = existing.get("ticket_name_key")
    return t_key == name_key(req.concept_name) or (
        concept_id is not None and str(existing["effective_concept_id"] or "") == concept_id)


def _insert_record(conn, req: Request, directory, seq_holder: list) -> tuple[str, str | None, dict | None]:
    """Shared by ADD_* and SUPERSEDE. Returns (record_uid, concept_id, ticket)."""
    concept_id, ticket = _resolve_concept(conn, req, directory)
    existing = conn.execute(
        """SELECT s.*, t.name_key AS ticket_name_key FROM record_state s
           LEFT JOIN concept_ticket t ON t.ticket_id = s.ticket_id
           WHERE s.origin_sender = %s AND s.source_record_id = %s""",
        (req.sender, req.source_record_id)).fetchone()
    if existing:
        same = (str(existing["learner_id"]) == req.learner_id
                and existing["content_fingerprint"] == req.record_fingerprint
                and existing["kind"] == req.kind
                and _same_concept(existing, req, concept_id))
        if not same:
            raise _Stop(_reject(Reject.CONFLICT,
                                f"record {req.source_record_id} already exists with different "
                                f"content (request seq {existing['request_seq']})"))
        return None, concept_id, ticket          # caller turns this into NO_OP

    early = conn.execute(
        """SELECT learner_id FROM record_change WHERE target_sender = %s
           AND target_source_record_id = %s""", (req.sender, req.source_record_id)).fetchone()
    if early and str(early["learner_id"]) != req.learner_id:
        raise _Stop(_reject(Reject.CONFLICT, "an earlier correction names this record for "
                                             "another learner"))

    status = Status.APPLIED if concept_id else Status.PENDING_CONCEPT
    seq = _log_request(conn, req, status,
                       "" if concept_id else f"waiting for concept ticket {ticket['ticket_id']}")
    seq_holder.append(seq)
    uid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO learner_record (record_uid, learner_id, kind, concept_id, ticket_id,
               origin_sender, source_record_id, payload, occurred_at, request_seq,
               content_fingerprint)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (uid, req.learner_id, req.kind, concept_id, ticket["ticket_id"] if ticket else None,
         req.sender, req.source_record_id, json.dumps(req.payload, ensure_ascii=False),
         req.occurred_at, seq, req.record_fingerprint))
    _outbox(conn, req.learner_id, concept_id, seq)
    return uid, concept_id, ticket


def _add(conn, req: Request, directory) -> Outcome:
    seqs = []
    uid, concept_id, ticket = _insert_record(conn, req, directory, seqs)
    if uid is None:
        seq = _log_request(conn, req, Status.NO_OP, "record already recorded by another request")
        raise _Stop(Outcome(Status.NO_OP, message="this record is already in the learner graph",
                            request_seq=seq), commit=True)
    if concept_id:
        return Outcome(Status.APPLIED, message=f"{req.kind.lower()} added", request_seq=seqs[0],
                       record_uid=uid)
    return Outcome(Status.PENDING_CONCEPT, request_seq=seqs[0], record_uid=uid,
                   ticket_id=str(ticket["ticket_id"]),
                   message="stored; shown once its concept is accepted into the graph")


def _target(conn, req: Request):
    return conn.execute(
        """SELECT * FROM record_state WHERE origin_sender = %s AND source_record_id = %s""",
        (req.target_sender, req.target_source_record_id)).fetchone()


def _existing_change(conn, req: Request):
    return conn.execute(
        """SELECT * FROM record_change WHERE target_sender = %s AND target_source_record_id = %s""",
        (req.target_sender, req.target_source_record_id)).fetchone()


def _retract(conn, req: Request) -> Outcome:
    target = _target(conn, req)
    if target and str(target["learner_id"]) != req.learner_id:
        raise _Stop(_reject(Reject.CONFLICT, "the target record belongs to another learner"))
    prev = _existing_change(conn, req)
    if prev:
        if prev["change"] == "RETRACT" and str(prev["learner_id"]) == req.learner_id:
            seq = _log_request(conn, req, Status.NO_OP, "already retracted")
            raise _Stop(Outcome(Status.NO_OP, message="record was already retracted",
                                request_seq=seq), commit=True)
        raise _Stop(_reject(Reject.CONFLICT, f"record was already {prev['change'].lower()}d "
                                             f"(request seq {prev['request_seq']})"))
    seq = _log_request(conn, req, Status.APPLIED, "" if target else "target not received yet")
    conn.execute(
        """INSERT INTO record_change (learner_id, target_sender, target_source_record_id, change,
                                      reason, actor, request_seq)
           VALUES (%s, %s, %s, 'RETRACT', %s, %s, %s)""",
        (req.learner_id, req.target_sender, req.target_source_record_id, req.reason, req.sender,
         seq))
    if target:
        _outbox(conn, req.learner_id, target["effective_concept_id"], seq)
    return Outcome(Status.APPLIED, request_seq=seq,
                   message="record retracted" if target else
                   "retraction stored; the record will arrive already retracted")


def _supersede(conn, req: Request, directory) -> Outcome:
    target = _target(conn, req)
    if target and str(target["learner_id"]) != req.learner_id:
        raise _Stop(_reject(Reject.CONFLICT, "the target record belongs to another learner"))
    prev = _existing_change(conn, req)
    if prev:
        repl = None
        if prev["change"] == "SUPERSEDE":
            repl = conn.execute("""SELECT * FROM learner_record WHERE record_uid = %s""",
                                (prev["replacement_uid"],)).fetchone()
        if (repl and repl["origin_sender"] == req.sender
                and repl["source_record_id"] == req.source_record_id
                and repl["content_fingerprint"] == req.record_fingerprint):
            seq = _log_request(conn, req, Status.NO_OP, "same supersede already applied")
            raise _Stop(Outcome(Status.NO_OP, message="this correction was already applied",
                                request_seq=seq), commit=True)
        raise _Stop(_reject(Reject.CONFLICT, f"record was already {prev['change'].lower()}d "
                                             f"(request seq {prev['request_seq']}): correct the "
                                             f"current record instead"))
    seqs = []
    uid, concept_id, ticket = _insert_record(conn, req, directory, seqs)
    if uid is None:
        raise _Stop(_reject(Reject.CONFLICT, f"replacement record {req.source_record_id} "
                                             f"already exists"))
    seq = seqs[0]
    conn.execute(
        """INSERT INTO record_change (learner_id, target_sender, target_source_record_id, change,
                                      replacement_uid, reason, actor, request_seq)
           VALUES (%s, %s, %s, 'SUPERSEDE', %s, %s, %s, %s)""",
        (req.learner_id, req.target_sender, req.target_source_record_id, uid, req.reason,
         req.sender, seq))
    if target and str(target["effective_concept_id"] or "") != (concept_id or ""):
        _outbox(conn, req.learner_id, target["effective_concept_id"], seq)
    return Outcome(Status.APPLIED if concept_id else Status.PENDING_CONCEPT, request_seq=seq,
                   record_uid=uid, ticket_id=str(ticket["ticket_id"]) if ticket else None,
                   message="record superseded" + ("" if target else
                                                  "; the old record will arrive already superseded"))
