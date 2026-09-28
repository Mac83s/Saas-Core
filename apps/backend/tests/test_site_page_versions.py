"""The page's version history and restore (F4-A): every version stays, a
restore is a new version with an earlier one's sections and look."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.sites.models import PageVersion
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    import_page_template,
    save_draft,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    # Three logins per test; the throttle counts them in the cache.
    cache.clear()


def versions(client: APIClient, page_id: str, **query: Any) -> Any:
    return client.get(f"/api/v1/sites/pages/{page_id}/versions/", query)


def restore(
    client: APIClient,
    page_id: str,
    version_id: str,
    *,
    expected_version: int,
    idempotency_key: str,
    csrf: bool = True,
) -> Any:
    return client.post(
        f"/api/v1/sites/pages/{page_id}/versions/{version_id}/restore/",
        {"expected_version": expected_version},
        format="json",
        **({"HTTP_X_CSRFTOKEN": csrf_value(client)} if csrf else {}),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def test_history_lists_versions_newest_first_with_their_origin() -> None:
    client, _, user = sites_client(slug="sites-versions-history")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    page_id = page.data["id"]
    first = save_draft(
        client, page_id, expected_version=0, idempotency_key="v1", heading="Pierwsza"
    )
    assert first.status_code == 201
    imported = import_page_template(
        client, page_id, expected_version=1, idempotency_key="v2"
    )
    assert imported.status_code == 201

    listed = versions(client, page_id)
    assert listed.status_code == 200
    items = listed.data["items"]
    assert [item["number"] for item in items] == [2, 1]
    assert items[0]["origin"] == "template"
    assert items[0]["origin_ref"] == "core.profile@1"
    assert items[0]["current"] is True
    assert items[0]["block_count"] == 3
    assert items[1]["origin"] == "save"
    assert items[1]["current"] is False
    assert items[1]["block_count"] == 2
    assert items[1]["created_by"]["email"] == user.email
    assert items[1]["automation"] is False

    paged = versions(client, page_id, limit=1)
    assert [item["number"] for item in paged.data["items"]] == [2]
    rest = versions(client, page_id, limit=1, cursor=paged.data["next_cursor"])
    assert [item["number"] for item in rest.data["items"]] == [1]
    assert rest.data["next_cursor"] is None


def test_restore_makes_a_new_version_with_the_earlier_content_and_keeps_the_rest() -> None:
    client, organization, _ = sites_client(slug="sites-versions-restore")
    site = create_site(client)
    page_id = create_page(client, site.data["id"]).data["id"]
    first = save_draft(
        client, page_id, expected_version=0, idempotency_key="v1", heading="Pierwsza"
    )
    save_draft(client, page_id, expected_version=1, idempotency_key="v2", heading="Druga")
    first_id = first.data["draft_id"]

    restored = restore(
        client, page_id, first_id, expected_version=2, idempotency_key="restore-1"
    )
    repeated = restore(
        client, page_id, first_id, expected_version=2, idempotency_key="restore-1"
    )
    stale = restore(
        client, page_id, first_id, expected_version=2, idempotency_key="restore-stale"
    )

    assert restored.status_code == 201
    assert restored.data["version"] == 3
    assert restored.data["blocks"][0]["data"]["heading"] == "Pierwsza"
    assert repeated.status_code == 200
    assert repeated.data["draft_id"] == restored.data["draft_id"]
    assert stale.status_code == 409
    assert stale.data["code"] == "draft_version_conflict"
    # Nothing rewritten: three versions, the second still says "Druga".
    stored = PageVersion.all_objects.filter(organization=organization).order_by("number")
    assert [version.number for version in stored] == [1, 2, 3]
    assert stored[2].origin == "restore"
    assert stored[2].origin_ref == "1"
    assert stored[1].blocks.get(position=0).data["heading"] == "Druga"
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization, action="sites.page.version_restored"
        ).count()
        == 1
    )
    history = versions(client, page_id).data["items"]
    assert (history[0]["origin"], history[0]["origin_ref"], history[0]["current"]) == (
        "restore",
        "1",
        True,
    )


def test_history_and_restore_are_tenant_scoped_and_need_csrf_and_permission() -> None:
    client, _, _ = sites_client(slug="sites-versions-owner")
    foreign, _, _ = sites_client(slug="sites-versions-foreign")
    viewer, _, _ = sites_client(slug="sites-versions-noplan", feature_enabled=False)
    site = create_site(client)
    page_id = create_page(client, site.data["id"]).data["id"]
    first = save_draft(
        client, page_id, expected_version=0, idempotency_key="v1", heading="Pierwsza"
    )
    version_id = first.data["draft_id"]

    assert versions(foreign, page_id).status_code == 404
    assert (
        restore(foreign, page_id, version_id, expected_version=1, idempotency_key="x")
        .data["code"]
        == "page_version_not_found"
    )
    assert versions(viewer, page_id).status_code == 403
    assert restore(
        client, page_id, version_id, expected_version=1, idempotency_key="y", csrf=False
    ).status_code == 403
