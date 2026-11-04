#!/bin/sh
set -eu

: "${DB_PASSWORD:?Set DB_PASSWORD for the PostgreSQL bootstrap administrator}"
: "${ABACUS_APP_PASSWORD:?Set ABACUS_APP_PASSWORD for the runtime database role}"

export PGPASSWORD="${DB_PASSWORD}"

psql --no-psqlrc --set=ON_ERROR_STOP=1 \
  --username=abacus --dbname=abacus \
  --set=app_password="${ABACUS_APP_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE abacus_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'abacus_app')
\gexec

ALTER ROLE abacus_app WITH LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT CONNECT ON DATABASE abacus TO abacus_app;
ALTER SCHEMA public OWNER TO abacus_app;
GRANT USAGE, CREATE ON SCHEMA public TO abacus_app;

DO $$
DECLARE
  object_record record;
BEGIN
  FOR object_record IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tableowner <> 'abacus_app'
  LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO abacus_app', object_record.tablename);
  END LOOP;

  FOR object_record IN
    SELECT c.relname AS sequence_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'S'
  LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO abacus_app', object_record.sequence_name);
  END LOOP;
END
$$;
SQL
