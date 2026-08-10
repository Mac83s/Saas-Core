#!/bin/sh
set -eu

project_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
backup_dir="${project_root}/.runtime/backups"
report_dir="${project_root}/.runtime/reports"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${backup_dir}/saas-core-${timestamp}.dump"
partial_file="${backup_file}.partial"
started_at="$(date +%s)"

mkdir -p "${backup_dir}" "${report_dir}"
umask 077

cleanup() {
  rm -f "${partial_file}"
}
trap cleanup EXIT HUP INT TERM

docker compose exec -T postgres sh -c \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_dump --host 127.0.0.1 --username saas_core --dbname saas_core --format custom' \
  >"${partial_file}"

test -s "${partial_file}"
mv "${partial_file}" "${backup_file}"
checksum="$(sha256sum "${backup_file}" | awk '{print $1}')"
printf '%s  %s\n' "${checksum}" "$(basename "${backup_file}")" >"${backup_file}.sha256"
duration="$(( $(date +%s) - started_at ))"
size="$(wc -c <"${backup_file}" | tr -d ' ')"

printf '{"backup":"%s","sha256":"%s","bytes":%s,"duration_seconds":%s,"created_at":"%s"}\n' \
  "$(basename "${backup_file}")" "${checksum}" "${size}" "${duration}" "${timestamp}" \
  >"${report_dir}/backup-${timestamp}.json"

trap - EXIT HUP INT TERM
printf 'Backup: %s\nSHA-256: %s\nCzas: %ss\n' "${backup_file}" "${checksum}" "${duration}"

