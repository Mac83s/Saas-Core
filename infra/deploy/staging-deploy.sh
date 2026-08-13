#!/bin/sh
set -eu

: "${DEPLOY_PATH:?DEPLOY_PATH jest wymagany}"
: "${RELEASE_SHA:?RELEASE_SHA jest wymagany}"
: "${STAGING_URL:?STAGING_URL jest wymagany}"

release_dir="${DEPLOY_PATH}/releases/${RELEASE_SHA}"
state_dir="${DEPLOY_PATH}/state"
compose_files="-f ${release_dir}/compose.yaml -f ${release_dir}/compose.staging.yaml"

mkdir -p "${release_dir}" "${state_dir}"
tar -xzf "/tmp/saas-core-${RELEASE_SHA}.tgz" -C "${release_dir}"
rm -f "/tmp/saas-core-${RELEASE_SHA}.tgz"

if [ ! -f "${DEPLOY_PATH}/staging.env" ]; then
  echo "Brak ${DEPLOY_PATH}/staging.env na hoście staging" >&2
  exit 1
fi
if [ ! -d "${DEPLOY_PATH}/secrets" ]; then
  echo "Brak ${DEPLOY_PATH}/secrets na hoście staging" >&2
  exit 1
fi
for required_secret in \
  postgres_app_password \
  object_storage_access_key_id \
  object_storage_secret_access_key; do
  if [ ! -s "${DEPLOY_PATH}/secrets/${required_secret}" ]; then
    echo "Brak niepustego sekretu ${required_secret} na hoście staging" >&2
    exit 1
  fi
done

set -a
. "${DEPLOY_PATH}/staging.env"
set +a
export SAAS_CORE_IMAGE_TAG="sha-${RELEASE_SHA}"
export SAAS_CORE_SECRETS_DIR="${DEPLOY_PATH}/secrets"
unset SAAS_CORE_BACKEND_IMAGE SAAS_CORE_FRONTEND_IMAGE SAAS_CORE_CADDY_IMAGE SAAS_CORE_REDIS_IMAGE

compose() {
  docker compose --env-file "${DEPLOY_PATH}/staging.env" ${compose_files} "$@"
}

previous_tag=""
if [ -f "${state_dir}/last-successful-image-tag" ]; then
  previous_tag="$(cat "${state_dir}/last-successful-image-tag")"
fi
printf '%s\n' "${previous_tag}" >"${state_dir}/previous-image-tag"
if [ -L "${DEPLOY_PATH}/current" ]; then
  readlink -f "${DEPLOY_PATH}/current" >"${state_dir}/previous-release"
fi
if [ -f "${state_dir}/last-successful-images.env" ]; then
  cp "${state_dir}/last-successful-images.env" "${state_dir}/previous-images.env"
fi

compose config --quiet
compose pull
compose up -d --wait --wait-timeout 1800 postgres redis clamav
compose run --rm database-bootstrap
compose run --rm migrate
compose run --rm --no-deps backend python manage.py configure_simulated_prices
compose up -d --no-deps backend worker scheduler
compose up -d --no-deps frontend
compose up -d --no-deps caddy
compose up -d postgres-exporter redis-exporter loki alloy
compose up -d celery-exporter prometheus grafana

attempt=0
until curl --fail --silent --show-error --max-time 10 \
  "${STAGING_URL%/}/api/v1/health/" >/dev/null; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge 18 ]; then
    compose ps
    compose logs --tail 100 \
      caddy backend frontend worker scheduler \
      clamav celery-exporter postgres-exporter redis-exporter prometheus loki alloy grafana
    exit 1
  fi
  sleep 5
done

for service in backend worker scheduler; do
  compose exec -T "${service}" python manage.py check_database_role
done
compose exec -T worker python manage.py check_malware_scanner

compose ps
compose images --format json >"${state_dir}/images-${RELEASE_SHA}.json"
{
  printf 'SAAS_CORE_BACKEND_IMAGE=%s\n' "$(docker image inspect --format '{{index .RepoDigests 0}}' "${SAAS_CORE_IMAGE_PREFIX}/backend:${SAAS_CORE_IMAGE_TAG}")"
  printf 'SAAS_CORE_FRONTEND_IMAGE=%s\n' "$(docker image inspect --format '{{index .RepoDigests 0}}' "${SAAS_CORE_IMAGE_PREFIX}/frontend:${SAAS_CORE_IMAGE_TAG}")"
  printf 'SAAS_CORE_CADDY_IMAGE=%s\n' "$(docker image inspect --format '{{index .RepoDigests 0}}' "${SAAS_CORE_IMAGE_PREFIX}/caddy:${SAAS_CORE_IMAGE_TAG}")"
  printf 'SAAS_CORE_REDIS_IMAGE=%s\n' "$(docker image inspect --format '{{index .RepoDigests 0}}' "${SAAS_CORE_IMAGE_PREFIX}/redis:${SAAS_CORE_IMAGE_TAG}")"
} >"${state_dir}/images-${RELEASE_SHA}.env"
cp "${state_dir}/images-${RELEASE_SHA}.env" "${state_dir}/last-successful-images.env"
printf '%s\n' "${SAAS_CORE_IMAGE_TAG}" >"${state_dir}/last-successful-image-tag"
printf '%s\n' "${RELEASE_SHA}" >"${state_dir}/last-successful-sha"
ln -sfn "${release_dir}" "${DEPLOY_PATH}/current"
