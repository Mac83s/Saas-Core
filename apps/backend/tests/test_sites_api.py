from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import MissingTenantContext
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    QuotaUsage,
    SubscriptionState,
)
from saas_core.modules.shared.sites.models import Page, PageBlock, PageVersion, Publication, Site

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
SITES_URL = "/api/v1/sites/"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def sites_client(
    *,
    slug: str,
    role_key: str = "manager",
    feature_enabled: bool = True,
    sites_limit: int = 3,
) -> tuple[APIClient, Organization, User]:
    user = User.objects.create_user(email=f"{slug}@example.test", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug,
        slug=slug,
        status=OrganizationStatus.ACTIVE,
    )
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key=role_key, organization=None),
    )
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"sites.enabled": feature_enabled},
        quotas={"sites.max": sites_limit},
        sources={"sites.enabled": {"kind": "plan"}, "sites.max": {"kind": "plan"}},
    )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    response = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    return client, organization, user


def csrf_value(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def create_site(
    client: APIClient,
    *,
    slug: str = "main-site",
    idempotency_key: str = "site-create",
) -> Any:
    return client.post(
        SITES_URL,
        {"name": slug.replace("-", " ").title(), "slug": slug, "default_locale": "pl"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def create_page(
    client: APIClient,
    site_id: str,
    *,
    key: str = "home",
    idempotency_key: str = "page-create",
) -> Any:
    return client.post(
        f"/api/v1/sites/{site_id}/pages/",
        {"name": key.title(), "key": key},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def save_draft(
    client: APIClient,
    page_id: str,
    *,
    expected_version: int,
    idempotency_key: str,
    heading: str,
) -> Any:
    return client.put(
        f"/api/v1/sites/pages/{page_id}/draft/",
        {
            "expected_version": expected_version,
            "blocks": [
                {
                    "block_type": "core.hero",
                    "schema_version": 1,
                    "data": {"heading": heading},
                },
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Treść"},
                },
            ],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def test_site_create_is_csrf_protected_idempotent_audited_and_consumes_quota() -> None:
    client, organization, _ = sites_client(slug="sites-create")
    payload = {"name": "Main", "slug": "main", "default_locale": "pl"}

    missing_csrf = client.post(
        SITES_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="site-main",
    )
    missing_idempotency = client.post(
        SITES_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    created = client.post(
        SITES_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="site-main",
    )
    repeated = client.post(
        SITES_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="site-main",
    )
    changed = client.post(
        SITES_URL,
        {**payload, "name": "Other"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="site-main",
    )
    duplicate_slug = client.post(
        SITES_URL,
        {**payload, "name": "Duplicate slug"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="site-duplicate-slug",
    )

    assert missing_csrf.status_code == 403
    assert missing_idempotency.status_code == 409
    assert missing_idempotency.data["code"] == "sites_idempotency_conflict"
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["id"] == created.data["id"]
    assert changed.status_code == 409
    assert changed.data["code"] == "sites_idempotency_conflict"
    assert duplicate_slug.status_code == 409
    assert duplicate_slug.data["code"] == "site_slug_conflict"
    assert Site.all_objects.filter(organization=organization).count() == 1
    assert QuotaUsage.all_objects.get(organization=organization).used == 1
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action="sites.site.created",
    )
    assert audit.target_id == Site.all_objects.get(organization=organization).id


def test_site_list_uses_cursor() -> None:
    client, _, _ = sites_client(slug="sites-cursor")
    assert create_site(client, slug="first", idempotency_key="first").status_code == 201
    assert create_site(client, slug="second", idempotency_key="second").status_code == 201

    first_page = client.get(SITES_URL, {"limit": 1})
    second_page = client.get(
        SITES_URL,
        {"limit": 1, "cursor": first_page.data["next_cursor"]},
    )

    assert [item["slug"] for item in first_page.data["items"]] == ["first"]
    assert first_page.data["next_cursor"] is not None
    assert [item["slug"] for item in second_page.data["items"]] == ["second"]
    assert second_page.data["next_cursor"] is None


def test_site_quota_blocks_another_site() -> None:
    client, organization, _ = sites_client(slug="sites-quota", sites_limit=1)
    first = create_site(client, slug="first", idempotency_key="first")
    exceeded = create_site(client, slug="second", idempotency_key="second")

    assert first.status_code == 201
    assert exceeded.status_code == 409
    assert exceeded.data["code"] == "quota_exceeded"
    assert Site.all_objects.filter(organization=organization).count() == 1


def test_sites_require_permission_entitlement_and_active_tenant() -> None:
    viewer, _, _ = sites_client(slug="sites-viewer", role_key="viewer")
    disabled, _, _ = sites_client(slug="sites-disabled", feature_enabled=False)

    viewer_response = viewer.get(SITES_URL)
    disabled_response = disabled.get(SITES_URL)

    assert viewer_response.status_code == 403
    assert viewer_response.data["code"] == "organization_permission_denied"
    assert disabled_response.status_code == 403
    assert disabled_response.data["code"] == "entitlement_required"

    user = User.objects.create_user(email="sites-multi@example.test", password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    for slug in ("sites-multi-one", "sites-multi-two"):
        organization = Organization.objects.create(
            name=slug,
            slug=slug,
            status=OrganizationStatus.ACTIVE,
        )
        Membership.objects.create(
            organization=organization,
            user=user,
            role=Role.objects.get(key="manager", organization=None),
        )
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").data["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        ).status_code
        == 200
    )
    missing_context = client.get(SITES_URL)
    assert missing_context.status_code == 409
    assert missing_context.data["code"] == "active_organization_required"

    with pytest.raises(MissingTenantContext):
        Site.objects.count()


def test_page_and_draft_are_tenant_scoped_versioned_and_idempotent() -> None:
    client, organization, _ = sites_client(slug="sites-draft")
    foreign_client, _, _ = sites_client(slug="sites-foreign")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    duplicate_page = create_page(
        client,
        site.data["id"],
        idempotency_key="page-duplicate-key",
    )

    assert site.status_code == 201
    assert page.status_code == 201
    assert duplicate_page.status_code == 409
    assert duplicate_page.data["code"] == "page_key_conflict"
    foreign_read = foreign_client.get(f"/api/v1/sites/{site.data['id']}/pages/")
    assert foreign_read.status_code == 404
    assert foreign_read.data["code"] == "site_not_found"

    first = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-v1",
        heading="Pierwszy",
    )
    repeated = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-v1",
        heading="Pierwszy",
    )
    changed_replay = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-v1",
        heading="Zmieniony replay",
    )
    stale = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-stale",
        heading="Nie zapisuj",
    )
    second = save_draft(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="draft-v2",
        heading="Drugi",
    )

    assert first.status_code == 201
    assert first.data["version"] == 1
    assert [block["position"] for block in first.data["blocks"]] == [0, 1]
    assert repeated.status_code == 200
    assert repeated.data["draft_id"] == first.data["draft_id"]
    assert changed_replay.status_code == 409
    assert changed_replay.data["code"] == "sites_idempotency_conflict"
    assert stale.status_code == 409
    assert stale.data["code"] == "draft_version_conflict"
    assert second.status_code == 201
    assert second.data["version"] == 2
    assert second.data["blocks"][0]["data"]["heading"] == "Drugi"
    assert PageVersion.all_objects.filter(organization=organization).count() == 2
    first_version = PageVersion.all_objects.get(id=first.data["draft_id"])
    first_block = (
        PageBlock.all_objects.filter(page_version=first_version)
        .order_by("position")
        .first()
    )
    assert first_block is not None
    assert first_block.data["heading"] == "Pierwszy"
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="sites.page.draft_saved",
        ).count()
        == 2
    )


def test_database_guards_append_only_snapshots_and_cross_tenant_links() -> None:
    client, organization, user = sites_client(slug="sites-guards")
    other_client, other_organization, _ = sites_client(slug="sites-guards-other")
    site_response = create_site(client)
    page_response = create_page(client, site_response.data["id"])
    draft_response = save_draft(
        client,
        page_response.data["id"],
        expected_version=0,
        idempotency_key="draft-guard",
        heading="Guarded",
    )
    other_site_response = create_site(other_client)
    version = PageVersion.all_objects.get(pk=draft_response.data["draft_id"])
    block = PageBlock.all_objects.get(page_version=version, position=0)

    with pytest.raises(DatabaseError), transaction.atomic():
        PageVersion.all_objects.filter(pk=version.pk).update(content_hash="0" * 64)
    with pytest.raises(DatabaseError), transaction.atomic():
        PageBlock.all_objects.filter(pk=block.pk).delete()

    site = Site.all_objects.get(pk=site_response.data["id"])
    publication = Publication.all_objects.create(
        organization=organization,
        site=site,
        sequence=1,
        snapshot_schema_version=1,
        snapshot={"site_id": str(site.id), "pages": []},
        snapshot_hash="",
        created_by=user,
        idempotency_key="publication-guard",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        Publication.all_objects.filter(pk=publication.pk).update(sequence=2)

    foreign_site = Site.all_objects.get(pk=other_site_response.data["id"])
    with pytest.raises(DatabaseError), transaction.atomic():
        Page.all_objects.create(
            organization=other_organization,
            site=site,
            name="Invalid",
            key="invalid",
            created_by=user,
            idempotency_key="invalid-link",
            request_hash="0" * 64,
        )
    assert foreign_site.organization_id == other_organization.id
