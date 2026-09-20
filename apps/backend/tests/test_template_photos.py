from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import Membership, OrganizationStatus
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.media.models import MediaAsset
from saas_core.modules.shared.sites.models import Domain, PageVersion, Publication
from saas_core.modules.shared.sites.public_media import serve_public_media
from saas_core.modules.shared.sites.publication_routing import PublicSiteNotFound
from test_sites_api import (
    CleanTemplateMediaScanner,
    TemplateMediaStorage,
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()


@pytest.fixture
def media_runtime(monkeypatch):
    storage, scanner = TemplateMediaStorage(), CleanTemplateMediaScanner()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner", lambda: scanner
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )
    return storage, scanner


def enable_storage(org):
    snapshot = EntitlementSnapshot.all_objects.get(organization=org)
    snapshot.features["storage.enabled"] = True
    snapshot.quotas["storage.bytes"] = 50 * 1024**2
    snapshot.sources["storage.enabled"] = {"kind": "plan"}
    snapshot.sources["storage.bytes"] = {"kind": "plan"}
    snapshot.save()


def photo_request(client, photo="business", key="demo-photo"):
    return client.post(
        f"/api/v1/sites/template-media/{photo}/materialize/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_photo_materialization_is_scanned_idempotent_and_isolated(media_runtime):
    storage, scanner = media_runtime
    client, org, _ = sites_client(slug="photo-a", role_key="owner")
    other, foreign, _ = sites_client(slug="photo-b", role_key="owner")
    enable_storage(org)
    enable_storage(foreign)
    with CaptureQueriesContext(connection) as queries:
        first = photo_request(client)
    assert first.status_code == 200, first.data
    sql = [q["sql"] for q in queries.captured_queries]
    assert next(i for i, q in enumerate(sql) if "SET LOCAL app.organization_id" in q) < next(
        i for i, q in enumerate(sql) if 'FROM "media_mediaasset"' in q
    )
    assert photo_request(client).data == first.data
    assert scanner.calls == 1
    assert photo_request(client, photo="medicine").status_code == 409
    second = photo_request(other)
    assert second.status_code == 200
    assert second.data["asset_id"] != first.data["asset_id"]
    assert scanner.calls == 2
    assert MediaAsset.all_objects.get(id=first.data["asset_id"]).organization_id == org.id
    assert all(key.startswith((str(org.id), str(foreign.id))) for key in storage.objects)
    assert other.get(f"/api/v1/media/{first.data['asset_id']}/preview/").status_code == 404
    assert client.post("/api/v1/sites/template-media/business/materialize/", {}).status_code == 403
    assert photo_request(client, photo="unknown").status_code == 404
    role = connection.ops.quote_name(f"photo_rls_{uuid7().hex}")
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cursor.execute(f"GRANT SELECT ON media_mediaasset TO {role}")
        cursor.execute(f"SET LOCAL ROLE {role}")
        for tenant, expected in [("", 0), (str(org.id), 1), (str(foreign.id), 0)]:
            cursor.execute("SET LOCAL app.organization_id = %s", [tenant])
            cursor.execute(
                "SELECT COUNT(*) FROM media_mediaasset WHERE id = %s", [first.data["asset_id"]]
            )
            assert cursor.fetchone()[0] == expected
        cursor.execute("RESET ROLE")


@pytest.mark.parametrize(
    "denial", ["anonymous", "permission", "entitlement", "storage", "context", "suspended"]
)
def test_photo_denials_do_not_read_or_write_media(denial, media_runtime):
    client, org, _ = sites_client(
        slug=f"photo-denial-{denial}",
        role_key="viewer" if denial == "permission" else "owner",
        feature_enabled=denial != "entitlement",
    )
    if denial != "storage":
        enable_storage(org)
    if denial == "context":
        Membership.objects.filter(organization=org).delete()
    elif denial == "suspended":
        org.status = OrganizationStatus.SUSPENDED
        org.save()
    with CaptureQueriesContext(connection) as queries:
        result = (
            APIClient().post("/api/v1/sites/template-media/business/materialize/", {})
            if denial == "anonymous"
            else photo_request(client)
        )
    assert result.status_code in (403, 409)
    assert not any('"media_mediaasset"' in q["sql"] for q in queries.captured_queries)
    assert media_runtime[0].objects == {}


def test_localized_page_import_binds_real_photos_and_compensates_failed_import(media_runtime):
    storage, scanner = media_runtime
    client, org, _ = sites_client(slug="photo-page", role_key="owner")
    enable_storage(org)
    site_id = create_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]
    url = f"/api/v1/sites/pages/{page_id}/template-import/"
    payload = {
        "expected_version": 99,
        "template_id": "core.medicine_clinic",
        "template_version": 1,
        "locale": "en",
    }

    def send(key):
        return client.post(
            url,
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
            HTTP_IDEMPOTENCY_KEY=key,
        )

    assert send("stale").status_code == 409
    assert storage.objects == {}
    assert MediaAsset.all_objects.filter(organization=org).count() == 0
    payload["expected_version"] = 0
    result = send("import")
    assert result.status_code == 201, result.data
    images = [block["data"]["image"] for block in result.data["blocks"] if "image" in block["data"]]
    assert len(images) == 2
    assert "Care tailored" in result.data["blocks"][0]["data"]["title"]
    assert {str(image["asset_id"]) for image in images} == set(
        map(str, result.data["media_asset_ids"])
    )
    for image in images:
        asset = MediaAsset.all_objects.get(id=image["asset_id"])
        assert asset.state == "ready"
        assert asset.organization_id == org.id
        assert client.get(f"/api/v1/media/{asset.id}/preview/").status_code == 200
    assert send("import").data["draft_id"] == result.data["draft_id"]
    payload["locale"] = "pl"
    assert send("import").status_code == 409
    assert PageVersion.all_objects.filter(page_id=page_id).count() == 1

    domain = Domain.all_objects.get(site_id=site_id)
    with pytest.raises(PublicSiteNotFound):
        serve_public_media(host=domain.hostname, asset_id=asset.id)
    save_translation(
        client,
        page_id,
        "pl",
        expected_version=0,
        slug="clinic",
        title="Clinic",
        description="Example clinic",
        idempotency_key="translation",
    )
    published = publish_site_request(client, site_id, idempotency_key="publish")
    assert published.status_code in (200, 201), published.data
    snapshot = Publication.all_objects.get(site_id=site_id).snapshot
    assert snapshot["pages"][0]["blocks"][0]["data"]["image"] == images[0]
    response = serve_public_media(host=domain.hostname, asset_id=asset.id)
    assert response.status_code == 200
    assert response.content == storage.objects[asset.object_key][0]
