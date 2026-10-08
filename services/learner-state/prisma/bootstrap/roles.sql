-- Learner State database roles (architecture §9.3.1, App. C.2 rule 3).
--
-- Run ONCE per database by an administrator (locally: the container
-- superuser; on AWS: the RDS master user), never by the service and never
-- as a Prisma migration -- migrations run as ls_owner, which cannot create
-- roles. Passwords are psql variables so none is stored in the repo:
--
--   psql -v owner_password=... -v api_password=... -v ingest_password=... \
--        -f prisma/bootstrap/roles.sql
--
-- ls_owner   owns the tables; used only by `prisma migrate deploy`.
-- ls_api     read surface; subject to RLS.
-- ls_ingest  evidence pipeline.
-- None is a superuser and none has BYPASSRLS, so FORCEd RLS applies to all.

\set ON_ERROR_STOP on

CREATE ROLE ls_owner  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'owner_password';
CREATE ROLE ls_api    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'api_password';
CREATE ROLE ls_ingest LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'ingest_password';

-- Since Postgres 15, PUBLIC can no longer create objects in schema public.
GRANT USAGE, CREATE ON SCHEMA public TO ls_owner;
GRANT USAGE         ON SCHEMA public TO ls_api, ls_ingest;
