"""SCRUM-92 Learner Graph: incremental, idempotent updates of a learner's graph.

Postgres log (source of truth) -> outbox -> projector -> Neo4j view over the canonical
Domain Knowledge Graph. See schema.sql, contract.py, service.py and projector.py."""
