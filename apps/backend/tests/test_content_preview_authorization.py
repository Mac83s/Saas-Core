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
from test_content_operations_api import _apply, _change_set, _preview
from test_sites_api import create_page, create_site, csrf_value, save_draft, sites_client
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
        role=Role.objects.get(key="viewer", organization=None, organization_type=""),
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


# `allowed_link_hosts`: a link is a recommendation made in the customer's name.

OWN_HOST = "sklep.example.test"


def linking(surface: Any, hosts: list[str]) -> Client:
    """A drafting connector on an automated page of a site with its own domain."""
    from saas_core.modules.shared.sites.models import Domain, Page

    _, organization, owner, document = surface
    client, key = connector(surface, scope="content:draft")
    grant = grant_for(surface, key, allowed_link_hosts=hosts)
    grant.mode = "draft_write"
    grant.save(update_fields=["mode"])
    Page.all_objects.filter(pk=document["target"]["page_id"]).update(automation_policy="automated")
    Domain.all_objects.create(
        organization=organization,
        site_id=document["target"]["site_id"],
        hostname=OWN_HOST,
        kind="custom",
        status="verified",
        verification_name=f"_saas-core.{OWN_HOST}",
        verification_token="token",
        created_by=owner,
        idempotency_key="own-domain",
        request_hash="0" * 64,
    )
    return client


def with_block(surface: Any, block: dict[str, Any]) -> dict[str, Any]:
    person, _, _, document = surface
    document["commands"] = [{"command": "block.insert", "position": 0, "block": block}]
    document["base"] = person.get("/api/v1/sites/content-base/", document["target"]).json()["base"]
    return document


def cta(href: str) -> dict[str, Any]:
    # hero v1 still accepts `//host`, so the envelope alone does not stop it.
    return {
        "type": "core.hero",
        "schema_version": 1,
        "data": {"heading": "Oferta", "ctaLabel": "Zobacz", "ctaHref": href},
    }


@pytest.mark.parametrize(
    ("href", "allowed"),
    [
        ("https://evil.test/oferta", False),
        ("https://partner.test/oferta", True),
        ("https://PARTNER.test:8443/oferta", True),
        ("https://sub.partner.test/", False),
        ("/kontakt/", True),
        (f"https://{OWN_HOST}/kontakt/", True),
        ("mailto:biuro@evil.test", True),
        ("tel:+48123456789", True),
        ("//evil.test/oferta", False),
        ("/\\evil.test/oferta", False),
        ("https://partner.test@evil.test/", False),
        ("https:///evil.test/", False),
    ],
)
def test_an_automation_links_only_to_its_own_site_and_the_granted_hosts(
    surface: Any, href: str, allowed: bool
) -> None:
    client = linking(surface, ["partner.test"])
    response = post_preview(client, with_block(surface, cta(href)))
    if allowed:
        assert response.status_code == 200, response.content
    else:
        assert response.status_code == 403, response.content
        assert response.json()["code"] == "automation_link_host_forbidden"
        assert "blocks[0].data.ctaHref" in response.json()["detail"]


def test_an_empty_host_list_means_internal_links_only(surface: Any) -> None:
    client = linking(surface, [])
    nested = {
        "type": "core.rich_text",
        "schema_version": 2,
        "data": {
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"text": "Zobacz "},
                        {"text": "partnera", "href": "https://partner.test/"},
                    ],
                }
            ]
        },
    }
    response = post_preview(client, with_block(surface, nested))
    assert response.status_code == 403, response.content
    assert "blocks[0].data.content[0].content[1].href" in response.json()["detail"]
    assert post_preview(client, with_block(surface, cta(f"https://{OWN_HOST}/"))).status_code == 200


def test_apply_refuses_the_link_before_anything_is_written(surface: Any) -> None:
    from saas_core.modules.shared.sites.models import ContentProposal, PageVersion

    client = linking(surface, [])
    document = with_block(surface, cta("https://evil.test/"))
    response = client.post(
        "/api/v1/sites/changes/apply/", {"change_set": document}, content_type="application/json"
    )
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "automation_link_host_forbidden"
    page_id = document["target"]["page_id"]
    assert PageVersion.all_objects.filter(page_id=page_id).count() == 1
    assert not ContentProposal.all_objects.filter(resource_id=page_id).exists()


def test_a_person_links_anywhere(surface: Any) -> None:
    person, _, _, _ = surface
    document = with_block(surface, cta("https://evil.test/"))
    assert _preview(person, document).status_code == 200
    response = _apply(person, document)
    assert response.status_code == 201, response.content


def test_a_link_a_person_already_placed_survives_an_automated_rewrite(surface: Any) -> None:
    """Rewriting the copy around somebody's link is not a new recommendation."""
    person, _, _, document = surface
    hero = cta("https://evil.test/")["data"]
    saved = person.put(
        f"/api/v1/sites/pages/{document['target']['page_id']}/draft/",
        {
            "expected_version": 1,
            "blocks": [{"block_type": "core.hero", "schema_version": 1, "data": hero}],
            "media_asset_ids": [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(person),
        HTTP_IDEMPOTENCY_KEY="person-link",
    )
    assert saved.status_code == 201, saved.content
    client = linking(surface, [])
    replaced = cta("https://evil.test/")
    replaced["data"]["heading"] = "Nowy nagłówek"
    document["commands"] = [{"command": "block.replace", "position": 0, "block": replaced}]
    document["base"] = person.get("/api/v1/sites/content-base/", document["target"]).json()["base"]
    assert post_preview(client, document).status_code == 200


def test_an_entry_draft_written_directly_by_a_key_is_held_to_the_same_hosts(
    surface: Any,
) -> None:
    from saas_core.modules.shared.sites.models import ContentCollection

    person, organization, owner, document = surface
    collection = create_collection(person, document["target"]["site_id"]).data["id"]
    entry = create_entry(person, collection, slug="linki", idempotency_key="link-entry").data["id"]
    ContentCollection.all_objects.filter(pk=collection).update(automation_policy="automated")
    client, key = connector(surface, scope="content:draft")
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        collection_id=collection,
        mode="draft_write",
        allowed_link_hosts=["partner.test"],
        created_by=owner,
    )

    def put(href: str, marker: str) -> Any:
        return client.put(
            f"/api/v1/sites/entries/{entry}/draft/",
            {
                "expected_version": 0,
                "blocks": [
                    {"block_type": "core.hero", "schema_version": 1, "data": cta(href)["data"]}
                ],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=marker,
        )

    refused = put("https://evil.test/", "entry-evil")
    assert refused.status_code == 403, refused.content
    assert refused.json()["code"] == "automation_link_host_forbidden"
    assert put("https://partner.test/", "entry-partner").status_code == 201


def test_every_link_field_in_the_block_schemas_is_walked() -> None:
    """A future `…Url` field would slip past the host check unnoticed."""
    import json
    from pathlib import Path

    from django.conf import settings

    from saas_core.modules.shared.sites.rich_content import is_link_field

    def keys(value: Any) -> Any:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, dict) and "https://" in str(child.get("pattern", "")):
                    yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    found = {
        key
        for path in Path(settings.SITE_BLOCK_CONTRACTS_PATH).glob("core.*.schema.json")
        for key in keys(json.loads(path.read_text(encoding="utf-8")))
    }
    assert found
    assert {key for key in found if not is_link_field(key)} == set()
