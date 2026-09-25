#!/bin/sh
set -eu

: "${DEPLOY_PATH:?DEPLOY_PATH jest wymagany}"
: "${STAGING_URL:?STAGING_URL jest wymagany}"

state_dir="${DEPLOY_PATH}/state"
previous_release="${state_dir}/previous-release"
if [ ! -f "${previous_release}" ]; then
  echo "Brak poprzedniego release do rollbacku" >&2
  exit 1
fi
release_dir="$(cat "${previous_release}")"
previous_tag="$(cat "${state_dir}/previous-image-tag")"
previous_images="${state_dir}/previous-images.env"

if [ -z "${previous_tag}" ] || [ ! -f "${previous_images}" ] || [ ! -d "${release_dir}" ]; then
  echo "Brak poprzedniego manifestu obrazów albo aktywnego release do rollbacku" >&2
  exit 1
fi
if ! grep -q 'postgres_app_password' "${release_dir}/compose.yaml"; then
  echo "Rollback zablokowany: poprzedni release nie rozdziela ról PostgreSQL" >&2
  exit 1
fi
if ! grep -q 'OBJECT_STORAGE_ENDPOINT_URL' "${release_dir}/compose.staging.yaml"; then
  echo "Rollback zablokowany: poprzedni release nie wymaga zewnętrznego S3" >&2
  exit 1
fi

set -a
. "${DEPLOY_PATH}/staging.env"
. "${previous_images}"
set +a
export SAAS_CORE_IMAGE_TAG="${previous_tag}"
export SAAS_CORE_SECRETS_DIR="${DEPLOY_PATH}/secrets"
export COMPOSE_PROFILES=image-generation

compose() {
  docker compose --env-file "${DEPLOY_PATH}/staging.env" \
    -f "${release_dir}/compose.yaml" -f "${release_dir}/compose.staging.yaml" "$@"
}

# Rollback nie cofa schematu. Poprzedni obraz musi być zgodny z migracją expand/contract.
compose pull backend frontend caddy redis clamav
compose up -d --wait --wait-timeout 1800 clamav
compose up -d --no-deps backend worker worker-ai scheduler celery-exporter frontend caddy
curl --fail --silent --show-error --retry 18 --retry-delay 5 --max-time 10 \
  "${STAGING_URL%/}/api/v1/health/" >/dev/null
for service in backend worker worker-ai scheduler; do
  compose exec -T "${service}" python manage.py check_database_role
done
compose exec -T worker python manage.py check_malware_scanner
printf '%s\n' "${previous_tag}" >"${state_dir}/last-successful-image-tag"
cp "${previous_images}" "${state_dir}/last-successful-images.env"
ln -sfn "${release_dir}" "${DEPLOY_PATH}/current"
