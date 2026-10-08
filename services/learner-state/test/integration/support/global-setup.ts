/**
 * Starts ONE Postgres for the whole integration run (Jest globalSetup):
 * roles created, migrations applied as ls_owner. Suites read the
 * connection strings from the environment via databaseUrl().
 *
 * One container per run, not per suite: starting a second container in
 * the same Jest process hangs in Testcontainers' file copy.
 */
import { execFileSync } from 'node:child_process';
import * as path from 'node:path';
import { PostgreSqlContainer, StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { LS_ROLES, LsRole, SERVICE_ROOT, urlEnvVar } from './postgres';

// Test-only credentials for a throwaway container.
const PASSWORDS: Record<LsRole, string> = {
  ls_owner: 'owner_pw',
  ls_api: 'api_pw',
  ls_ingest: 'ingest_pw',
};

declare global {
  // eslint-disable-next-line no-var
  var __LS_POSTGRES__: StartedPostgreSqlContainer | undefined;
}

export default async function globalSetup(): Promise<void> {
  const container = await new PostgreSqlContainer('postgres:16-alpine')
    .withCopyFilesToContainer([
      {
        source: path.join(SERVICE_ROOT, 'prisma', 'bootstrap', 'roles.sql'),
        target: '/bootstrap/roles.sql',
      },
    ])
    .start();
  globalThis.__LS_POSTGRES__ = container;

  for (const role of LS_ROLES) {
    const url = new URL(container.getConnectionUri());
    url.username = role;
    url.password = PASSWORDS[role];
    process.env[urlEnvVar(role)] = url.toString();
  }

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

  execFileSync(path.join(SERVICE_ROOT, 'node_modules', '.bin', 'prisma'), ['migrate', 'deploy'], {
    cwd: SERVICE_ROOT,
    env: { ...process.env, LS_OWNER_DATABASE_URL: process.env[urlEnvVar('ls_owner')] },
    stdio: 'pipe',
  });
}
