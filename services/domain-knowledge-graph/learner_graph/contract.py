"""The update request contract (SCRUM-92).

An envelope is {"body": {...}, "signature": "<base64 Ed25519 over canonical(body)>"}.

body, schema ali.learner-graph.update/v1:
  request_id   the sender's idempotency key, unique per sender
  sender       the component id (checked against the signature's key)
  learner_id   UUID
  operation    ADD_EVIDENCE | ADD_EXPOSURE | RETRACT | SUPERSEDE
  sent_at      transport time; ignored by duplicate detection
  concept      {"concept_id": UUID}                    canonical DKG id, or
               {"name": str, "context": str}           a concept the sender could not
                                                       resolve: waits for SCRUM-89/90
               (ADD_* and SUPERSEDE only)
  record       {"source_record_id", "occurred_at", "payload"}   (ADD_* and SUPERSEDE;
               SUPERSEDE also gives "kind": EVIDENCE | EXPOSURE)
  target       {"sender", "source_record_id"}          (RETRACT and SUPERSEDE)
  reason       why the record is corrected             (RETRACT and SUPERSEDE)

The component does not read payload: it is the sender's description of the evidence and
is stored and shown as given. Deciding what it means for the learner belongs to other
ALI components (SCRUM-92 ownership boundary).
"""
import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

SCHEMA = "ali.learner-graph.update/v1"

MAX_BODY_BYTES = 32_000
MAX_PAYLOAD_BYTES = 16_000
MAX_PAYLOAD_DEPTH = 6
MAX_FUTURE = timedelta(minutes=5)       # clock skew allowed on occurred_at

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SENDER = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class Operation(str, Enum):
    ADD_EVIDENCE = "ADD_EVIDENCE"
    ADD_EXPOSURE = "ADD_EXPOSURE"
    RETRACT = "RETRACT"
    SUPERSEDE = "SUPERSEDE"


KIND_OF = {Operation.ADD_EVIDENCE: "EVIDENCE", Operation.ADD_EXPOSURE: "EXPOSURE"}


class Status(str, Enum):
    APPLIED = "APPLIED"                  # in the log; the view will show it
    PENDING_CONCEPT = "PENDING_CONCEPT"  # in the log; waits for its concept (SCRUM-89/90)
    DUPLICATE = "DUPLICATE"              # same request resent: nothing new, original outcome
    NO_OP = "NO_OP"                      # new request, but nothing to change
    REJECTED = "REJECTED"


class Reject(str, Enum):
    INVALID = "INVALID"
    UNKNOWN_SENDER = "UNKNOWN_SENDER"
    BAD_SIGNATURE = "BAD_SIGNATURE"
    FORBIDDEN = "FORBIDDEN"
    UNKNOWN_CONCEPT = "UNKNOWN_CONCEPT"
    CONCEPT_REJECTED = "CONCEPT_REJECTED"
    CONFLICT = "CONFLICT"


@dataclass
class Outcome:
    status: Status
    code: Reject | None = None
    message: str = ""
    request_seq: int | None = None
    record_uid: str | None = None
    ticket_id: str | None = None
    original: dict | None = None        # for DUPLICATE: the first outcome

    def to_dict(self) -> dict:
        d = {"status": self.status.value, "message": self.message}
        for k in ("request_seq", "record_uid", "ticket_id", "original"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.code:
            d["code"] = self.code.value
        return d


class InvalidRequest(ValueError):
    pass


@dataclass
class Request:
    body: dict
    signature: bytes
    request_id: str
    sender: str
    learner_id: str
    operation: Operation
    concept_id: str | None = None
    concept_name: str | None = None
    concept_context: str = ""
    source_record_id: str | None = None
    occurred_at: datetime | None = None
    payload: dict | None = None
    kind: str | None = None
    target_sender: str | None = None
    target_source_record_id: str | None = None
    reason: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return request_fingerprint(self.body)

    @property
    def record_fingerprint(self) -> str:
        return record_fingerprint(self.learner_id, self.kind, self.occurred_at, self.payload)

    @property
    def concept_ref(self) -> str:
        return (f"id:{self.concept_id}" if self.concept_id
                else f"name:{name_key(self.concept_name or '')}")


# ---- canonical form and fingerprints --------------------------------------------------

def canonical(obj) -> bytes:
    """The exact bytes that are signed and hashed: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def request_fingerprint(body: dict) -> str:
    """Same request = same body apart from the transport time."""
    return sha256({k: v for k, v in body.items() if k != "sent_at"})


def record_fingerprint(learner_id, kind, occurred_at, payload) -> str:
    """The record's content without its concept: the concept is compared on its own,
    because the same concept may be named once by name and later by its resolved id."""
    return sha256({"learner_id": learner_id, "kind": kind,
                   "occurred_at": occurred_at.isoformat() if occurred_at else None,
                   "payload": payload})


def name_key(name: str) -> str:
    from validation.contract import normalize_name     # same rule as the SCRUM-90 gate
    return normalize_name(name)


# ---- parsing --------------------------------------------------------------------------

def _uuid(v, what) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise InvalidRequest(f"{what} must be a UUID")


def _text(v, what, limit, required=True) -> str:
    if v is None or v == "":
        if required:
            raise InvalidRequest(f"{what} is required")
        return ""
    if not isinstance(v, str):
        raise InvalidRequest(f"{what} must be a string")
    if len(v) > limit:
        raise InvalidRequest(f"{what} is longer than {limit} characters")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in v):
        raise InvalidRequest(f"{what} contains control characters")
    return v


def _ident(v, what, pattern=_ID) -> str:
    if not isinstance(v, str) or not pattern.match(v):
        raise InvalidRequest(f"{what} is not a valid id")
    return v


def _time(v, what, now) -> datetime:
    if not isinstance(v, str):
        raise InvalidRequest(f"{what} must be an ISO-8601 time")
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidRequest(f"{what} must be an ISO-8601 time")
    if t.tzinfo is None:
        raise InvalidRequest(f"{what} must include a time zone")
    if t > now + MAX_FUTURE:
        raise InvalidRequest(f"{what} is in the future")
    return t.astimezone(timezone.utc)


def _depth(obj, d=0) -> int:
    if isinstance(obj, dict):
        return max([_depth(v, d + 1) for v in obj.values()] or [d + 1])
    if isinstance(obj, list):
        return max([_depth(v, d + 1) for v in obj] or [d + 1])
    return d


def _payload(v) -> dict:
    if not isinstance(v, dict):
        raise InvalidRequest("record.payload must be a JSON object")
    if len(canonical(v)) > MAX_PAYLOAD_BYTES:
        raise InvalidRequest(f"record.payload is larger than {MAX_PAYLOAD_BYTES} bytes")
    if _depth(v) > MAX_PAYLOAD_DEPTH:
        raise InvalidRequest(f"record.payload is nested deeper than {MAX_PAYLOAD_DEPTH}")
    return v


_ALLOWED = {
    Operation.ADD_EVIDENCE: {"concept", "record"},
    Operation.ADD_EXPOSURE: {"concept", "record"},
    Operation.RETRACT: {"target", "reason"},
    Operation.SUPERSEDE: {"concept", "record", "target", "reason"},
}
_COMMON = {"schema", "request_id", "sender", "learner_id", "operation", "sent_at"}


def parse(envelope, now: datetime | None = None) -> Request:
    """Shape checks only. Who may do what is checked later (learner_graph/service.py)."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(envelope, dict) or set(envelope) != {"body", "signature"}:
        raise InvalidRequest("envelope must be {body, signature}")
    body, sig = envelope["body"], envelope["signature"]
    if not isinstance(body, dict):
        raise InvalidRequest("body must be a JSON object")
    try:
        size = len(canonical(body))
    except (TypeError, ValueError):
        raise InvalidRequest("body is not plain JSON")
    if size > MAX_BODY_BYTES:
        raise InvalidRequest(f"body is larger than {MAX_BODY_BYTES} bytes")
    try:
        signature = base64.b64decode(sig, validate=True)
    except Exception:
        raise InvalidRequest("signature must be base64")
    if body.get("schema") != SCHEMA:
        raise InvalidRequest(f"schema must be {SCHEMA}")
    try:
        op = Operation(body.get("operation"))
    except ValueError:
        raise InvalidRequest("operation must be one of " + ", ".join(o.value for o in Operation))
    extra = set(body) - _COMMON - _ALLOWED[op]
    if extra:
        raise InvalidRequest(f"unexpected fields for {op.value}: {', '.join(sorted(extra))}")

    r = Request(body=body, signature=signature,
                request_id=_ident(body.get("request_id"), "request_id"),
                sender=_ident(body.get("sender"), "sender", _SENDER),
                learner_id=_uuid(body.get("learner_id"), "learner_id"),
                operation=op, raw=envelope)
    if "sent_at" in body:
        _time(body["sent_at"], "sent_at", now + timedelta(days=1))

    if "concept" in _ALLOWED[op]:
        c = body.get("concept")
        if not isinstance(c, dict):
            raise InvalidRequest("concept is required")
        if set(c) == {"concept_id"}:
            r.concept_id = _uuid(c["concept_id"], "concept.concept_id")
        elif "name" in c and set(c) <= {"name", "context"}:
            r.concept_name = _text(c["name"], "concept.name", 200).strip()
            if not name_key(r.concept_name):
                raise InvalidRequest("concept.name is empty")
            r.concept_context = _text(c.get("context"), "concept.context", 1000, required=False)
        else:
            raise InvalidRequest("concept must be {concept_id} or {name, context}")

        rec = body.get("record")
        allowed = {"source_record_id", "occurred_at", "payload"} | (
            {"kind"} if op is Operation.SUPERSEDE else set())
        if not isinstance(rec, dict) or not set(rec) <= allowed:
            raise InvalidRequest("record must be {source_record_id, occurred_at, payload"
                                 + (", kind}" if op is Operation.SUPERSEDE else "}"))
        r.source_record_id = _ident(rec.get("source_record_id"), "record.source_record_id")
        r.occurred_at = _time(rec.get("occurred_at"), "record.occurred_at", now)
        r.payload = _payload(rec.get("payload"))
        if op is Operation.SUPERSEDE:
            if rec.get("kind") not in ("EVIDENCE", "EXPOSURE"):
                raise InvalidRequest("record.kind must be EVIDENCE or EXPOSURE")
            r.kind = rec["kind"]
        else:
            r.kind = KIND_OF[op]

    if "target" in _ALLOWED[op]:
        t = body.get("target")
        if not isinstance(t, dict) or set(t) != {"sender", "source_record_id"}:
            raise InvalidRequest("target must be {sender, source_record_id}")
        r.target_sender = _ident(t["sender"], "target.sender", _SENDER)
        r.target_source_record_id = _ident(t["source_record_id"], "target.source_record_id")
        r.reason = _text(body.get("reason"), "reason", 500)
        if (op is Operation.SUPERSEDE and r.target_sender == r.sender
                and r.target_source_record_id == r.source_record_id):
            raise InvalidRequest("a record cannot supersede itself")
    return r


def make_body(*, request_id, sender, learner_id, operation, concept=None, record=None,
              target=None, reason=None, sent_at=None) -> dict:
    """Helper for senders (and the demo/tests): build a body with the right fields."""
    b = {"schema": SCHEMA, "request_id": request_id, "sender": sender,
         "learner_id": str(learner_id), "operation": Operation(operation).value,
         "sent_at": sent_at or datetime.now(timezone.utc).isoformat()}
    for k, v in (("concept", concept), ("record", record), ("target", target),
                 ("reason", reason)):
        if v is not None:
            b[k] = v
    return b
