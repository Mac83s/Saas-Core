#!/bin/sh
set -eu

: "${OBJECT_STORAGE_ACCESS_KEY_ID_FILE:?}"
: "${OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE:?}"
: "${OBJECT_STORAGE_BUCKET:?}"

if [ ! -s "$OBJECT_STORAGE_ACCESS_KEY_ID_FILE" ] || [ ! -s "$OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE" ]; then
  echo "Brak lokalnych sekretów object storage" >&2
  exit 1
fi

IFS= read -r AWS_ACCESS_KEY_ID < "$OBJECT_STORAGE_ACCESS_KEY_ID_FILE"
IFS= read -r AWS_SECRET_ACCESS_KEY < "$OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

exec /entrypoint.sh mini \
  -dir=/data \
  -bucket="$OBJECT_STORAGE_BUCKET" \
  -admin.ui=false \
  -master.telemetry=false \
  -s3.allowDeleteBucketNotEmpty=false \
  -s3.allowedOrigins="${OBJECT_STORAGE_ALLOWED_ORIGINS:-http://localhost:8080}" \
  -webdav=false
