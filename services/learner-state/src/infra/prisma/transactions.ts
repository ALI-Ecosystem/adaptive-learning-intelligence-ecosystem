import { Prisma, PrismaClient } from '@prisma/client';

/**
 * Transaction helpers for App. C.2 rules 1, 2 and 4. Every RLS-scoped read
 * and every evidence write goes through one of these, so the first
 * statements of the transaction are always right and always on the same
 * connection as the caller's own statements.
 */

export type Tx = Prisma.TransactionClient;
export type TxKind = 'read' | 'write';

/** Rule 4: explicit timeouts. Prisma's 5 s default is too short for a §6.5 re-fold. */
export const READ_TX_TIMEOUT_MS = 5_000;
export const WRITE_TX_TIMEOUT_MS = 30_000;

/**
 * Where timed-out transactions are counted. A timeout rolls back cleanly,
 * which is safe, but must be visible (App. C.2 rule 4). The concrete
 * exporter (Prometheus, CloudWatch, ...) waits on the compute decision
 * (SCRUM-87); until then InMemoryTransactionMetrics is enough.
 */
export interface TransactionMetrics {
  transactionTimedOut(kind: TxKind): void;
}

export class InMemoryTransactionMetrics implements TransactionMetrics {
  readonly timeouts: Record<TxKind, number> = { read: 0, write: 0 };

  transactionTimedOut(kind: TxKind): void {
    this.timeouts[kind] += 1;
  }
}

export interface TxContext {
  client: PrismaClient;
  metrics: TransactionMetrics;
  /** Overrides READ_TX_TIMEOUT_MS / WRITE_TX_TIMEOUT_MS. */
  timeoutMs?: number;
}

export interface EventClaim {
  evidenceEventId: string;
  learnerId: string;
}

export type EventWriteResult<T> = { status: 'APPLIED'; result: T } | { status: 'DUPLICATE' };

/**
 * Rule 2 (reads): the first statement scopes RLS to `learnerId`,
 * transaction-locally (`true`), so the value cannot leak to the next user
 * of the pooled connection (§9.3.1).
 */
export function withLearnerRead<T>(ctx: TxContext, learnerId: string, fn: (tx: Tx) => Promise<T>): Promise<T> {
  return run(ctx, 'read', READ_TX_TIMEOUT_MS, async (tx) => {
    await tx.$queryRaw`SELECT set_config('app.learner_id', ${learnerId}, true)`;
    return fn(tx);
  });
}

/**
 * Rule 2 (writes), §6.2: claim the event, then lock the learner, then run
 * `fn`. A duplicate claims 0 rows and returns DUPLICATE without running
 * `fn`. The claim stores outcome_digest = 'PENDING'; `fn` must set the real
 * digest before returning (decision #24).
 */
export function withEventWrite<T>(
  ctx: TxContext,
  claim: EventClaim,
  fn: (tx: Tx) => Promise<T>,
): Promise<EventWriteResult<T>> {
  return run(ctx, 'write', WRITE_TX_TIMEOUT_MS, async (tx): Promise<EventWriteResult<T>> => {
    const claimed = await tx.$queryRaw<{ evidence_event_id: string }[]>`
      INSERT INTO processed_event (evidence_event_id, learner_id, outcome_digest)
      VALUES (${claim.evidenceEventId}::uuid, ${claim.learnerId}::uuid, 'PENDING')
      ON CONFLICT (evidence_event_id) DO NOTHING
      RETURNING evidence_event_id::text`;
    if (claimed.length === 0) {
      return { status: 'DUPLICATE' };
    }
    // $executeRaw, not $queryRaw: Prisma cannot deserialise a `void` column.
    await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtextextended(${claim.learnerId}::text, 0))`;
    return { status: 'APPLIED', result: await fn(tx) };
  });
}

async function run<T>(ctx: TxContext, kind: TxKind, defaultTimeoutMs: number, body: (tx: Tx) => Promise<T>): Promise<T> {
  try {
    // Rule 1: interactive form only, so every statement shares one connection.
    return await ctx.client.$transaction(body, { timeout: ctx.timeoutMs ?? defaultTimeoutMs });
  } catch (err) {
    if (isTransactionTimeout(err)) {
      ctx.metrics.transactionTimedOut(kind);
    }
    throw err;
  }
}

/** Prisma reports an expired interactive transaction as P2028. */
function isTransactionTimeout(err: unknown): boolean {
  return (
    err instanceof Prisma.PrismaClientKnownRequestError &&
    err.code === 'P2028' &&
    /expired transaction/i.test(err.message)
  );
}
