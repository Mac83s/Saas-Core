#!/usr/bin/env bash
# Site catalogue harness (F4-P0a), host side; see site-catalog.md.
#
#   site-catalog-run.sh [playwright args]  prepare a synthetic account, run the
#                                          spec in the Playwright container,
#                                          always remove the account
#   site-catalog-run.sh prepare|cleanup    one step, for SITE_CATALOG_SLUG,
#                                          SITE_CATALOG_EMAIL, SITE_CATALOG_PASSWORD
#                                          (the spec calls these on a host run)
set -euo pipefail

backend=${SAAS_CORE_BACKEND_CONTAINER:-saas-core-backend-1}
frontend=$(cd "$(dirname "$0")/.." && pwd)
root=$(cd "$frontend/../.." && pwd)

guard() {
  # Only the reserved synthetic fixture: sites_e2e_fixture and
  # purge_test_tenants refuse anything else too, this just fails earlier.
  [[ $SITE_CATALOG_SLUG =~ ^w6-e2e-[a-z0-9-]+$ &&
    $SITE_CATALOG_EMAIL == "$SITE_CATALOG_SLUG@example.test" ]] ||
    { echo "Not a synthetic w6-e2e-* account: $SITE_CATALOG_EMAIL" >&2; exit 2; }
}

prepare() {
  guard
  # The password travels in the environment, never on a command line.
  SITES_E2E_PASSWORD=$SITE_CATALOG_PASSWORD docker exec -e SITES_E2E_PASSWORD \
    "$backend" python manage.py sites_e2e_fixture prepare \
    --email "$SITE_CATALOG_EMAIL" --slug "$SITE_CATALOG_SLUG"
}

cleanup() {
  guard
  # sites_e2e_fixture cleanup refuses a tenant holding Sites data, which is
  # what the harness creates: purge_test_tenants erases the tenant, then the
  # media sweep deletes the stored objects its receipt lists.
  docker exec -i -e SITE_CATALOG_EMAIL -e SITE_CATALOG_SLUG "$backend" \
    python manage.py shell --no-imports <<'PY'
import json, os
from django.core.management import call_command
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.models import ErasureReceipt, Organization
from saas_core.modules.core.organizations.pre_tenant import PRE_TENANT_DB
from saas_core.modules.shared.media.tasks import purge_erased_objects

email, slug = os.environ["SITE_CATALOG_EMAIL"], os.environ["SITE_CATALOG_SLUG"]
organization = Organization.objects.using(PRE_TENANT_DB).filter(slug=slug).values_list("id", flat=True).first()
if User.objects.filter(email=email).exists():
    call_command("purge_test_tenants", email=[email], apply=True)
purge_erased_objects()
receipt = ErasureReceipt.objects.filter(organization_id=organization).first() if organization else None
result = {
    "accountRemoved": not User.objects.filter(email=email).exists(),
    "organizationRemoved": not Organization.objects.using(PRE_TENANT_DB).filter(slug=slug).exists(),
    "deletedObjects": receipt.deleted_object_count if receipt else 0,
    "pendingObjects": len(receipt.pending_object_keys) if receipt else 0,
}
print("site-catalog cleanup:", json.dumps(result))
assert result["accountRemoved"] and result["organizationRemoved"] and not result["pendingObjects"], result
PY
}

case ${1:-} in
  prepare | cleanup) "$1" ;;
  *)
    export SITE_CATALOG_SLUG="w6-e2e-catalog-$(openssl rand -hex 5)"
    export SITE_CATALOG_EMAIL="$SITE_CATALOG_SLUG@example.test"
    SITE_CATALOG_PASSWORD="W6-E2E-$(openssl rand -hex 16)-aA1!"
    export SITE_CATALOG_PASSWORD
    trap cleanup EXIT
    prepare
    docker run --rm --network host --ipc=host \
      -e SITE_CATALOG_HARNESS=1 -e SITE_CATALOG_SLUG -e SITE_CATALOG_EMAIL \
      -e SITE_CATALOG_PASSWORD -e SITE_CATALOG_STYLES -e SITE_CATALOG_ALL \
      -e SITE_CATALOG_PAGES -e SITE_CATALOG_PROXY -e SAAS_CORE_BASE_URL \
      -v "$root:$root" -w "$frontend" \
      "${SITE_CATALOG_IMAGE:-mcr.microsoft.com/playwright:v1.62.1-noble}" \
      npx playwright test e2e/site-catalog.spec.ts "$@"
    ;;
esac
