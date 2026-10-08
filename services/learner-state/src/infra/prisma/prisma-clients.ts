import { PrismaClient } from '@prisma/client';

/**
 * The two runtime database roles (architecture §9.3.1, App. C.2 rule 3).
 * `ls_owner` is deliberately absent: only `prisma migrate` connects as it.
 */
export type RuntimeRole = 'ls_api' | 'ls_ingest';

const URL_ENV_VAR: Record<RuntimeRole, string> = {
  ls_api: 'LS_API_DATABASE_URL',
  ls_ingest: 'LS_INGEST_DATABASE_URL',
};

/** Reads the connection string for `role` from the environment. */
export function databaseUrlFor(role: RuntimeRole, env: NodeJS.ProcessEnv = process.env): string {
  const name = URL_ENV_VAR[role];
  const url = env[name];
  if (url === undefined || url === '') {
    throw new Error(`${name} is not set (connection string for ${role})`);
  }
  return url;
}

/**
 * One PrismaClient per role. The URL overrides `datasource.url` in
 * schema.prisma, which is the ls_owner connection used by migrations.
 */
export function createPrismaClient(datasourceUrl: string): PrismaClient {
  return new PrismaClient({ datasourceUrl });
}

interface RoleFacts {
  current_user: string;
  rolsuper: boolean;
  rolbypassrls: boolean;
  is_owner: boolean;
}

/**
 * Fails if `client` is connected as a role that would silently bypass RLS:
 * a superuser, a BYPASSRLS role, or ls_owner (or a member of it). Call
 * once at startup for each runtime client.
 */
export async function assertNonOwnerRole(client: PrismaClient, expected: RuntimeRole): Promise<void> {
  const rows = await client.$transaction(
    (tx) => tx.$queryRaw<RoleFacts[]>`
      SELECT current_user::text                                AS current_user,
             r.rolsuper,
             r.rolbypassrls,
             pg_has_role(current_user, 'ls_owner', 'MEMBER')   AS is_owner
      FROM pg_roles r
      WHERE r.rolname = current_user`,
    { timeout: 5_000 },
  );
  const facts = rows[0];
  if (facts === undefined) {
    throw new Error('Could not read the connected role from pg_roles');
  }
  if (facts.current_user !== expected) {
    throw new Error(`Connected as ${facts.current_user}, expected ${expected}`);
  }
  if (facts.rolsuper || facts.rolbypassrls || facts.is_owner) {
    throw new Error(
      `${facts.current_user} bypasses RLS (superuser=${facts.rolsuper}, ` +
        `bypassrls=${facts.rolbypassrls}, owner=${facts.is_owner})`,
    );
  }
}
