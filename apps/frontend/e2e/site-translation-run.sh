#!/usr/bin/env bash
# Host side of e2e/site-translation.spec.ts (TL15d); see site-catalog.md.
#
#   site-translation-run.sh prepare|cleanup   for SITE_CATALOG_SLUG,
#                                             SITE_CATALOG_EMAIL, SITE_CATALOG_PASSWORD
#
# `prepare` makes the synthetic w6-e2e-* company of site-catalog-run.sh, gives
# it credits to order with and puts it — this company only — on the stand-in
# translator (`translation_e2e_fixture on`). The stand-in exists only where the
# stack sets MODEL_PORT_TEST_DOUBLE; elsewhere the command refuses, the
# company is removed again and nothing is ever sent to a real model.
set -euo pipefail

backend=${SAAS_CORE_BACKEND_CONTAINER:-saas-core-backend-1}
here=$(cd "$(dirname "$0")" && pwd)
# A platform operator (staff with MFA) the fixture command records.
operator=${SITE_TRANSLATION_OPERATOR:-operator@saas.test}

stand_in() {
  docker exec "$backend" python manage.py translation_e2e_fixture "$1" \
    --organization "$SITE_CATALOG_SLUG" --operator "$operator"
}

prepare() {
  bash "$here/site-catalog-run.sh" prepare
  if ! stand_in on; then
    bash "$here/site-catalog-run.sh" cleanup
    exit 3
  fi
  # The stand-in costs nothing, but an order still holds credits for every
  # thousand characters: the company gets a month's pool to hold them from.
  docker exec -i -e SITE_CATALOG_SLUG "$backend" \
    python manage.py shell --no-imports <<'PY'
import os
from django.db import transaction
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.pre_tenant import PRE_TENANT_DB
from saas_core.modules.shared.billing.models import EntitlementSnapshot

slug = os.environ["SITE_CATALOG_SLUG"]
assert slug.startswith("w6-e2e-"), slug
organization = Organization.objects.using(PRE_TENANT_DB).get(slug=slug)
with transaction.atomic():
    set_local_organization_id(organization.id)
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=organization.id)
    snapshot.quotas["credits.monthly"] = 50
    snapshot.sources["credits.monthly"] = {"kind": "e2e"}
    snapshot.save(update_fields=["quotas", "sources"])
print("site-translation credits: 50 a month")
PY
}

cleanup() {
  # Off the stand-in first: the row names the company that is about to go.
  stand_in off || true
  bash "$here/site-catalog-run.sh" cleanup
}

case ${1:-} in
  prepare | cleanup) "$1" ;;
  *)
    echo "usage: site-translation-run.sh prepare|cleanup" >&2
    exit 2
    ;;
esac
