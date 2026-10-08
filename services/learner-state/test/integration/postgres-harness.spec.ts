/**
 * SCRUM-33: Postgres harness (architecture #23, §9.3.1, App. C.2).
 *
 * Starts a real Postgres, creates the three roles, runs
 * `prisma migrate deploy` as ls_owner, then checks that both runtime
 * clients connect as non-owner roles and that NUMERIC comes back as
 * Prisma.Decimal.
 */
import { execFileSync } from 'node:child_process';
import * as path from 'node:path';
import { Prisma, PrismaClient } from '@prisma/client';
import { PostgreSqlContainer, StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { assertNonOwnerRole, createPrismaClient } from '../../src/infra/prisma/prisma-clients';

const SERVICE_ROOT = path.resolve(__dirname, '../..');
const PRISMA_BIN = path.join(SERVICE_ROOT, 'node_modules', '.bin', 'prisma');

// Test-only credentials for a throwaway container.
const PASSWORDS = {
  ls_owner: 'owner_pw',
  ls_api: 'api_pw',
  ls_ingest: 'ingest_pw',
} as const;

function urlFor(container: StartedPostgreSqlContainer, role: keyof typeof PASSWORDS): string {
  const url = new URL(container.getConnectionUri());
  url.username = role;
  url.password = PASSWORDS[role];
  return url.toString();
}

describe('Postgres harness', () => {
  let container: StartedPostgreSqlContainer;
  let owner: PrismaClient;
  let api: PrismaClient;
  let ingest: PrismaClient;

  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:16-alpine')
      .withCopyFilesToContainer([
        {
          source: path.join(SERVICE_ROOT, 'prisma', 'bootstrap', 'roles.sql'),
          target: '/bootstrap/roles.sql',
        },
      ])
      .start();

    const bootstrap = await container.exec([
      'psql',
      '-U', container.getUsername(),
      '-d', container.getDatabase(),
      '-v', `owner_password=${PASSWORDS.ls_owner}`,
      '-v', `api_password=${PASSWORDS.ls_api}`,
      '-v', `ingest_password=${PASSWORDS.ls_ingest}`,
      '-f', '/bootstrap/roles.sql',
    ]);
    if (bootstrap.exitCode !== 0) {
      throw new Error(`roles.sql failed:\n${bootstrap.output}`);
    }

    execFileSync(PRISMA_BIN, ['migrate', 'deploy'], {
      cwd: SERVICE_ROOT,
      env: { ...process.env, LS_OWNER_DATABASE_URL: urlFor(container, 'ls_owner') },
      stdio: 'pipe',
    });

    owner = createPrismaClient(urlFor(container, 'ls_owner'));
    api = createPrismaClient(urlFor(container, 'ls_api'));
    ingest = createPrismaClient(urlFor(container, 'ls_ingest'));
  });

  afterAll(async () => {
    await Promise.all([owner?.$disconnect(), api?.$disconnect(), ingest?.$disconnect()]);
    await container?.stop();
  });

  it('runs Postgres 14 or newer', async () => {
    const [row] = await owner.$transaction(
      (tx) => tx.$queryRaw<{ v: number }[]>`SELECT current_setting('server_version_num')::int AS v`,
      { timeout: 5_000 },
    );
    expect(row?.v).toBeGreaterThanOrEqual(140000);
  });

  it('applied every migration, as ls_owner', async () => {
    const rows = await owner.$transaction(
      (tx) => tx.$queryRaw<{ migration_name: string; finished: boolean; table_owner: string }[]>`
        SELECT m.migration_name,
               m.finished_at IS NOT NULL AS finished,
               (SELECT tableowner::text FROM pg_tables WHERE tablename = '_prisma_migrations') AS table_owner
        FROM _prisma_migrations m
        ORDER BY m.migration_name`,
      { timeout: 5_000 },
    );
    expect(rows).toEqual([
      { migration_name: '20261008000000_roles_baseline', finished: true, table_owner: 'ls_owner' },
    ]);
  });

  it('connects the read client as ls_api, a non-owner role', async () => {
    await expect(assertNonOwnerRole(api, 'ls_api')).resolves.toBeUndefined();
  });

  it('connects the ingest client as ls_ingest, a non-owner role', async () => {
    await expect(assertNonOwnerRole(ingest, 'ls_ingest')).resolves.toBeUndefined();
  });

  it('rejects a client connected as ls_owner', async () => {
    await expect(assertNonOwnerRole(owner, 'ls_api')).rejects.toThrow(/ls_owner/);
  });

  it('returns NUMERIC from $queryRaw as Prisma.Decimal, never number', async () => {
    // 2^53 + 1 with 6 decimals: a float64 cannot hold this exactly.
    const [row] = await api.$transaction(
      (tx) => tx.$queryRaw<{ small: unknown; big: unknown }[]>`
        SELECT 0.123456::numeric(10, 6)                 AS small,
               9007199254740993.000001::numeric(22, 6)  AS big`,
      { timeout: 5_000 },
    );
    expect(row).toBeDefined();
    const { small, big } = row!;

    expect(typeof small).not.toBe('number');
    expect(small).toBeInstanceOf(Prisma.Decimal);
    expect((small as Prisma.Decimal).toFixed(6)).toBe('0.123456');

    expect(typeof big).not.toBe('number');
    expect(big).toBeInstanceOf(Prisma.Decimal);
    expect((big as Prisma.Decimal).toFixed(6)).toBe('9007199254740993.000001');
  });
});
