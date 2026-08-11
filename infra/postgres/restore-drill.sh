#!/bin/sh
set -eu

project_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
backup_dir="${project_root}/.runtime/backups"
report_dir="${project_root}/.runtime/reports"
backup_file="${1:-}"

if [ -z "${backup_file}" ]; then
  backup_file="$(find "${backup_dir}" -maxdepth 1 -type f -name 'saas-core-*.dump' -print | sort | tail -n 1)"
fi
if [ -z "${backup_file}" ] || [ ! -f "${backup_file}" ]; then
  echo "Brak backupu do restore drill" >&2
  exit 1
fi
if [ ! -f "${backup_file}.sha256" ]; then
  echo "Brak pliku checksumy: ${backup_file}.sha256" >&2
  exit 1
fi

cd "${backup_dir}"
sha256sum --check "$(basename "${backup_file}.sha256")"
cd "${project_root}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
restore_db="saas_core_restore_$(date -u +%Y%m%d%H%M%S)_$$"
case "${restore_db}" in
  saas_core_restore_[0-9]*) ;;
  *) echo "Niebezpieczna nazwa bazy restore" >&2; exit 1 ;;
esac

started_at="$(date +%s)"
restored=0
cleanup() {
  if [ "${restored}" -eq 1 ]; then
    docker compose exec -T --env "RESTORE_DB=${restore_db}" postgres sh -c \
      'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; dropdb --if-exists --force --host 127.0.0.1 --username "$POSTGRES_USER" "$RESTORE_DB"' \
      >/dev/null
  fi
}
trap cleanup EXIT HUP INT TERM

docker compose exec -T --env "RESTORE_DB=${restore_db}" postgres sh -c \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; createdb --host 127.0.0.1 --username "$POSTGRES_USER" "$RESTORE_DB"'
restored=1

docker compose exec -T --env "RESTORE_DB=${restore_db}" postgres sh -c \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; pg_restore --exit-on-error --no-owner --host 127.0.0.1 --username "$POSTGRES_USER" --dbname "$RESTORE_DB"' \
  <"${backup_file}"

docker compose run --rm --no-deps --env "POSTGRES_DB=${restore_db}" backend \
  python manage.py migrate --noinput
docker compose run --rm --no-deps --env "POSTGRES_DB=${restore_db}" backend \
  python manage.py check

migration_count="$(docker compose exec -T --env "RESTORE_DB=${restore_db}" postgres sh -c \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; psql --host 127.0.0.1 --username "$POSTGRES_USER" --dbname "$RESTORE_DB" --tuples-only --no-align --command "SELECT count(*) FROM django_migrations"')"
case "${migration_count}" in
  ''|*[!0-9]*) echo "Kontrola integralności zwróciła niepoprawny wynik" >&2; exit 1 ;;
esac

duration="$(( $(date +%s) - started_at ))"
mkdir -p "${report_dir}"
umask 077
printf '{"backup":"%s","restore_database":"%s","migration_count":%s,"duration_seconds":%s,"checked_at":"%s","result":"ok"}\n' \
  "$(basename "${backup_file}")" "${restore_db}" "${migration_count}" "${duration}" "${timestamp}" \
  >"${report_dir}/restore-drill-${timestamp}.json"

cleanup
restored=0
trap - EXIT HUP INT TERM
printf 'Restore drill OK: %s migracji, %ss; baza izolowana została usunięta.\n' \
  "${migration_count}" "${duration}"
