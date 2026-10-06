#!/bin/sh
# Restore drill of one stack: restores a dump into a scratch database beside the
# stack's own, compares the two and drops the scratch database. It never writes to
# an existing database and starts no application container.
#
#   restore-drill.sh [stack] [dump]    newest good dump of the stack when none is named
#
# The stack, its container and BACKUP_DIR are resolved as in backup.sh. The schema
# has to match the source exactly; row counts are compared with the source as it is
# now, so tables written since the dump may differ and are listed, not failed.
set -eu

project_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
stack="${1:-${BACKUP_STACK:-saas-core}}"
backup_file="${2:-}"
backup_dir="${BACKUP_DIR:-${project_root}/.runtime/backups}"
report_dir="${project_root}/.runtime/reports"

case "${stack}" in
  ''|*[!a-z0-9_-]*|-*) echo "restore drill: stack name must be a Compose project name, got '${stack}'" >&2; exit 64 ;;
esac

if [ -z "${backup_file}" ]; then
  for name in $(ls -1 "${backup_dir}" 2>/dev/null | grep -E "^${stack}-[0-9]{8}T[0-9]{6}Z\.dump$" | sort -r); do
    if [ -f "${backup_dir}/${name}.sha256" ]; then backup_file="${backup_dir}/${name}"; break; fi
  done
fi
if [ -z "${backup_file}" ] || [ ! -f "${backup_file}" ]; then
  echo "restore drill: no dump of ${stack} in ${backup_dir}" >&2
  exit 1
fi
if [ ! -f "${backup_file}.sha256" ]; then
  echo "restore drill: checksum file missing: ${backup_file}.sha256" >&2
  exit 1
fi
(cd "$(dirname -- "${backup_file}")" && sha256sum --check "$(basename -- "${backup_file}").sha256")

container="$(docker ps --quiet \
  --filter "label=com.docker.compose.project=${stack}" \
  --filter "label=com.docker.compose.service=postgres")"
case "${container}" in
  '') echo "restore drill: no running postgres container in Compose project '${stack}'" >&2; exit 69 ;;
  *[!0-9a-f]*) echo "restore drill: more than one postgres container in Compose project '${stack}'" >&2; exit 69 ;;
esac

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
restore_db="restore_drill_$(date -u +%Y%m%d%H%M%S)_$$"
work_dir="$(mktemp -d)"
started_at="$(date +%s)"
created=0

# Runs one client command inside the postgres container with the container's own
# credentials; "$RESTORE_DB" and "$POSTGRES_DB" resolve there.
in_postgres() {
  docker exec -i --env "RESTORE_DB=${restore_db}" "${container}" sh -c \
    'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" PGHOST=127.0.0.1 PGUSER="$POSTGRES_USER"; '"$1"
}

cleanup() {
  if [ "${created}" -eq 1 ]; then
    in_postgres 'dropdb --if-exists --force "$RESTORE_DB"' </dev/null >/dev/null
    created=0
  fi
  rm -rf "${work_dir}"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

# createdb refuses an existing name, so the drill cannot land on a database that
# was there before; only a database this run created is ever dropped.
in_postgres 'createdb "$RESTORE_DB"' </dev/null
created=1
in_postgres 'pg_restore --exit-on-error --no-owner --dbname "$RESTORE_DB"' <"${backup_file}"

schema_sql="SELECT 'tables=' || (SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema'))
  || ' indexes=' || (SELECT count(*) FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog', 'information_schema'))
  || ' constraints=' || (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema'))
  || ' sequences=' || (SELECT count(*) FROM pg_sequences)
  || ' triggers=' || (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal)
  || ' policies=' || (SELECT count(*) FROM pg_policies)
  || ' rls_forced=' || (SELECT count(*) FROM pg_class WHERE relforcerowsecurity)
  || ' migrations=' || (SELECT count(*) FROM django_migrations);"
rows_sql="SELECT format('SELECT %L, count(*) FROM %I.%I', schemaname || '.' || tablename, schemaname, tablename)
  FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1 \\gexec"

for side in source restored; do
  if [ "${side}" = source ]; then database='"$POSTGRES_DB"'; else database='"$RESTORE_DB"'; fi
  printf '%s\n' "${schema_sql}" |
    in_postgres "psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 --dbname ${database}" >"${work_dir}/${side}.schema"
  printf '%s\n' "${rows_sql}" |
    in_postgres "psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 --dbname ${database}" >"${work_dir}/${side}.rows"
done

schema="$(cat "${work_dir}/restored.schema")"
if ! cmp -s "${work_dir}/source.schema" "${work_dir}/restored.schema"; then
  echo "restore drill FAILED: the restored schema differs from the source" >&2
  echo "  source:   $(cat "${work_dir}/source.schema")" >&2
  echo "  restored: ${schema}" >&2
  exit 1
fi

tables="$(wc -l <"${work_dir}/restored.rows" | tr -d ' ')"
rows_source="$(awk -F'|' '{ total += $2 } END { print total + 0 }' "${work_dir}/source.rows")"
rows_restored="$(awk -F'|' '{ total += $2 } END { print total + 0 }' "${work_dir}/restored.rows")"
# Lines only one side has: a table whose count changed appears once per side.
differing="$(cat "${work_dir}/source.rows" "${work_dir}/restored.rows" | sort | uniq -u | cut -d'|' -f1 | sort -u)"
differing_count="$(printf '%s' "${differing}" | grep -c . || true)"
case "${tables}" in
  ''|0) echo "restore drill FAILED: no tables in the restored database" >&2; exit 1 ;;
esac
details=""
for table in ${differing}; do
  details="${details}  ${table}: $(awk -F'|' -v t="${table}" '$1 == t { print $2 }' "${work_dir}/source.rows") / $(awk -F'|' -v t="${table}" '$1 == t { print $2 }' "${work_dir}/restored.rows")
"
done

cleanup
duration="$(( $(date +%s) - started_at ))"
mkdir -p "${report_dir}"
umask 077
printf '{"stack":"%s","backup":"%s","restore_database":"%s","schema":"%s","tables":%s,"tables_with_other_row_count":%s,"rows_source_now":%s,"rows_restored":%s,"duration_seconds":%s,"checked_at":"%s","result":"ok"}\n' \
  "${stack}" "$(basename -- "${backup_file}")" "${restore_db}" "${schema}" "${tables}" "${differing_count}" \
  "${rows_source}" "${rows_restored}" "${duration}" "${timestamp}" \
  >"${report_dir}/restore-drill-${stack}-${timestamp}.json"

printf 'Restore drill OK %s: %s restored in %ss; schema identical (%s); rows %s restored, %s in the source now; %s of %s tables differ in row count; scratch database %s dropped.\n' \
  "${stack}" "$(basename -- "${backup_file}")" "${duration}" "${schema}" "${rows_restored}" "${rows_source}" \
  "${differing_count}" "${tables}" "${restore_db}"
if [ -n "${details}" ]; then
  printf 'Tables written since the dump (source now / restored):\n%s' "${details}"
fi
