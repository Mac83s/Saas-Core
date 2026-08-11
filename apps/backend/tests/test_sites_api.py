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
from saas_core.modules.shared.sites.models import (
    Page,
    PageBlock,
    PageTranslation,
    PageTranslationMutation,
    PageVersion,
    Publication,
    Site,
)

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


def save_translation(
    client: APIClient,
    page_id: str,
    locale: str,
    *,
    expected_version: int,
    slug: str,
    title: str = "",
    description: str = "",
    idempotency_key: str,
    **fallback: bool,
) -> Any:
    return client.put(
        f"/api/v1/sites/pages/{page_id}/translations/{locale}/",
        {
            "expected_version": expected_version,
            "slug": slug,
            "title": title,
            "description": description,
            "social_title": "",
            "social_description": "",
            **fallback,
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


def test_translations_are_separate_idempotent_audited_records() -> None:
    client, organization, _ = sites_client(slug="sites-translations")
    site = create_site(client)
    page = create_page(client, site.data["id"])

    polish = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="oferta",
        title="Oferta",
        description="Opis oferty",
        idempotency_key="translation-pl-v1",
    )
    repeated = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="oferta",
        title="Oferta",
        description="Opis oferty",
        idempotency_key="translation-pl-v1",
    )
    changed_replay = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="oferta",
        title="Inna oferta",
        description="Opis oferty",
        idempotency_key="translation-pl-v1",
    )
    listing = client.get(f"/api/v1/sites/pages/{page.data['id']}/translations/")

    assert polish.status_code == 201
    assert polish.data["version"] == 1
    assert repeated.status_code == 200
    assert repeated.data["id"] == polish.data["id"]
    assert changed_replay.status_code == 409
    assert changed_replay.data["code"] == "sites_idempotency_conflict"
    assert listing.status_code == 200
    assert listing.data["default_locale"] == "pl"
    assert listing.data["supported_locales"] == ["pl", "en"]
    assert [item["locale"] for item in listing.data["items"]] == ["pl"]
    assert PageTranslation.all_objects.filter(organization=organization).count() == 1
    assert PageTranslationMutation.all_objects.filter(organization=organization).count() == 1
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="sites.page.translation_saved",
        ).count()
        == 1
    )


def test_localization_report_resolves_fallback_and_generates_seo_paths() -> None:
    client, _, _ = sites_client(slug="sites-localization")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    assert (
        save_translation(
            client,
            page.data["id"],
            "pl",
            expected_version=0,
            slug="uslugi",
            title="Usługi",
            description="Opis usług",
            idempotency_key="localization-pl",
        ).status_code
        == 201
    )
    assert (
        save_translation(
            client,
            page.data["id"],
            "en",
            expected_version=0,
            slug="services",
            idempotency_key="localization-en",
            allow_title_fallback=True,
            allow_description_fallback=True,
            allow_social_title_fallback=True,
            allow_social_description_fallback=True,
        ).status_code
        == 201
    )

    response = client.get(f"/api/v1/sites/{site.data['id']}/localization/")

    assert response.status_code == 200
    assert response.data["ready_to_publish"] is True
    report = response.data["pages"][0]
    polish, english = report["locales"]
    assert polish["path"] == "/uslugi/"
    assert polish["canonical_path"] == "/uslugi/"
    assert english["path"] == "/en/services/"
    assert english["canonical_path"] == "/en/services/"
    assert english["title"] == "Usługi"
    assert english["description"] == "Opis usług"
    assert english["social_title"] == "Usługi"
    assert english["social_description"] == "Opis usług"
    assert english["fallback_fields"] == [
        "title",
        "description",
        "social_title",
        "social_description",
    ]
    assert report["hreflang"] == {"pl": "/uslugi/", "en": "/en/services/"}
    assert report["x_default"] == "/uslugi/"


def test_missing_locales_and_fields_are_reported_without_blocking_base_locale() -> None:
    client, _, _ = sites_client(slug="sites-completeness")
    site = create_site(client)
    page = create_page(client, site.data["id"])

    missing_base = client.get(f"/api/v1/sites/{site.data['id']}/localization/")
    assert missing_base.data["ready_to_publish"] is False
    assert missing_base.data["pages"][0]["locales"][0]["missing_fields"] == [
        "translation",
        "slug",
        "title",
        "description",
    ]

    assert (
        save_translation(
            client,
            page.data["id"],
            "pl",
            expected_version=0,
            slug="kontakt",
            title="Kontakt",
            description="Dane kontaktowe",
            idempotency_key="completeness-pl",
        ).status_code
        == 201
    )
    report = client.get(f"/api/v1/sites/{site.data['id']}/localization/")

    assert report.data["ready_to_publish"] is True
    english = report.data["pages"][0]["locales"][1]
    assert english["complete"] is False
    assert english["path"] is None
    assert report.data["pages"][0]["hreflang"] == {"pl": "/kontakt/"}


def test_translation_slug_collision_is_scoped_by_site_and_locale() -> None:
    client, _, _ = sites_client(slug="sites-slugs")
    site = create_site(client)
    first_page = create_page(client, site.data["id"], key="first")
    second_page = create_page(
        client,
        site.data["id"],
        key="second",
        idempotency_key="page-second",
    )
    assert (
        save_translation(
            client,
            first_page.data["id"],
            "pl",
            expected_version=0,
            slug="wspolny",
            title="Pierwsza",
            description="Pierwszy opis",
            idempotency_key="slug-first-pl",
        ).status_code
        == 201
    )

    collision = save_translation(
        client,
        second_page.data["id"],
        "pl",
        expected_version=0,
        slug="wspolny",
        title="Druga",
        description="Drugi opis",
        idempotency_key="slug-second-pl",
    )
    other_locale = save_translation(
        client,
        second_page.data["id"],
        "en",
        expected_version=0,
        slug="wspolny",
        title="Second",
        description="Second description",
        idempotency_key="slug-second-en",
    )

    assert collision.status_code == 409
    assert collision.data["code"] == "translation_slug_conflict"
    assert other_locale.status_code == 201


def test_published_translation_slug_is_locked_in_service_and_database() -> None:
    client, _, _ = sites_client(slug="sites-slug-lock")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    created = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="staly",
        title="Stały",
        description="Opis",
        idempotency_key="slug-lock-v1",
    )
    translation = PageTranslation.all_objects.get(pk=created.data["id"])
    PageTranslation.all_objects.filter(pk=translation.id).update(
        slug_locked_at=translation.created_at
    )

    changed = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=1,
        slug="nowy",
        title="Nowy",
        description="Opis",
        idempotency_key="slug-lock-v2",
    )
    metadata_only = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=1,
        slug="staly",
        title="Zmieniony tytuł",
        description="Opis",
        idempotency_key="slug-lock-metadata-v2",
    )

    assert changed.status_code == 409
    assert changed.data["code"] == "translation_slug_locked"
    assert metadata_only.status_code == 201
    assert metadata_only.data["version"] == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        PageTranslation.all_objects.filter(pk=translation.id).update(slug="bypass")


def test_translation_rejects_unsupported_locale_base_fallback_and_foreign_tenant() -> None:
    client, organization, _ = sites_client(slug="sites-locale-guards")
    foreign_client, _, _ = sites_client(slug="sites-locale-foreign")
    viewer_client, _, _ = sites_client(
        slug="sites-locale-viewer",
        role_key="viewer",
    )
    disabled_client, _, _ = sites_client(
        slug="sites-locale-disabled",
        feature_enabled=False,
    )
    site = create_site(client)
    page = create_page(client, site.data["id"])

    unsupported = save_translation(
        client,
        page.data["id"],
        "de",
        expected_version=0,
        slug="angebot",
        title="Angebot",
        description="Beschreibung",
        idempotency_key="locale-de",
    )
    base_fallback = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="oferta",
        idempotency_key="locale-pl-fallback",
        allow_title_fallback=True,
    )
    foreign = save_translation(
        foreign_client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="foreign",
        title="Obce",
        description="Obcy opis",
        idempotency_key="locale-foreign",
    )
    viewer = viewer_client.get(
        f"/api/v1/sites/pages/{page.data['id']}/translations/"
    )
    disabled = disabled_client.get(
        f"/api/v1/sites/{site.data['id']}/localization/"
    )

    assert unsupported.status_code == 400
    assert unsupported.data["code"] == "unsupported_site_locale"
    assert base_fallback.status_code == 400
    assert base_fallback.data["code"] == "translation_fallback_conflict"
    assert foreign.status_code == 404
    assert foreign.data["code"] == "page_not_found"
    assert viewer.status_code == 403
    assert viewer.data["code"] == "organization_permission_denied"
    assert disabled.status_code == 403
    assert disabled.data["code"] == "entitlement_required"

    site_model = Site.all_objects.get(pk=site.data["id"])
    page_model = Page.all_objects.get(pk=page.data["id"])
    with pytest.raises(DatabaseError), transaction.atomic():
        PageTranslation.all_objects.create(
            organization=organization,
            site=site_model,
            page=page_model,
            locale="de",
            slug="angebot",
            title="Angebot",
            description="Beschreibung",
        )
