-- Runs as ls_owner. Every table ls_owner creates from here on is readable
-- by both runtime roles; RLS policies (P4) then decide which rows.
--
-- Write privileges are deliberately NOT defaulted: each table's migration
-- grants exactly what ls_ingest needs (e.g. INSERT only on the append-only
-- state_transition), so a blanket UPDATE/DELETE can never leak in.

ALTER DEFAULT PRIVILEGES FOR ROLE ls_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO ls_api, ls_ingest;
