/**
 * Connection strings for the shared integration Postgres started by
 * global-setup.ts.
 */
import * as path from 'node:path';

export const SERVICE_ROOT = path.resolve(__dirname, '../../..');

export const LS_ROLES = ['ls_owner', 'ls_api', 'ls_ingest'] as const;
export type LsRole = (typeof LS_ROLES)[number];

export function urlEnvVar(role: LsRole): string {
  return `LS_TEST_${role.toUpperCase()}_URL`;
}

export function databaseUrl(role: LsRole): string {
  const url = process.env[urlEnvVar(role)];
  if (url === undefined) {
    throw new Error(`${urlEnvVar(role)} is not set; run via npm run test:integration`);
  }
  return url;
}
