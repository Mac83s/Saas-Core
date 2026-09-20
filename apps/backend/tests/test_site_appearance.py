from copy import deepcopy
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    OrganizationStatus,
)
from saas_core.modules.shared.sites.appearance import default_appearance
from saas_core.modules.shared.sites.models import Publication, Site, SiteAppearanceRevision
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_draft,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


def save(client, url, appearance, version=0, key="appearance-one"):
    return client.put(
        url,
        {"expected_version": version, "appearance": appearance},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_appearance_versions_idempotency_validation_csrf_and_audit():
    client, org, _ = sites_client(slug="appearance-owner", role_key="owner")
    site_id = create_site(client).data["id"]
    url = f"/api/v1/sites/{site_id}/appearance/"
    with CaptureQueriesContext(connection) as queries:
        original = client.get(url)
    sql = [q["sql"] for q in queries.captured_queries]
    assert next(i for i, q in enumerate(sql) if "SET LOCAL app.organization_id" in q) < next(
        i for i, q in enumerate(sql) if 'FROM "sites_siteappearancerevision"' in q
    )
    assert original.data["version"] == 0
    appearance = original.data["appearance"]
    appearance["font"] = "georgia"
    appearance["header"]["layout"] = "centered"
    assert (
        client.put(
            url, {"expected_version": 0, "appearance": appearance}, format="json"
        ).status_code
        == 403
    )
    first = save(client, url, appearance)
    assert first.status_code == 200
    assert first.data["version"] == 1
    assert save(client, url, appearance).data == first.data
    assert save(client, url, appearance, key="stale").status_code == 409
    different = deepcopy(appearance)
    different["font"] = "arial"
    assert save(client, url, different).data["code"] == "sites_idempotency_conflict"
    different["font"] = "javascript:evil"
    assert save(client, url, different, version=1, key="invalid").status_code == 400
    assert SiteAppearanceRevision.all_objects.filter(organization=org).count() == 1
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=org, action="sites.appearance.saved"
        ).count()
        == 1
    )
    assert client.get(url).data == first.data
    with pytest.raises(DatabaseError), transaction.atomic():
        SiteAppearanceRevision.all_objects.filter(organization=org).update(data={})


@pytest.mark.parametrize(
    "denial", ["anonymous", "permission", "entitlement", "context", "suspended"]
)
@pytest.mark.parametrize("method", ["get", "put"])
def test_appearance_denials_do_not_read_designs(denial, method):
    client, org, _ = sites_client(
        slug=f"appearance-{denial}",
        role_key="viewer" if denial == "permission" else "owner",
        feature_enabled=denial != "entitlement",
    )
    if denial == "anonymous":
        client = APIClient()
    elif denial == "context":
        Membership.objects.filter(organization=org).delete()
    elif denial == "suspended":
        org.status = OrganizationStatus.SUSPENDED
        org.save()
    with CaptureQueriesContext(connection) as queries:
        url = f"/api/v1/sites/{uuid7()}/appearance/"
        if method == "get":
            result = client.get(url)
        elif denial == "anonymous":
            result = client.put(url, {}, format="json")
        else:
            result = save(client, url, default_appearance(Site(name="Clinic")))
    assert result.status_code in (403, 409)
    assert not any(
        'FROM "sites_siteappearancerevision"' in q["sql"] for q in queries.captured_queries
    )


def test_appearance_foreign_site_and_rls():
    client, org, _ = sites_client(slug="appearance-own", role_key="owner")
    other, foreign, _ = sites_client(slug="appearance-other", role_key="owner")
    site_id = create_site(client).data["id"]
    url = f"/api/v1/sites/{site_id}/appearance/"
    appearance = client.get(url).data["appearance"]
    assert save(client, url, appearance).status_code == 200
    assert other.get(url).status_code == 404
    assert save(other, url, appearance).status_code == 404
    role = connection.ops.quote_name(f"appearance_rls_{uuid7().hex}")
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cursor.execute(f"GRANT SELECT ON sites_siteappearancerevision TO {role}")
        cursor.execute(f"SET LOCAL ROLE {role}")
        for tenant, expected in [("", 0), (str(foreign.id), 0), (str(org.id), 1)]:
            cursor.execute("SET LOCAL app.organization_id = %s", [tenant])
            cursor.execute("SELECT COUNT(*) FROM sites_siteappearancerevision")
            assert cursor.fetchone()[0] == expected
        cursor.execute("RESET ROLE")


def test_appearance_is_copied_into_publication_and_later_changes_stay_private():
    client, _, _ = sites_client(slug="appearance-publish", role_key="owner")
    site_id = create_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]
    save_draft(client, page_id, expected_version=0, idempotency_key="draft", heading="Hello")
    save_translation(
        client,
        page_id,
        "pl",
        expected_version=0,
        slug="home",
        title="Home",
        description="Hello",
        idempotency_key="translation",
    )
    url = f"/api/v1/sites/{site_id}/appearance/"
    appearance = client.get(url).data["appearance"]
    appearance["header"]["layout"] = "centered"
    appearance["navigation"]["mobile"] = "bottom"
    appearance["designTokens"]["palette"] = "emerald"
    assert save(client, url, appearance).status_code == 200
    result = publish_site_request(client, site_id, idempotency_key="publish")
    assert result.status_code in (200, 201)
    snapshot = Publication.all_objects.get(site_id=site_id).snapshot
    assert snapshot["appearance"] == appearance
    assert snapshot["design_tokens"] == appearance["designTokens"]
    changed = deepcopy(appearance)
    changed["header"]["layout"] = "stacked"
    assert save(client, url, changed, version=1, key="two").status_code == 200
    assert Publication.all_objects.get(site_id=site_id).snapshot == snapshot
