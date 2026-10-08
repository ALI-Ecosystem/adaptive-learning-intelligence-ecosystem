/**
 * SCRUM-34: transaction helpers (App. C.2 rules 1, 2, 4; §6.2; §9.3.1).
 *
 * Run against real Postgres: "same connection" can only be shown by state
 * that is local to one transaction (set_config(..., true), an uncommitted
 * row, a transaction-scoped advisory lock).
 */
import { randomUUID } from 'node:crypto';
import { PrismaClient } from '@prisma/client';
import { createPrismaClient } from '../../src/infra/prisma/prisma-clients';
import {
  InMemoryTransactionMetrics,
  Tx,
  withEventWrite,
  withLearnerRead,
} from '../../src/infra/prisma/transactions';
import { databaseUrl } from './support/postgres';

// Test-only copy of the §5 processed_event DDL. The real migration is SCRUM-46.
const PROCESSED_EVENT_DDL = `
  CREATE TABLE processed_event (
    evidence_event_id UUID        PRIMARY KEY,
    learner_id        UUID        NOT NULL,
    processed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_digest    TEXT        NOT NULL,
    disposition       TEXT        NOT NULL DEFAULT 'APPLIED'
                      CHECK (disposition IN ('APPLIED','DEFERRED_LATE')),
    deferred_payload  BYTEA,
    CONSTRAINT deferred_has_payload
      CHECK ((disposition = 'DEFERRED_LATE') = (deferred_payload IS NOT NULL))
  )`;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function backendPid(tx: Tx): Promise<number> {
  const [row] = await tx.$queryRaw<{ pid: number }[]>`SELECT pg_backend_pid() AS pid`;
  return row!.pid;
}

async function learnerSetting(tx: Tx): Promise<string | null> {
  const [row] = await tx.$queryRaw<{ v: string | null }[]>`
    SELECT NULLIF(current_setting('app.learner_id', true), '') AS v`;
  return row!.v;
}

describe('transaction helpers', () => {
  let owner: PrismaClient;
  let api: PrismaClient;
  let ingest: PrismaClient;
  let metrics: InMemoryTransactionMetrics;

  beforeAll(async () => {
    owner = createPrismaClient(databaseUrl('ls_owner'));
    await owner.$transaction(
      async (tx) => {
        await tx.$executeRawUnsafe(PROCESSED_EVENT_DDL);
        await tx.$executeRawUnsafe('GRANT INSERT, UPDATE ON processed_event TO ls_ingest');
      },
      { timeout: 5_000 },
    );
    // One pooled connection each, so "the next transaction" reuses the same one.
    api = createPrismaClient(`${databaseUrl('ls_api')}?connection_limit=1`);
    ingest = createPrismaClient(`${databaseUrl('ls_ingest')}?connection_limit=1`);
  });

  beforeEach(() => {
    metrics = new InMemoryTransactionMetrics();
  });

  afterAll(async () => {
    await Promise.all([owner?.$disconnect(), api?.$disconnect(), ingest?.$disconnect()]);
  });

  async function storedEvent(id: string): Promise<{ outcome_digest: string } | undefined> {
    const rows = await owner.$transaction(
      (tx) => tx.$queryRaw<{ outcome_digest: string }[]>`
        SELECT outcome_digest FROM processed_event WHERE evidence_event_id = ${id}::uuid`,
      { timeout: 5_000 },
    );
    return rows[0];
  }

  describe('withLearnerRead', () => {
    it('sets app.learner_id on the same connection as the caller', async () => {
      const learnerId = randomUUID();
      const seen = await withLearnerRead({ client: api, metrics }, learnerId, learnerSetting);
      expect(seen).toBe(learnerId);
    });

    it('does not leak app.learner_id to the next transaction on that connection', async () => {
      const pidInside = await withLearnerRead({ client: api, metrics }, randomUUID(), backendPid);
      const after = await api.$transaction(
        async (tx) => ({ pid: await backendPid(tx), setting: await learnerSetting(tx) }),
        { timeout: 5_000 },
      );
      expect(after.pid).toBe(pidInside);
      expect(after.setting).toBeNull();
    });
  });

  describe('withEventWrite', () => {
    it('claims the event and takes the learner lock on the same connection as the caller', async () => {
      const claim = { evidenceEventId: randomUUID(), learnerId: randomUUID() };

      const outcome = await withEventWrite({ client: ingest, metrics }, claim, async (tx) => {
        // Only visible here if the claim ran in this transaction.
        const [row] = await tx.$queryRaw<{ outcome_digest: string }[]>`
          SELECT outcome_digest FROM processed_event
          WHERE evidence_event_id = ${claim.evidenceEventId}::uuid`;
        // Held by this backend only if the lock ran on this connection.
        const [lock] = await tx.$queryRaw<{ held: boolean }[]>`
          SELECT EXISTS (
            SELECT 1 FROM pg_locks
            WHERE locktype = 'advisory' AND granted AND pid = pg_backend_pid()
          ) AS held`;
        await tx.$executeRaw`
          UPDATE processed_event SET outcome_digest = 'digest-1'
          WHERE evidence_event_id = ${claim.evidenceEventId}::uuid`;
        return { digestDuringTx: row?.outcome_digest, lockHeld: lock?.held };
      });

      expect(outcome).toEqual({ status: 'APPLIED', result: { digestDuringTx: 'PENDING', lockHeld: true } });
      expect(await storedEvent(claim.evidenceEventId)).toEqual({ outcome_digest: 'digest-1' });
    });

    it('releases the advisory lock on commit', async () => {
      const claim = { evidenceEventId: randomUUID(), learnerId: randomUUID() };
      await withEventWrite({ client: ingest, metrics }, claim, async () => undefined);

      const [lock] = await ingest.$transaction(
        (tx) => tx.$queryRaw<{ held: boolean }[]>`
          SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory') AS held`,
        { timeout: 5_000 },
      );
      expect(lock?.held).toBe(false);
    });

    it('returns DUPLICATE for an already-processed event and does not run fn', async () => {
      const claim = { evidenceEventId: randomUUID(), learnerId: randomUUID() };
      await withEventWrite({ client: ingest, metrics }, claim, async () => 'first');

      const fn = jest.fn(async () => 'second');
      await expect(withEventWrite({ client: ingest, metrics }, claim, fn)).resolves.toEqual({ status: 'DUPLICATE' });
      expect(fn).not.toHaveBeenCalled();
    });

    it('rolls the claim back when fn throws, so the event can be retried', async () => {
      const claim = { evidenceEventId: randomUUID(), learnerId: randomUUID() };
      await expect(
        withEventWrite({ client: ingest, metrics }, claim, async () => {
          throw new Error('boom');
        }),
      ).rejects.toThrow('boom');
      expect(await storedEvent(claim.evidenceEventId)).toBeUndefined();

      await expect(withEventWrite({ client: ingest, metrics }, claim, async () => 'retried')).resolves.toEqual({
        status: 'APPLIED',
        result: 'retried',
      });
    });
  });

  describe('timeouts', () => {
    it('counts a timed-out write and rolls it back', async () => {
      const claim = { evidenceEventId: randomUUID(), learnerId: randomUUID() };
      await expect(
        withEventWrite({ client: ingest, metrics, timeoutMs: 200 }, claim, async (tx) => {
          await sleep(400);
          await tx.$queryRaw`SELECT 1`;
        }),
      ).rejects.toMatchObject({ code: 'P2028' });

      expect(metrics.timeouts).toEqual({ read: 0, write: 1 });
      expect(await storedEvent(claim.evidenceEventId)).toBeUndefined();
    });

    it('counts a timed-out read', async () => {
      await expect(
        withLearnerRead({ client: api, metrics, timeoutMs: 200 }, randomUUID(), async () => {
          await sleep(400);
        }),
      ).rejects.toMatchObject({ code: 'P2028' });

      expect(metrics.timeouts).toEqual({ read: 1, write: 0 });
    });

    it('does not count an ordinary failure as a timeout', async () => {
      await expect(
        withLearnerRead({ client: api, metrics }, randomUUID(), async () => {
          throw new Error('not a timeout');
        }),
      ).rejects.toThrow('not a timeout');

      expect(metrics.timeouts).toEqual({ read: 0, write: 0 });
    });
  });
});
