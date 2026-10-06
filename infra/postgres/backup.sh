#!/bin/sh
# Logical backup of one stack's PostgreSQL database: dump, rotation, freshness check.
#
#   backup.sh [run] [stack]    dump the database, read the archive back, rotate old dumps
#   backup.sh check [stack]    age of the newest good dump; exit 1 when it is older than
#                              BACKUP_MAX_AGE_HOURS, 2 when there is none
#   backup.sh rotate [stack]   apply the retention alone and print how many dumps it removed
#
# A stack is a Compose project name (saas-core, hoofcare, medplano). The script finds
# that project's `postgres` container by its Compose labels and runs the PostgreSQL
# clients inside it: the client always matches the server's major version, and the
# credentials are the ones the container already holds (POSTGRES_USER, POSTGRES_DB,
# POSTGRES_PASSWORD_FILE) — nothing secret is read, written or passed on the host.
# One checkout therefore serves every stack on the host.
#
# It is meant for the host's cron, not for the stack's scheduler: beat runs at a
# 256 MB limit and a second process beside it is killed (docs/operations/backup-restore.md).
#
# Environment (all optional):
#   BACKUP_STACK          stack when no argument names one (saas-core)
#   BACKUP_DIR            host directory of the dumps, outside the containers' volumes
#                         (<checkout>/.runtime/backups)
#   BACKUP_KEEP_DAYS      newest days whose dumps are all kept (7)
#   BACKUP_KEEP_WEEKS     newest ISO weeks whose last dump is kept (4)
#   BACKUP_MAX_AGE_HOURS  freshness limit of `check` (26: a daily run plus slack)
set -eu

project_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

action="run"
case "${1:-}" in
  run|check|rotate) action="$1"; shift ;;
esac
stack="${1:-${BACKUP_STACK:-saas-core}}"
backup_dir="${BACKUP_DIR:-${project_root}/.runtime/backups}"
keep_days="${BACKUP_KEEP_DAYS:-7}"
keep_weeks="${BACKUP_KEEP_WEEKS:-4}"
max_age_hours="${BACKUP_MAX_AGE_HOURS:-26}"

case "${stack}" in
  ''|*[!a-z0-9_-]*|-*) echo "backup: stack name must be a Compose project name, got '${stack}'" >&2; exit 64 ;;
esac
for number in "${keep_days}" "${keep_weeks}" "${max_age_hours}"; do
  case "${number}" in
    ''|*[!0-9]*) echo "backup: BACKUP_KEEP_DAYS, BACKUP_KEEP_WEEKS and BACKUP_MAX_AGE_HOURS must be whole numbers" >&2; exit 64 ;;
  esac
done

# Finished dumps of this stack, newest first. The name carries the UTC time the dump
# started, so sorting names sorts by age; `.partial` files never match.
list_dumps() {
  [ -d "${backup_dir}" ] || return 0
  ls -1 "${backup_dir}" | grep -E "^${stack}-[0-9]{8}T[0-9]{6}Z\.dump$" | sort -r || true
}

# A dump is good when its checksum file exists and still matches: the checksum is
# written from the verified archive just before the dump takes its final name.
is_good() {
  [ -s "${backup_dir}/$1" ] && [ -f "${backup_dir}/$1.sha256" ] &&
    (cd "${backup_dir}" && sha256sum --check --status "$1.sha256")
}

check() {
  newest=""
  for name in $(list_dumps); do
    if is_good "${name}"; then newest="${name}"; break; fi
    echo "backup: skipped ${name} (checksum missing or wrong)" >&2
  done
  if [ -z "${newest}" ]; then
    echo "MISSING ${stack}: no good dump in ${backup_dir}"
    exit 2
  fi
  stamp="${newest#"${stack}"-}"
  stamp="${stamp%.dump}"
  day="${stamp%%T*}"
  clock="${stamp#*T}"
  clock="${clock%Z}"
  taken="$(date -u -d "${day} $(printf '%s' "${clock}" | sed 's/\(..\)\(..\)\(..\)/\1:\2:\3/')" +%s)"
  age_minutes="$(( ($(date -u +%s) - taken) / 60 ))"
  size="$(wc -c <"${backup_dir}/${newest}" | tr -d ' ')"
  count="$(list_dumps | wc -l | tr -d ' ')"
  summary="${stack}: newest good dump ${newest}, $(( age_minutes / 60 )) h $(( age_minutes % 60 )) min old (limit ${max_age_hours} h), ${size} bytes; ${count} kept in ${backup_dir}"
  if [ "${age_minutes}" -ge "$(( max_age_hours * 60 ))" ]; then
    echo "STALE ${summary}"
    exit 1
  fi
  echo "OK ${summary}"
}

# Keeps every dump of the newest BACKUP_KEEP_DAYS days that have one and, beyond
# them, the last dump of each of the newest BACKUP_KEEP_WEEKS ISO weeks. Days and
# weeks are counted among existing dumps, so a host that was down for a week does
# not lose its history to the calendar.
rotate() {
  days=""
  weeks=""
  day_count=0
  week_count=0
  removed=0
  for name in $(list_dumps); do
    day="${name#"${stack}"-}"
    day="${day%%T*}"
    week="$(date -u -d "${day}" +%G%V)"
    keep=0
    case " ${days} " in
      *" ${day} "*) keep=1 ;;
      *) if [ "${day_count}" -lt "${keep_days}" ]; then days="${days} ${day}"; day_count=$(( day_count + 1 )); keep=1; fi ;;
    esac
    case " ${weeks} " in
      *" ${week} "*) ;;
      *) if [ "${week_count}" -lt "${keep_weeks}" ]; then weeks="${weeks} ${week}"; week_count=$(( week_count + 1 )); keep=1; fi ;;
    esac
    if [ "${keep}" -eq 0 ]; then
      rm -f "${backup_dir}/${name}" "${backup_dir}/${name}.sha256"
      removed=$(( removed + 1 ))
    fi
  done
  echo "${removed}"
}

run() {
  # Dumps hold personal data: nothing here is readable by another user.
  umask 077
  mkdir -p "${backup_dir}"

  # One run per stack at a time; the lock dies with the process, so a killed run
  # never blocks the next one.
  exec 9>"${backup_dir}/.${stack}.lock"
  if ! flock --nonblock 9; then
    echo "backup: another backup of ${stack} is running" >&2
    exit 75
  fi

  container="$(docker ps --quiet \
    --filter "label=com.docker.compose.project=${stack}" \
    --filter "label=com.docker.compose.service=postgres")"
  case "${container}" in
    '') echo "backup: no running postgres container in Compose project '${stack}'" >&2; exit 69 ;;
    *[!0-9a-f]*) echo "backup: more than one postgres container in Compose project '${stack}'" >&2; exit 69 ;;
  esac

  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_file="${backup_dir}/${stack}-${timestamp}.dump"
  partial_file="${backup_file}.partial"
  started_at="$(date +%s)"

  # Whatever an interrupted run left behind is dead: the lock is ours.
  rm -f "${backup_dir}/${stack}"-*.dump.partial
  trap 'rm -f "${partial_file}"' EXIT
  trap 'exit 130' HUP INT TERM

  docker exec "${container}" sh -c \
    'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"; exec pg_dump --host 127.0.0.1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format custom' \
    >"${partial_file}"
  test -s "${partial_file}"

  # The archive has to read back to its last byte before it counts: the table of
  # contents alone sits at the front and survives a truncated file.
  tables="$(docker exec -i "${container}" pg_restore --list <"${partial_file}" | grep -c 'TABLE DATA')" ||
    { echo "backup: the archive of ${stack} lists no table data" >&2; exit 1; }
  docker exec -i "${container}" pg_restore --file=/dev/null <"${partial_file}" ||
    { echo "backup: the archive of ${stack} does not read back to its end" >&2; exit 1; }

  # Checksum first, final name second: a file called *.dump always has its checksum,
  # and a crash in between leaves only a checksum without a dump, removed below.
  checksum="$(sha256sum "${partial_file}" | awk '{print $1}')"
  printf '%s  %s\n' "${checksum}" "$(basename "${backup_file}")" >"${backup_file}.sha256"
  mv "${partial_file}" "${backup_file}"
  trap - EXIT HUP INT TERM

  for orphan in "${backup_dir}/${stack}"-*.dump.sha256; do
    [ -e "${orphan}" ] || continue
    [ -e "${orphan%.sha256}" ] || rm -f "${orphan}"
  done
  removed="$(rotate)"

  size="$(wc -c <"${backup_file}" | tr -d ' ')"
  printf '%s backup %s: %s, %s bytes, %s tables, sha256 %s, %ss; %s old removed, %s kept\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${stack}" "${backup_file}" "${size}" "${tables}" "${checksum}" \
    "$(( $(date +%s) - started_at ))" "${removed}" "$(list_dumps | wc -l | tr -d ' ')"
}

"${action}"
