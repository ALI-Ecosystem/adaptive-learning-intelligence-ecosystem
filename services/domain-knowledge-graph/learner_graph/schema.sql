-- SCRUM-92 Learner Graph: the source of truth (decision 2026-10-19, option C).
--
-- Postgres holds an append-only log of every update request and every learner record.
-- Neo4j holds only a view of it (learner_graph/projector.py) that can be dropped and
-- rebuilt from these tables at any time. Nothing writes the view except the projector.
--
-- Append-only: rows of update_request, learner_record, record_change, request_audit and
-- concept_ticket_event are never updated or deleted by the service. The only mutable
-- columns are operational: concept_ticket.state (its history is in concept_ticket_event)
-- and outbox.projected_at.

CREATE SCHEMA IF NOT EXISTS learner_graph;
SET search_path = learner_graph;

-- Components allowed to send requests. A request must be signed with the private key that
-- matches public_key (Ed25519). operations lists what the sender may ask for;
-- can_correct_others lets it retract or supersede records another sender wrote
-- (decision 2026-10-19, option B: the original sender + a closed list).
CREATE TABLE IF NOT EXISTS sender (
    sender_id          text PRIMARY KEY CHECK (sender_id ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
    public_key         bytea NOT NULL CHECK (length(public_key) = 32),
    operations         text[] NOT NULL,
    can_correct_others boolean NOT NULL DEFAULT false,
    active             boolean NOT NULL DEFAULT true,
    registered_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Every request that was accepted into the log (applied, pending a concept, or a no-op).
-- (sender_id, request_id) is the idempotency key: a resend with the same content gets the
-- stored outcome back; a resend with different content is rejected as a conflict.
CREATE TABLE IF NOT EXISTS update_request (
    seq          bigserial PRIMARY KEY,
    sender_id    text NOT NULL REFERENCES sender,
    request_id   text NOT NULL,
    learner_id   uuid NOT NULL,
    operation    text NOT NULL CHECK (operation IN
                     ('ADD_EVIDENCE', 'ADD_EXPOSURE', 'RETRACT', 'SUPERSEDE')),
    fingerprint  text NOT NULL,          -- sha256 of the canonical body without sent_at
    body         jsonb NOT NULL,         -- the signed body, as received
    signature    bytea NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    outcome      text NOT NULL CHECK (outcome IN ('APPLIED', 'PENDING_CONCEPT', 'NO_OP')),
    detail       text NOT NULL DEFAULT '',
    UNIQUE (sender_id, request_id)
);
CREATE INDEX IF NOT EXISTS update_request_learner ON update_request (learner_id, seq);

-- Every attempt, including rejected ones and resends: who tried what, and what happened.
-- sender_claimed is what the request said; it is only trustworthy when outcome is not
-- UNKNOWN_SENDER / BAD_SIGNATURE.
CREATE TABLE IF NOT EXISTS request_audit (
    id              bigserial PRIMARY KEY,
    received_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    sender_claimed  text,
    request_id      text,
    learner_id      text,
    operation       text,
    outcome         text NOT NULL,
    reason          text NOT NULL DEFAULT '',
    fingerprint     text,
    request_seq     bigint REFERENCES update_request
);

-- A concept that is not in the Domain Knowledge Graph yet (decision 2026-10-19, option B).
-- One ticket per normalised name: two requests naming the same new concept wait on one
-- SCRUM-89 placement + SCRUM-90 gate run, never two.
--   WAITING   not sent yet        PROPOSED  ProposedConcept exists, gate/teacher pending
--   RESOLVED  concept_id is known REJECTED  the concept was not accepted
CREATE TABLE IF NOT EXISTS concept_ticket (
    ticket_id    uuid PRIMARY KEY,
    name_key     text NOT NULL UNIQUE,
    name         text NOT NULL,
    context      text NOT NULL DEFAULT '',
    state        text NOT NULL CHECK (state IN ('WAITING', 'PROPOSED', 'RESOLVED', 'REJECTED')),
    proposal_id  text,
    concept_id   uuid,
    created_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((state = 'RESOLVED') = (concept_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS concept_ticket_event (
    id         bigserial PRIMARY KEY,
    ticket_id  uuid NOT NULL REFERENCES concept_ticket,
    state      text NOT NULL,
    detail     jsonb NOT NULL DEFAULT '{}',
    at         timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- One piece of learner evidence or exposure, exactly as the sender described it.
-- payload is opaque here: stored and shown, never interpreted (no mastery, no diagnosis).
-- (origin_sender, source_record_id) is the record's natural key: the same record arriving
-- in a second request is a no-op if its content is the same, a conflict if not.
CREATE TABLE IF NOT EXISTS learner_record (
    record_uid          uuid PRIMARY KEY,
    learner_id          uuid NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('EVIDENCE', 'EXPOSURE')),
    concept_id          uuid,                         -- canonical DKG concept_id ...
    ticket_id           uuid REFERENCES concept_ticket, -- ... or the ticket it waits on
    origin_sender       text NOT NULL REFERENCES sender,
    source_record_id    text NOT NULL,
    payload             jsonb NOT NULL,
    occurred_at         timestamptz NOT NULL,
    recorded_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    request_seq         bigint NOT NULL REFERENCES update_request,
    content_fingerprint text NOT NULL,
    CHECK (concept_id IS NOT NULL OR ticket_id IS NOT NULL),
    UNIQUE (origin_sender, source_record_id)
);
CREATE INDEX IF NOT EXISTS learner_record_learner ON learner_record (learner_id, concept_id);
CREATE INDEX IF NOT EXISTS learner_record_ticket ON learner_record (ticket_id);

-- A correction. It names its target by natural key, so it can arrive before the target
-- (the target then enters already corrected). At most one correction per record:
-- retracting a retracted record is a no-op, any other second correction a conflict.
CREATE TABLE IF NOT EXISTS record_change (
    change_id                bigserial PRIMARY KEY,
    learner_id               uuid NOT NULL,
    target_sender            text NOT NULL,
    target_source_record_id  text NOT NULL,
    change                   text NOT NULL CHECK (change IN ('RETRACT', 'SUPERSEDE')),
    replacement_uid          uuid REFERENCES learner_record,
    reason                   text NOT NULL,
    actor                    text NOT NULL REFERENCES sender,
    request_seq              bigint NOT NULL REFERENCES update_request,
    at                       timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((change = 'SUPERSEDE') = (replacement_uid IS NOT NULL)),
    UNIQUE (target_sender, target_source_record_id)
);

-- Transactional outbox: written in the same transaction as the change it announces. The
-- projector re-syncs exactly one (learner, concept) part of the view per row.
CREATE TABLE IF NOT EXISTS outbox (
    seq           bigserial PRIMARY KEY,
    learner_id    uuid NOT NULL,
    concept_id    uuid NOT NULL,
    request_seq   bigint REFERENCES update_request,
    created_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    projected_at  timestamptz
);
CREATE INDEX IF NOT EXISTS outbox_todo ON outbox (seq) WHERE projected_at IS NULL;

-- Records with their current validity, the one query everything else reads.
CREATE OR REPLACE VIEW record_state AS
SELECT r.*,
       COALESCE(r.concept_id, t.concept_id) AS effective_concept_id,
       t.state                              AS ticket_state,
       c.change                             AS changed_by,
       c.reason                             AS change_reason,
       c.actor                              AS change_actor,
       c.at                                 AS changed_at,
       c.replacement_uid,
       (c.change_id IS NULL)                AS valid
FROM learner_record r
LEFT JOIN concept_ticket t ON t.ticket_id = r.ticket_id
LEFT JOIN record_change c ON c.target_sender = r.origin_sender
                         AND c.target_source_record_id = r.source_record_id
                         AND c.learner_id = r.learner_id;
