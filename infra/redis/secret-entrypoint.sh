#!/bin/sh
set -eu

if [ -n "${REDIS_PASSWORD_FILE:-}" ]; then
  redis_password="$(cat "${REDIS_PASSWORD_FILE}")"
  if ! printf '%s' "${redis_password}" | grep -Eq '^[A-Za-z0-9_-]{32,}$'; then
    echo "REDIS_PASSWORD_FILE musi zawierać co najmniej 32 znaki base64url" >&2
    exit 1
  fi
  if [ "${1:-}" = "redis_exporter" ]; then
    export REDIS_PASSWORD="${redis_password}"
  else
    umask 077
    printf 'user default on >%s ~* &* +@all\n' "${redis_password}" > /tmp/users.acl
    set -- "$@" --aclfile /tmp/users.acl
  fi
fi

exec "$@"
