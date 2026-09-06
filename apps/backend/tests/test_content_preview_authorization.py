"""A suggest-only connector may preview exactly the resources it was granted."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from saas_core.modules.shared.notifications.models import ApiKey, ApiKeyCredentialRoute
from saas_core.modules.shared.sites.models import ContentAutomationGrant
from test_content_operations_api import _change_set, _preview
from test_sites_api import create_page, create_site, save_draft, sites_client
from test_sites_collections import create_collection, create_entry, save_entry_draft
from test_sites_operations import _api_key_client

pytestmark = pytest.mark.django_db
PREVIEW_URL = "/api/v1/sites/changes/"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


@pytest.fixture
def surface() -> tuple[Any, Any, Any, dict[str, Any]]:
    person, organization, owner = sites_client(slug="preview-owner", role_key="owner")
    site = create_site(person).data["id"]
    page = create_page(person, site, idempotency_key="preview-page").data["id"]
    save_draft(
        person, page, expected_version=0, idempotency_key="preview-draft", heading="Private draft"
    )
    document = _change_set(
        target={"kind": "site_page", "site_id": str(site), "page_id": str(page), "locale": "pl"},
        commands=[{"command": "translation.update", "fields": {"description": "Proposed copy."}}],
    )
    document["base"] = person.get("/api/v1/sites/content-base/", document["target"]).json()["base"]
    return person, organization, owner, document


def connector(surface: Any, *, scope: str = "content:read") -> tuple[Client, Any]:
    _, organization, owner, _ = surface
    client = _api_key_client(organization=organization, created_by=owner, marker="p")
    key = ApiKey.all_objects.get(organization=organization)
    # Both routing and tenant records carry scopes; never rely on only one.
    ApiKey.all_objects.filter(pk=key.id).update(scopes=[scope])
    ApiKeyCredentialRoute.objects.filter(api_key_id=key.id).update(scopes=[scope])
    return client, key


def grant_for(surface: Any, key: Any, **bounds: Any) -> Any:
    _, organization, owner, document = surface
    return ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        site_id=document["target"]["site_id"],
        mode="suggest_only",
        created_by=owner,
        **bounds,
    )


def post_preview(client: Client, document: dict[str, Any]) -> Any:
    return client.post(PREVIEW_URL, {"change_set": document}, content_type="application/json")


def test_read_scope_and_suggest_only_grant_preview_without_business_writes(surface: Any) -> None:
    client, key = connector(surface)
    grant_for(surface, key)
    document = surface[3]
    with CaptureQueriesContext(connection) as queries:
        response = post_preview(client, document)
    assert response.status_code == 200, response.content
    assert response.json()["translation_fields"] == {"description": "Proposed copy."}
    assert response.json()["base_version"] == 1
    assert response.json()["blocks_before"] == response.json()["blocks_after"]
    sql = [query["sql"] for query in queries.captured_queries]
    tenant_set = next(
        index for index, statement in enumerate(sql) if "app.organization_id" in statement
    )
    block_read = next(
        index for index, statement in enumerate(sql) if '"sites_pageblock"' in statement
    )
    assert tenant_set < block_read
    assert not any(
        query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        and "sites_" in query["sql"]
        for query in queries.captured_queries
    )
    # POST preview is the exact read exception, not a licence for other POSTs.
    for path in ("/api/v1/sites/changes/apply/", "/api/v1/sites/", "/api/v1/sites/changes/other/"):
        refused = client.post(path, {"change_set": document}, content_type="application/json")
        assert refused.status_code == 401


@pytest.mark.parametrize(
    "state", ["missing", "revoked", "expired", "other_site", "collection_only"]
)
def test_draft_key_cannot_preview_outside_an_active_grant(surface: Any, state: str) -> None:
    client, key = connector(surface, scope="content:draft")
    person, organization, owner, document = surface
    if state in {"revoked", "expired"}:
        field = "revoked_at" if state == "revoked" else "expires_at"
        grant_for(surface, key, **{field: timezone.now() - timedelta(seconds=1)})
    elif state == "other_site":
        other_site = create_site(
            person, slug="other-preview-site", idempotency_key="other-site"
        ).data["id"]
        ContentAutomationGrant.all_objects.create(
            organization=organization,
            credential_id=key.id,
            site_id=other_site,
            mode="suggest_only",
            created_by=owner,
        )
    elif state == "collection_only":
        collection = create_collection(person, document["target"]["site_id"]).data["id"]
        ContentAutomationGrant.all_objects.create(
            organization=organization,
            credential_id=key.id,
            collection_id=collection,
            mode="suggest_only",
            created_by=owner,
        )
    with CaptureQueriesContext(connection) as queries:
        response = post_preview(client, document)
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "automation_grant_missing"
    assert not any('"sites_pageblock"' in query["sql"] for query in queries.captured_queries)


def test_preview_checks_the_feature_before_reading_the_target(surface: Any) -> None:
    from saas_core.modules.shared.billing.models import EntitlementSnapshot

    client, key = connector(surface, scope="content:draft")
    grant_for(surface, key)
    EntitlementSnapshot.all_objects.filter(organization=surface[1]).update(
        features={"sites.enabled": False},
    )
    with CaptureQueriesContext(connection) as queries:
        response = post_preview(client, surface[3])
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "entitlement_required"
    assert not any('"sites_pageblock"' in query["sql"] for query in queries.captured_queries)


def test_preview_checks_session_permission(surface: Any) -> None:
    from saas_core.modules.core.organizations.models import Membership, Role

    person, organization, owner, document = surface
    Membership.objects.filter(organization=organization, user=owner).update(
        role=Role.objects.get(key="viewer", organization=None),
    )
    response = _preview(person, document)
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "organization_permission_denied"


def test_preview_refuses_a_foreign_tenant_even_with_a_valid_grant(surface: Any) -> None:
    client, key = connector(surface, scope="content:draft")
    grant_for(surface, key)
    foreign, _, _ = sites_client(slug="preview-foreign", role_key="owner")
    foreign_site = create_site(foreign).data["id"]
    foreign_page = create_page(foreign, foreign_site, idempotency_key="foreign-preview").data["id"]
    document = surface[3]
    document["target"].update(site_id=str(foreign_site), page_id=str(foreign_page))
    response = post_preview(client, document)
    assert response.status_code == 404, response.content


def test_suspended_organization_cannot_preview(surface: Any) -> None:
    from saas_core.modules.core.organizations.models import OrganizationStatus

    client, key = connector(surface, scope="content:draft")
    grant_for(surface, key)
    organization = surface[1]
    organization.status = OrganizationStatus.SUSPENDED
    organization.save(update_fields=["status"])
    response = post_preview(client, surface[3])
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "api_key_organization_inactive"


def test_revoking_the_grant_stops_the_next_preview(surface: Any) -> None:
    client, key = connector(surface)
    grant = grant_for(surface, key)
    assert post_preview(client, surface[3]).status_code == 200
    grant.revoked_at = timezone.now()
    grant.save(update_fields=["revoked_at"])
    response = post_preview(client, surface[3])
    assert response.status_code == 403
    assert response.json()["code"] == "automation_grant_missing"


def test_preview_service_requires_context_before_any_domain_query(surface: Any) -> None:
    from saas_core.modules.core.organizations.authorization import ActiveOrganizationRequired
    from saas_core.modules.shared.sites.change_sets import preview_change_set

    with CaptureQueriesContext(connection) as queries, pytest.raises(ActiveOrganizationRequired):
        preview_change_set(surface[3])
    assert queries.captured_queries == []


def test_read_only_billing_access_still_allows_preview(surface: Any) -> None:
    from saas_core.modules.shared.billing.models import AccessMode, EntitlementSnapshot

    client, key = connector(surface)
    grant_for(surface, key)
    EntitlementSnapshot.all_objects.filter(organization=surface[1]).update(
        access_mode=AccessMode.READ_ONLY,
    )
    assert post_preview(client, surface[3]).status_code == 200


def test_collection_grant_only_previews_entries_of_its_real_site(surface: Any) -> None:
    person, organization, owner, document = surface
    collection = create_collection(person, document["target"]["site_id"]).data["id"]
    entry = create_entry(
        person, collection, slug="preview-entry", idempotency_key="preview-entry"
    ).data["id"]
    save_entry_draft(
        person, entry, expected_version=0, text="Entry draft.", idempotency_key="entry-base"
    )
    client, key = connector(surface)
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        collection_id=collection,
        mode="suggest_only",
        created_by=owner,
    )
    document["target"] = {
        "kind": "content_entry",
        "site_id": document["target"]["site_id"],
        "collection_id": str(collection),
        "entry_id": str(entry),
        "locale": "pl",
    }
    document["commands"] = [{"command": "block.remove", "position": 0}]
    document["base"] = person.get("/api/v1/sites/content-base/", document["target"]).json()["base"]
    assert post_preview(client, document).status_code == 200
    document["target"]["site_id"] = str(
        create_site(person, slug="wrong-entry-site", idempotency_key="wrong-entry-site").data["id"]
    )
    response = post_preview(client, document)
    assert response.status_code == 404, response.content
