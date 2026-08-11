#!/bin/sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB jest wymagany}"
: "${POSTGRES_HOST:?POSTGRES_HOST jest wymagany}"
: "${POSTGRES_PORT:?POSTGRES_PORT jest wymagany}"
: "${POSTGRES_USER:?POSTGRES_USER jest wymagany}"
: "${POSTGRES_PASSWORD_FILE:?POSTGRES_PASSWORD_FILE jest wymagany}"
: "${POSTGRES_APP_USER:?POSTGRES_APP_USER jest wymagany}"
: "${POSTGRES_APP_PASSWORD_FILE:?POSTGRES_APP_PASSWORD_FILE jest wymagany}"

if [ ! -s "${POSTGRES_PASSWORD_FILE}" ] || [ ! -s "${POSTGRES_APP_PASSWORD_FILE}" ]; then
  echo "Brak niepustego sekretu PostgreSQL" >&2
  exit 1
fi

export PGPASSWORD
PGPASSWORD="$(cat "${POSTGRES_PASSWORD_FILE}")"
export SAAS_CORE_APP_DATABASE_PASSWORD
SAAS_CORE_APP_DATABASE_PASSWORD="$(cat "${POSTGRES_APP_PASSWORD_FILE}")"

psql \
  --no-psqlrc \
  --quiet \
  --set=ON_ERROR_STOP=1 \
  --set=app_role="${POSTGRES_APP_USER}" \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" <<'SQL'
\getenv app_password SAAS_CORE_APP_DATABASE_PASSWORD

SELECT format('CREATE ROLE %I', :'app_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

SELECT format(
  'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'app_role',
  :'app_password'
)
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_role')
\gexec
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_role";

SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  AS app_role_is_safe
FROM pg_roles
WHERE rolname = :'app_role'
\gset
\if :app_role_is_safe
\else
  \echo 'Rola aplikacyjna PostgreSQL ma niedozwolone atrybuty' >&2
  \quit 1
\endif
SQL

unset PGPASSWORD SAAS_CORE_APP_DATABASE_PASSWORD
printf 'Rola aplikacyjna PostgreSQL %s jest gotowa.\n' "${POSTGRES_APP_USER}"
