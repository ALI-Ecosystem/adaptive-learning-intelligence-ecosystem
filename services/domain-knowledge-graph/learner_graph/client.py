"""What another ALI component would use to build signed update requests (demo and tests).

    ev = SenderClient("evidence-module", key)
    envelope = ev.add_evidence(learner, concept_id=..., source_record_id="att-17",
                               occurred_at="2026-10-19T10:00:00+00:00",
                               payload={"item": "q3", "outcome": "CORRECT"})
"""
import uuid

from . import signing
from .contract import make_body


class SenderClient:
    def __init__(self, sender_id: str, key=None):
        self.sender_id = sender_id
        self.key = key or signing.new_key()

    @property
    def public_key(self) -> bytes:
        return signing.public_bytes(self.key)

    def _concept(self, concept_id=None, name=None, context=None):
        if concept_id:
            return {"concept_id": str(concept_id)}
        c = {"name": name}
        if context:
            c["context"] = context
        return c

    def envelope(self, **body_fields) -> dict:
        body_fields.setdefault("request_id", "req-" + uuid.uuid4().hex[:16])
        return signing.sign(make_body(sender=self.sender_id, **body_fields), self.key)

    def _add(self, op, learner_id, source_record_id, occurred_at, payload, concept_id=None,
             name=None, context=None, request_id=None):
        return self.envelope(
            request_id=request_id or "req-" + uuid.uuid4().hex[:16], learner_id=learner_id,
            operation=op, concept=self._concept(concept_id, name, context),
            record={"source_record_id": source_record_id, "occurred_at": occurred_at,
                    "payload": payload})

    def add_evidence(self, learner_id, **kw):
        return self._add("ADD_EVIDENCE", learner_id, **kw)

    def add_exposure(self, learner_id, **kw):
        return self._add("ADD_EXPOSURE", learner_id, **kw)

    def retract(self, learner_id, target_sender, target_source_record_id, reason,
                request_id=None):
        return self.envelope(
            request_id=request_id or "req-" + uuid.uuid4().hex[:16], learner_id=learner_id,
            operation="RETRACT", reason=reason,
            target={"sender": target_sender, "source_record_id": target_source_record_id})

    def supersede(self, learner_id, target_sender, target_source_record_id, reason, *,
                  source_record_id, occurred_at, payload, kind="EVIDENCE", concept_id=None,
                  name=None, context=None, request_id=None):
        return self.envelope(
            request_id=request_id or "req-" + uuid.uuid4().hex[:16], learner_id=learner_id,
            operation="SUPERSEDE", reason=reason,
            target={"sender": target_sender, "source_record_id": target_source_record_id},
            concept=self._concept(concept_id, name, context),
            record={"source_record_id": source_record_id, "occurred_at": occurred_at,
                    "payload": payload, "kind": kind})
