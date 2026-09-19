from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from shutil import copytree
from typing import Any
from uuid import uuid7

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import (
    DatabaseError,
    IntegrityError,
    InternalError,
    connection,
    transaction,
)
from django.test import override_settings
from django.utils import timezone
from PIL import Image
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
    Feature,
    QuotaUsage,
    SubscriptionState,
)
from saas_core.modules.shared.media.models import (
    MediaAsset,
    MediaAssetState,
    MediaReference,
    MediaReferenceOwner,
)
from saas_core.modules.shared.media.scanner import MalwareVerdict
from saas_core.modules.shared.media.storage import ObjectMetadata, ObjectNotFoundError
from saas_core.modules.shared.sites.models import (
    NavigationItem,
    Page,
    PageBlock,
    PageTranslation,
    PageTranslationMutation,
    PageVersion,
    Publication,
    Site,
    SiteOutboxEvent,
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
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
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


class TemplateMediaStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls: list[str] = []

    def head(self, *, object_key: str) -> ObjectMetadata:
        try:
            content, content_type = self.objects[object_key]
        except KeyError as error:
            raise ObjectNotFoundError(object_key) from error
        return ObjectMetadata(content_length=len(content), content_type=content_type)

    def read(self, *, object_key: str, max_bytes: int) -> bytes:
        content = self.objects[object_key][0]
        assert len(content) <= max_bytes
        return content

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.put_calls.append(object_key)
        self.objects[object_key] = (content, content_type)

    def delete(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


class CleanTemplateMediaScanner:
    def __init__(self) -> None:
        self.calls = 0

    def scan(self, content: bytes) -> MalwareVerdict:
        assert content
        self.calls += 1
        return MalwareVerdict.CLEAN


def template_png() -> bytes:
    image = Image.new("RGB", (40, 30), color=(24, 96, 180))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


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
    media_asset_ids: list[str] | None = None,
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
            "media_asset_ids": media_asset_ids or [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def import_page_template(
    client: APIClient,
    page_id: str,
    *,
    expected_version: int,
    idempotency_key: str,
    template_id: str = "core.profile",
    template_version: int = 1,
) -> Any:
    return client.post(
        f"/api/v1/sites/pages/{page_id}/template-import/",
        {
            "expected_version": expected_version,
            "template_id": template_id,
            "template_version": template_version,
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def create_media_asset(
    organization: Organization,
    user: User,
    *,
    state: MediaAssetState = MediaAssetState.READY,
    deleted: bool = False,
) -> MediaAsset:
    asset_id = uuid7()
    return MediaAsset.all_objects.create(
        id=asset_id,
        organization=organization,
        original_filename="reference.jpg",
        object_key=f"{organization.id}/processed/{asset_id}/original.jpg",
        declared_mime="image/jpeg",
        detected_mime="image/jpeg" if state == MediaAssetState.READY else "",
        expected_size=1024,
        actual_size=1024 if state == MediaAssetState.READY else None,
        stored_size=2048 if state == MediaAssetState.READY else None,
        state=state,
        quota_reservation_key=f"media-reference:{asset_id}",
        quota_committed=state == MediaAssetState.READY,
        upload_expires_at=timezone.now() + timedelta(hours=1),
        ready_at=timezone.now() if state == MediaAssetState.READY else None,
        deleted_at=timezone.now() if deleted else None,
        deleted_by=user if deleted else None,
        deletion_idempotency_key=f"reference-delete-{asset_id}" if deleted else "",
        created_by=user,
        idempotency_key=f"reference-{asset_id}",
        request_hash="0" * 64,
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


def publish_site_request(
    client: APIClient,
    site_id: str,
    *,
    idempotency_key: str,
) -> Any:
    return client.post(
        f"/api/v1/sites/{site_id}/publications/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def rollback_site_request(
    client: APIClient,
    site_id: str,
    publication_id: str,
    *,
    idempotency_key: str,
) -> Any:
    return client.post(
        f"/api/v1/sites/{site_id}/publications/{publication_id}/rollback/",
        {},
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
            role=Role.objects.get(key="manager", organization=None, organization_type=""),
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
        PageBlock.all_objects.filter(page_version=first_version).order_by("position").first()
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


def test_page_template_import_uses_draft_versioning_and_is_tenant_scoped() -> None:
    client, organization, _ = sites_client(slug="sites-template-import")
    foreign_client, _, _ = sites_client(slug="sites-template-foreign")
    site = create_site(client)
    page = create_page(client, site.data["id"])

    imported = import_page_template(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="template-profile-v1",
    )
    repeated = import_page_template(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="template-profile-v1",
    )
    changed_replay = import_page_template(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="template-profile-v1",
        template_id="core.company",
    )
    stale = import_page_template(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="template-stale",
    )
    unknown = import_page_template(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="template-unknown",
        template_version=99,
    )
    foreign = import_page_template(
        foreign_client,
        page.data["id"],
        expected_version=1,
        idempotency_key="template-foreign",
    )

    assert imported.status_code == 201
    assert imported.data["version"] == 1
    assert [block["block_type"] for block in imported.data["blocks"]] == [
        "core.hero",
        "core.rich_text",
        "core.contact",
    ]
    assert repeated.status_code == 200
    assert repeated.data["draft_id"] == imported.data["draft_id"]
    assert changed_replay.status_code == 409
    assert changed_replay.data["code"] == "sites_idempotency_conflict"
    assert stale.status_code == 409
    assert stale.data["code"] == "draft_version_conflict"
    assert unknown.status_code == 404
    assert unknown.data["code"] == "page_template_not_found"
    assert foreign.status_code == 404
    assert foreign.data["code"] == "page_not_found"
    assert PageVersion.all_objects.filter(organization=organization).count() == 1
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="sites.page.template_imported",
        ).count()
        == 1
    )


def test_page_template_import_enforces_recipe_entitlements(tmp_path: Path) -> None:
    from saas_core.modules.shared.sites.page_templates import page_template_catalog

    client, organization, _ = sites_client(slug="sites-template-entitlement")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    Feature.objects.create(
        key="sites.templates.company",
        name="Company templates",
        module="sites",
    )
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    snapshot.features["sites.templates.company"] = False
    snapshot.save(update_fields=["features", "updated_at"])

    source = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    contracts = tmp_path / "page-templates"
    copytree(source, contracts)
    recipe_path = contracts / "core.company.v1.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["requiredEntitlements"] = [
        "sites.enabled",
        "sites.templates.company",
    ]
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    page_template_catalog.cache_clear()
    try:
        with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=contracts):
            denied = import_page_template(
                client,
                page.data["id"],
                expected_version=0,
                idempotency_key="template-company-denied",
                template_id="core.company",
            )
    finally:
        page_template_catalog.cache_clear()

    assert denied.status_code == 403
    assert denied.data["code"] == "entitlement_required"
    assert PageVersion.all_objects.filter(organization=organization).count() == 0


def test_page_template_import_materializes_approved_media_once_per_tenant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from saas_core.modules.shared.sites.page_templates import page_template_catalog

    client, organization, _ = sites_client(slug="sites-template-media")
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    snapshot.features["storage.enabled"] = True
    snapshot.quotas["storage.bytes"] = 10 * 1024**2
    snapshot.sources["storage.enabled"] = {"kind": "plan"}
    snapshot.sources["storage.bytes"] = {"kind": "plan"}
    snapshot.save(update_fields=["features", "quotas", "sources", "updated_at"])

    storage = TemplateMediaStorage()
    scanner = CleanTemplateMediaScanner()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner",
        lambda: scanner,
    )

    source = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    contracts = tmp_path / "page-templates"
    copytree(source, contracts)
    media_content = template_png()
    media_path = contracts / "assets" / "profile" / "hero.png"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(media_content)
    recipe_path = contracts / "core.profile.v1.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["media"] = [
        {
            "id": "hero",
            "source": "assets/profile/hero.png",
            "filename": "profile-hero.png",
            "contentType": "image/png",
            "sha256": hashlib.sha256(media_content).hexdigest(),
        }
    ]
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    site = create_site(client)
    first_page = create_page(client, site.data["id"])
    page_template_catalog.cache_clear()
    try:
        with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=contracts):
            stale = import_page_template(
                client,
                first_page.data["id"],
                expected_version=99,
                idempotency_key="template-media-stale",
            )
            assert stale.status_code == 409
            assert storage.objects == {}
            assert MediaAsset.all_objects.filter(organization=organization).count() == 0
            assert (
                QuotaUsage.all_objects.filter(
                    organization=organization,
                    quota_definition__key="storage.bytes",
                ).count()
                == 0
            )

            first = import_page_template(
                client,
                first_page.data["id"],
                expected_version=0,
                idempotency_key="template-media-first",
            )

            second_user = User.objects.create_user(
                email="sites-template-media-second@example.test",
                password=PASSWORD,
            )
            second_user.status = UserStatus.ACTIVE
            second_user.save()
            Membership.objects.create(
                organization=organization,
                user=second_user,
                role=Role.objects.get(key="manager", organization=None, organization_type=""),
            )
            second_client = APIClient(enforce_csrf_checks=True)
            csrf = second_client.get("/api/v1/auth/csrf/").data["csrf_token"]
            login = second_client.post(
                "/api/v1/auth/login/",
                {"email": second_user.email, "password": PASSWORD},
                format="json",
                HTTP_X_CSRFTOKEN=csrf,
            )
            assert login.status_code == 200
            second_page = create_page(
                second_client,
                site.data["id"],
                key="about",
                idempotency_key="page-create-second",
            )
            second = import_page_template(
                second_client,
                second_page.data["id"],
                expected_version=0,
                idempotency_key="template-media-second",
            )
    finally:
        page_template_catalog.cache_clear()

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(first.data["media_asset_ids"]) == 1
    assert second.data["media_asset_ids"] == first.data["media_asset_ids"]
    asset = MediaAsset.all_objects.get(organization=organization)
    assert asset.id == first.data["media_asset_ids"][0]
    assert asset.state == MediaAssetState.READY
    assert asset.quota_committed is True
    assert scanner.calls == 2
    assert len(storage.put_calls) == 8
    assert (
        MediaReference.all_objects.filter(
            organization=organization,
            asset=asset,
            owner_type=MediaReferenceOwner.PAGE_VERSION,
        ).count()
        == 2
    )
    usage = QuotaUsage.all_objects.get(
        organization=organization,
        quota_definition__key="storage.bytes",
    )
    assert usage.used == asset.stored_size


def test_page_template_approved_media_rejects_escape_and_checksum_drift(
    tmp_path: Path,
) -> None:
    from saas_core.modules.shared.sites.page_templates import page_template_catalog

    source = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    contracts = tmp_path / "page-templates"
    copytree(source, contracts)
    content = template_png()
    outside = contracts / "outside.png"
    outside.write_bytes(content)
    recipe_path = contracts / "core.profile.v1.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe["media"] = [
        {
            "id": "hero",
            "source": "assets/a/../../outside.png",
            "filename": "profile-hero.png",
            "contentType": "image/png",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    ]
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    page_template_catalog.cache_clear()
    try:
        with (
            override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=contracts),
            pytest.raises(ImproperlyConfigured, match="poza katalog assets"),
        ):
            page_template_catalog()
    finally:
        page_template_catalog.cache_clear()

    safe_path = contracts / "assets" / "profile" / "hero.png"
    safe_path.parent.mkdir(parents=True)
    safe_path.write_bytes(content)
    recipe["media"][0]["source"] = "assets/profile/hero.png"
    recipe["media"][0]["sha256"] = "0" * 64
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    page_template_catalog.cache_clear()
    try:
        with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH=contracts):
            medium = page_template_catalog().get(
                template_id="core.profile",
                version=1,
            ).media[0]
            with pytest.raises(ImproperlyConfigured, match="nieprawidłową sumę"):
                medium.read()
    finally:
        page_template_catalog.cache_clear()


def test_draft_uses_canonical_block_contracts_after_authorization() -> None:
    client, _, _ = sites_client(slug="sites-block-contracts")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    url = f"/api/v1/sites/pages/{page.data['id']}/draft/"

    def put_block(block: dict[str, Any], idempotency_key: str) -> Any:
        return client.put(
            url,
            {"expected_version": 0, "blocks": [block]},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )

    unknown_type = put_block(
        {"block_type": "custom.unknown", "schema_version": 1, "data": {}},
        "unknown-type",
    )
    unknown_version = put_block(
        {"block_type": "core.hero", "schema_version": 99, "data": {}},
        "unknown-version",
    )
    hostile_control_field = put_block(
        {
            "block_type": "core.hero",
            "schema_version": 2,
            "data": {
                "title": "Treść",
                "dangerouslySetInnerHTML": {"__html": "<script>alert(1)</script>"},
            },
        },
        "hostile-field",
    )
    javascript_url = put_block(
        {
            "block_type": "core.hero",
            "schema_version": 2,
            "data": {
                "title": "Treść",
                "action": {"label": "Kliknij", "href": "javascript:alert(1)"},
            },
        },
        "javascript-url",
    )

    assert unknown_type.status_code == 400
    assert unknown_type.data["code"] == "unknown_site_block_type"
    assert unknown_version.status_code == 400
    assert unknown_version.data["code"] == "unknown_site_block_version"
    assert hostile_control_field.status_code == 400
    assert hostile_control_field.data["code"] == "invalid_site_block_data"
    assert javascript_url.status_code == 400
    assert javascript_url.data["code"] == "invalid_site_block_data"
    assert PageVersion.all_objects.filter(page_id=page.data["id"]).count() == 0

    fixture_path = settings.SITE_BLOCK_CONTRACTS_PATH / "fixtures" / "core.hero.v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    legacy = put_block(fixture, "legacy-fixture")
    assert legacy.status_code == 201
    assert legacy.data["blocks"][0]["schema_version"] == 1

    viewer, _, _ = sites_client(slug="sites-block-viewer", role_key="viewer")
    denied = viewer.put(
        url,
        {
            "expected_version": 0,
            "blocks": [{"block_type": "custom.unknown", "schema_version": 1, "data": {}}],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(viewer),
        HTTP_IDEMPOTENCY_KEY="viewer-invalid",
    )
    assert denied.status_code == 403
    assert denied.data["code"] == "organization_permission_denied"


def test_draft_media_references_require_ready_assets_from_the_same_tenant() -> None:
    client, organization, user = sites_client(slug="sites-media-reference")
    _, foreign_organization, foreign_user = sites_client(slug="sites-media-reference-foreign")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    ready = create_media_asset(organization, user)
    pending = create_media_asset(
        organization,
        user,
        state=MediaAssetState.PENDING,
    )
    tombstoned = create_media_asset(organization, user, deleted=True)
    foreign = create_media_asset(foreign_organization, foreign_user)

    for asset, key in (
        (pending, "draft-media-pending"),
        (tombstoned, "draft-media-tombstoned"),
        (foreign, "draft-media-foreign"),
    ):
        rejected = save_draft(
            client,
            page.data["id"],
            expected_version=0,
            idempotency_key=key,
            heading="Nie zapisuj",
            media_asset_ids=[str(asset.id)],
        )
        assert rejected.status_code == 409
        assert rejected.data["code"] == "site_media_reference_unavailable"

    assert PageVersion.all_objects.filter(page_id=page.data["id"]).count() == 0
    assert MediaReference.all_objects.filter(organization=organization).count() == 0

    saved = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-media-ready",
        heading="Gotowe media",
        media_asset_ids=[str(ready.id)],
    )
    repeated = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-media-ready",
        heading="Gotowe media",
        media_asset_ids=[str(ready.id)],
    )
    changed_replay = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="draft-media-ready",
        heading="Gotowe media",
        media_asset_ids=[],
    )
    preview = client.get(f"/api/v1/sites/pages/{page.data['id']}/preview/{saved.data['draft_id']}/")

    assert saved.status_code == 201
    assert saved.data["media_asset_ids"] == [ready.id]
    assert repeated.status_code == 200
    assert repeated.data["media_asset_ids"] == [ready.id]
    assert changed_replay.status_code == 409
    assert changed_replay.data["code"] == "sites_idempotency_conflict"
    assert preview.status_code == 200
    assert preview.data["media_asset_ids"] == [ready.id]
    reference = MediaReference.all_objects.get(
        organization=organization,
        owner_type=MediaReferenceOwner.PAGE_VERSION,
        owner_id=saved.data["draft_id"],
    )
    assert reference.asset_id == ready.id
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action="sites.page.draft_saved",
        target_id=saved.data["draft_id"],
    )
    assert audit.metadata["media_asset_count"] == 1


def test_preview_requires_session_and_explicit_tenant_scoped_version() -> None:
    client, _, _ = sites_client(slug="sites-preview")
    foreign_client, _, _ = sites_client(slug="sites-preview-foreign")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    first = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="preview-v1",
        heading="Wersja pierwsza",
    )
    second = save_draft(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="preview-v2",
        heading="Wersja druga",
    )
    preview_url = f"/api/v1/sites/pages/{page.data['id']}/preview/{first.data['draft_id']}/"

    anonymous = APIClient().get(preview_url)
    preview = client.get(preview_url)
    foreign = foreign_client.get(preview_url)

    assert second.status_code == 201
    assert anonymous.status_code == 403
    assert preview.status_code == 200
    assert preview.data["draft_id"] == first.data["draft_id"]
    assert preview.data["version"] == 1
    assert preview.data["blocks"][0]["data"]["heading"] == "Wersja pierwsza"
    assert foreign.status_code == 404
    assert foreign.data["code"] == "page_version_not_found"


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
    outbox = SiteOutboxEvent.all_objects.create(
        organization=organization,
        publication=publication,
        event_type="sites.site.published",
        version=1,
        actor=user,
        correlation_id=uuid7(),
        causation_id=f"sites-publish:{publication.id}",
        payload={"publication_id": str(publication.id)},
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        Publication.all_objects.filter(pk=publication.pk).update(sequence=2)
    with pytest.raises(DatabaseError), transaction.atomic():
        SiteOutboxEvent.all_objects.filter(pk=outbox.pk).update(payload={"changed": True})

    role_name = f"sites_outbox_rls_{uuid7().hex}"
    quoted_role = connection.ops.quote_name(role_name)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {quoted_role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
        cursor.execute(f"GRANT SELECT ON sites_siteoutboxevent TO {quoted_role}")
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")
        cursor.execute("SET LOCAL app.organization_id = ''")
        cursor.execute("SELECT COUNT(*) FROM sites_siteoutboxevent")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SET LOCAL app.organization_id = %s", [str(other_organization.id)])
        cursor.execute("SELECT COUNT(*) FROM sites_siteoutboxevent")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization.id)])
        cursor.execute("SELECT COUNT(*) FROM sites_siteoutboxevent")
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")

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


def test_publication_requires_complete_draft_translation_and_still_ready_media() -> None:
    client, organization, user = sites_client(
        slug="sites-publication-not-ready",
        role_key="owner",
    )
    site = create_site(client)
    page = create_page(client, site.data["id"])
    manager, _, _ = sites_client(slug="sites-publication-manager")
    foreign_owner, _, _ = sites_client(
        slug="sites-publication-foreign-owner",
        role_key="owner",
    )

    denied = publish_site_request(
        manager,
        site.data["id"],
        idempotency_key="publish-manager-denied",
    )
    foreign = publish_site_request(
        foreign_owner,
        site.data["id"],
        idempotency_key="publish-foreign-denied",
    )
    assert denied.status_code == 403
    assert denied.data["code"] == "organization_permission_denied"
    assert foreign.status_code == 404
    assert foreign.data["code"] == "site_not_found"

    missing_draft = publish_site_request(
        client,
        site.data["id"],
        idempotency_key="publish-missing-draft",
    )
    assert missing_draft.status_code == 409
    assert missing_draft.data["code"] == "site_publication_not_ready"

    asset = create_media_asset(organization, user)
    draft = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="publish-draft",
        heading="Publikacja",
        media_asset_ids=[str(asset.id)],
    )
    missing_translation = publish_site_request(
        client,
        site.data["id"],
        idempotency_key="publish-missing-translation",
    )
    assert draft.status_code == 201
    assert missing_translation.status_code == 409
    assert missing_translation.data["code"] == "site_publication_not_ready"

    translation = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="publikacja",
        title="Publikacja",
        description="Opis publikacji",
        idempotency_key="publish-translation",
    )
    MediaAsset.all_objects.filter(pk=asset.id).update(
        deleted_at=timezone.now(),
        deleted_by=user,
        deletion_idempotency_key=f"publication-delete-{asset.id}",
    )
    unavailable_media = publish_site_request(
        client,
        site.data["id"],
        idempotency_key="publish-tombstoned-media",
    )

    assert translation.status_code == 201
    assert unavailable_media.status_code == 409
    assert unavailable_media.data["code"] == "site_media_reference_unavailable"
    assert Publication.all_objects.filter(organization=organization).count() == 0
    assert SiteOutboxEvent.all_objects.filter(organization=organization).count() == 0
    assert Site.all_objects.get(pk=site.data["id"]).current_publication_id is None


def test_publication_is_atomic_idempotent_and_emits_signed_outbox(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, user = sites_client(
        slug="sites-publication-ready",
        role_key="owner",
    )
    site = create_site(client)
    page = create_page(client, site.data["id"])
    asset = create_media_asset(organization, user)
    draft = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="publication-draft-v1",
        heading="Wersja opublikowana",
        media_asset_ids=[str(asset.id)],
    )
    translation = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Strona startowa",
        idempotency_key="publication-translation-pl",
    )
    delayed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.tasks.publish_site_outbox_event_task.delay",
        lambda event_id, contract: delayed.append((event_id, contract)),
    )

    missing_csrf = client.post(
        f"/api/v1/sites/{site.data['id']}/publications/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="publication-no-csrf",
    )
    with django_capture_on_commit_callbacks(execute=True):
        published = publish_site_request(
            client,
            site.data["id"],
            idempotency_key="publication-ready",
        )
    with django_capture_on_commit_callbacks(execute=True):
        repeated = publish_site_request(
            client,
            site.data["id"],
            idempotency_key="publication-ready",
        )

    assert draft.status_code == 201
    assert translation.status_code == 201
    assert missing_csrf.status_code == 403
    assert published.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["id"] == published.data["id"]
    # Pending delivery is deliberately rescheduled on an idempotent replay so
    # a transient broker failure cannot strand a committed outbox event.
    assert len(delayed) == 2

    publication = Publication.all_objects.get(pk=published.data["id"])
    site_record = Site.all_objects.get(pk=site.data["id"])
    translation_record = PageTranslation.all_objects.get(pk=translation.data["id"])
    assert site_record.current_publication_id == publication.id
    assert translation_record.slug_locked_at is not None
    assert publication.snapshot["site_id"] == str(site_record.id)
    assert publication.snapshot["pages"][0]["version_id"] == str(draft.data["draft_id"])
    assert publication.snapshot["pages"][0]["page_type"] == "landing"
    assert publication.snapshot["pages"][0]["media_asset_ids"] == [str(asset.id)]
    assert publication.snapshot["pages"][0]["locales"][0]["canonical_path"] == "/start/"
    assert publication.snapshot_hash == published.data["snapshot_hash"]
    assert (
        MediaReference.all_objects.filter(
            organization=organization,
            owner_type=MediaReferenceOwner.PUBLICATION,
            owner_id=publication.id,
            asset=asset,
        ).count()
        == 1
    )
    event = SiteOutboxEvent.all_objects.get(publication=publication)
    assert event.published_at is None
    assert event.payload["snapshot_hash"] == publication.snapshot_hash
    assert event.payload.get("object_key") is None
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="sites.site.published",
            target_id=publication.id,
        ).count()
        == 1
    )

    from saas_core.modules.shared.sites.tasks import publish_site_outbox_event_task

    publish_site_outbox_event_task(str(uuid7()), delayed[0][1])
    event.refresh_from_db()
    assert event.published_at is None
    publish_site_outbox_event_task(*delayed[0])
    publish_site_outbox_event_task(*delayed[1])
    event.refresh_from_db()
    assert event.published_at is not None

    newer_draft = save_draft(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="publication-draft-v2",
        heading="Nowszy, nieopublikowany draft",
        media_asset_ids=[str(asset.id)],
    )
    publication.refresh_from_db()
    site_record.refresh_from_db()
    assert newer_draft.status_code == 201
    assert publication.snapshot["pages"][0]["version_id"] == str(draft.data["draft_id"])
    assert site_record.current_publication_id == publication.id


def test_publication_history_and_rollback_preserve_newer_draft_and_media() -> None:
    client, organization, user = sites_client(
        slug="sites-publication-rollback",
        role_key="owner",
    )
    site = create_site(client)
    page = create_page(client, site.data["id"])
    asset = create_media_asset(organization, user)
    first_draft = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="rollback-draft-v1",
        heading="Pierwsza wersja",
        media_asset_ids=[str(asset.id)],
    )
    save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Opis",
        idempotency_key="rollback-translation",
    )
    first = publish_site_request(
        client,
        site.data["id"],
        idempotency_key="rollback-publication-v1",
    )
    second_draft = save_draft(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="rollback-draft-v2",
        heading="Nowszy draft",
        media_asset_ids=[str(asset.id)],
    )
    second = publish_site_request(
        client,
        site.data["id"],
        idempotency_key="rollback-publication-v2",
    )
    MediaAsset.all_objects.filter(pk=asset.id).update(
        deleted_at=timezone.now(),
        deleted_by=user,
        deletion_idempotency_key=f"rollback-delete-{asset.id}",
    )

    missing_csrf = client.post(
        f"/api/v1/sites/{site.data['id']}/publications/{first.data['id']}/rollback/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rollback-missing-csrf",
    )
    rolled_back = rollback_site_request(
        client,
        site.data["id"],
        first.data["id"],
        idempotency_key="rollback-to-first",
    )
    repeated = rollback_site_request(
        client,
        site.data["id"],
        first.data["id"],
        idempotency_key="rollback-to-first",
    )
    conflicting_key = rollback_site_request(
        client,
        site.data["id"],
        second.data["id"],
        idempotency_key="rollback-to-first",
    )
    current_target = rollback_site_request(
        client,
        site.data["id"],
        rolled_back.data["id"],
        idempotency_key="rollback-current",
    )
    history = client.get(f"/api/v1/sites/{site.data['id']}/publications/?limit=2")
    next_page = client.get(
        f"/api/v1/sites/{site.data['id']}/publications/",
        {"limit": 2, "cursor": history.data["next_cursor"]},
    )

    manager, _, _ = sites_client(slug="sites-rollback-manager")
    foreign_owner, _, _ = sites_client(
        slug="sites-rollback-foreign",
        role_key="owner",
    )
    denied = rollback_site_request(
        manager,
        site.data["id"],
        first.data["id"],
        idempotency_key="rollback-manager",
    )
    foreign = rollback_site_request(
        foreign_owner,
        site.data["id"],
        first.data["id"],
        idempotency_key="rollback-foreign",
    )

    assert first_draft.status_code == 201
    assert second_draft.status_code == 201
    assert first.status_code == 201
    assert second.status_code == 201
    assert missing_csrf.status_code == 403
    assert rolled_back.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["id"] == rolled_back.data["id"]
    assert conflicting_key.status_code == 409
    assert conflicting_key.data["code"] == "sites_idempotency_conflict"
    assert current_target.status_code == 409
    assert current_target.data["code"] == "site_publication_already_current"
    assert denied.status_code == 403
    assert denied.data["code"] == "organization_permission_denied"
    assert foreign.status_code == 404
    assert foreign.data["code"] == "site_not_found"

    rollback_record = Publication.all_objects.get(pk=rolled_back.data["id"])
    first_record = Publication.all_objects.get(pk=first.data["id"])
    page_record = Page.all_objects.get(pk=page.data["id"])
    site_record = Site.all_objects.get(pk=site.data["id"])
    assert rollback_record.sequence == 3
    assert rollback_record.source_publication_id == first_record.id
    assert rollback_record.snapshot == first_record.snapshot
    assert rollback_record.snapshot_hash == first_record.snapshot_hash
    assert site_record.current_publication_id == rollback_record.id
    assert page_record.current_draft_id == second_draft.data["draft_id"]
    assert page_record.version == 2
    assert (
        MediaReference.all_objects.filter(
            organization=organization,
            owner_type=MediaReferenceOwner.PUBLICATION,
            owner_id=rollback_record.id,
            asset=asset,
        ).count()
        == 1
    )
    assert history.status_code == 200
    assert [item["sequence"] for item in history.data["items"]] == [3, 2]
    assert history.data["items"][0]["source_publication_id"] == first.data["id"]
    assert history.data["items"][0]["created_by"]["email"] == user.email
    assert next_page.status_code == 200
    assert [item["sequence"] for item in next_page.data["items"]] == [1]
    assert SiteOutboxEvent.all_objects.filter(publication=rollback_record).count() == 1
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="sites.site.rolled_back",
            target_id=rollback_record.id,
        ).count()
        == 1
    )


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
    viewer = viewer_client.get(f"/api/v1/sites/pages/{page.data['id']}/translations/")
    disabled = disabled_client.get(f"/api/v1/sites/{site.data['id']}/localization/")

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


def test_publication_snapshot_carries_only_reachable_navigation() -> None:
    client, organization, user = sites_client(slug="nav-snapshot", role_key="owner")
    site = create_site(client)
    site_id = site.data["id"]
    home = create_page(client, site_id, key="home", idempotency_key="nav-home")
    offer = create_page(client, site_id, key="oferta", idempotency_key="nav-offer")
    hidden = create_page(client, site_id, key="ukryta", idempotency_key="nav-hidden")
    for index, page in enumerate((home, offer, hidden)):
        save_draft(
            client,
            page.data["id"],
            expected_version=0,
            idempotency_key=f"nav-draft-{index}",
            heading=f"Nagłówek {index}",
        )
        save_translation(
            client,
            page.data["id"],
            "pl",
            expected_version=0,
            slug=page.data["key"],
            title=f"Tytuł {index}",
            description="Opis",
            idempotency_key=f"nav-translation-{index}",
        )

    site_row = Site.all_objects.get(pk=site_id)
    parent = NavigationItem.all_objects.create(
        organization=organization,
        site=site_row,
        page=Page.all_objects.get(pk=home.data["id"]),
        position=0,
    )
    NavigationItem.all_objects.create(
        organization=organization,
        site=site_row,
        page=Page.all_objects.get(pk=offer.data["id"]),
        parent=parent,
        position=1,
    )
    # Hidden entries keep their place in the tree but never reach the public
    # snapshot, and their children go with them rather than being promoted.
    invisible = NavigationItem.all_objects.create(
        organization=organization,
        site=site_row,
        page=Page.all_objects.get(pk=hidden.data["id"]),
        position=2,
        visible=False,
    )

    published = publish_site_request(client, site_id, idempotency_key="nav-publish")

    assert published.status_code == 201
    snapshot = Publication.all_objects.get(pk=published.data["id"]).snapshot
    entries = snapshot["navigation"]
    assert [entry["page_id"] for entry in entries] == [
        str(home.data["id"]),
        str(offer.data["id"]),
    ]
    assert entries[1]["parent_page_id"] == str(home.data["id"])
    assert str(invisible.page_id) not in {entry["page_id"] for entry in entries}


def test_navigation_item_cannot_point_outside_its_site() -> None:
    client, organization, _ = sites_client(slug="nav-guard", role_key="owner")
    first = create_site(client)
    second = create_site(client, slug="second-site", idempotency_key="nav-second")
    stranger = create_page(
        client, second.data["id"], key="obca", idempotency_key="nav-stranger"
    )

    # The database enforces this too, so a bug in a service cannot quietly link
    # a menu to another site's page.
    with pytest.raises((ValidationError, IntegrityError, InternalError)):
        NavigationItem.all_objects.create(
            organization=organization,
            site=Site.all_objects.get(pk=first.data["id"]),
            page=Page.all_objects.get(pk=stranger.data["id"]),
            position=0,
        )


def navigation_request(
    client: APIClient,
    site_id: str,
    *,
    expected_version: int,
    items: list[dict[str, Any]],
) -> Any:
    return client.put(
        f"/api/v1/sites/{site_id}/navigation/",
        {"expected_version": expected_version, "items": items},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )


def test_navigation_saves_a_tree_and_guards_its_own_version() -> None:
    client, _, _ = sites_client(slug="nav-api", role_key="owner")
    site = create_site(client)
    site_id = site.data["id"]
    home = create_page(client, site_id, key="home", idempotency_key="nav-api-home")
    offer = create_page(client, site_id, key="oferta", idempotency_key="nav-api-offer")

    empty = client.get(f"/api/v1/sites/{site_id}/navigation/")
    saved = navigation_request(
        client,
        site_id,
        expected_version=0,
        items=[
            {"page_id": home.data["id"], "parent_page_id": None, "visible": True},
            {
                "page_id": offer.data["id"],
                "parent_page_id": home.data["id"],
                "visible": False,
            },
        ],
    )
    # The version the caller read is already spent; replaying it must not
    # silently overwrite whatever the other editor saved in between.
    stale = navigation_request(
        client,
        site_id,
        expected_version=0,
        items=[{"page_id": home.data["id"], "parent_page_id": None}],
    )
    reread = client.get(f"/api/v1/sites/{site_id}/navigation/")

    assert empty.status_code == 200
    assert empty.data["version"] == 0
    assert empty.data["items"] == []
    assert saved.status_code == 200
    assert saved.data["version"] == 1
    assert saved.data["items"] == [
        {"page_id": str(home.data["id"]), "parent_page_id": None, "visible": True},
        {
            "page_id": str(offer.data["id"]),
            "parent_page_id": str(home.data["id"]),
            "visible": False,
        },
    ]
    assert stale.status_code == 409
    assert stale.data["code"] == "navigation_version_conflict"
    assert reread.data["items"] == saved.data["items"]


def test_navigation_rejects_trees_the_renderer_could_not_show() -> None:
    client, _, _ = sites_client(slug="nav-tree", role_key="owner")
    site = create_site(client)
    site_id = site.data["id"]
    home = create_page(client, site_id, key="home", idempotency_key="nav-tree-home")
    offer = create_page(client, site_id, key="oferta", idempotency_key="nav-tree-offer")
    deep = create_page(client, site_id, key="deep", idempotency_key="nav-tree-deep")
    other_site = create_site(client, slug="other", idempotency_key="nav-tree-other")
    stranger = create_page(
        client, other_site.data["id"], key="obca", idempotency_key="nav-tree-stranger"
    )

    duplicate = navigation_request(
        client,
        site_id,
        expected_version=0,
        items=[{"page_id": home.data["id"]}, {"page_id": home.data["id"]}],
    )
    foreign = navigation_request(
        client,
        site_id,
        expected_version=0,
        items=[{"page_id": stranger.data["id"]}],
    )
    self_parent = navigation_request(
        client,
        site_id,
        expected_version=0,
        items=[{"page_id": home.data["id"], "parent_page_id": home.data["id"]}],
    )
    # Only one level of nesting is rendered, so a grandchild would publish a
    # link the public menu cannot show.
    too_deep = navigation_request(
        client,
        site_id,
        expected_version=0,
        items=[
            {"page_id": home.data["id"]},
            {"page_id": offer.data["id"], "parent_page_id": home.data["id"]},
            {"page_id": deep.data["id"], "parent_page_id": offer.data["id"]},
        ],
    )

    for response in (duplicate, foreign, self_parent, too_deep):
        assert response.status_code == 400
        assert response.data["code"] == "navigation_invalid_tree"
    assert Site.all_objects.get(pk=site_id).navigation_version == 0


def grant_for_site(organization: Any, user: Any, site_id: Any) -> Any:
    """Grants a synthetic credential one whole site, and returns its id."""
    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    credential_id = uuid7()
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        site_id=site_id,
        mode="autonomous",
        expires_at=timezone.now() + timedelta(days=7),
        max_changes_per_day=50,
        max_payload_bytes=100_000,
        created_by=user,
    )
    return credential_id


def automation_context(
    organization_id: Any,
    actor_id: Any,
    *,
    credential_id: Any = None,
    may_publish: bool = False,
) -> Any:
    """A principal that is not a signed-in person — what an integration gets.

    `may_publish` mirrors the `content:publish` scope: without it the key cannot
    reach a publication at all, so a test about the *policy* has to grant it.
    """
    from saas_core.modules.core.organizations.context import TenantContext

    permissions = {"site.content.edit"}
    if may_publish:
        permissions.add("site.publish")
    return TenantContext(
        organization_id=organization_id,
        membership_id=uuid7(),
        actor_id=actor_id,
        role_key="integration",
        permissions=frozenset(permissions),
        principal_kind="api_key",
        credential_id=credential_id,
    )


def membership_context(organization: Any, user: Any) -> Any:
    """A signed-in person: the policy and the lock never apply to them."""
    from saas_core.modules.core.organizations.context import TenantContext

    return TenantContext(
        organization_id=organization.id,
        membership_id=uuid7(),
        actor_id=user.id,
        role_key="owner",
        permissions=frozenset({"site.content.edit"}),
    )


def test_automation_may_only_write_pages_the_operator_opened() -> None:
    from saas_core.modules.shared.sites.models import PageAutomationPolicy
    from saas_core.modules.shared.sites.services import (
        PageAutomationForbidden,
        assert_page_writable,
    )

    client, organization, user = sites_client(slug="policy", role_key="owner")
    site = create_site(client)
    page_response = create_page(client, site.data["id"], idempotency_key="policy-page")
    page = Page.all_objects.get(pk=page_response.data["id"])
    # The grant says which site this credential was hired for; the policy is a
    # separate gate. This test isolates the policy, so the grant is present.
    context = automation_context(
        organization.id,
        user.id,
        credential_id=grant_for_site(organization, user, site.data["id"]),
    )

    # Default is manual: an integration cannot grant itself a page.
    assert page.automation_policy == PageAutomationPolicy.MANUAL
    with pytest.raises(PageAutomationForbidden):
        assert_page_writable(page, context)

    page.automation_policy = PageAutomationPolicy.AUTOMATED
    page.save(update_fields=["automation_policy"])
    assert_page_writable(page, context)


def test_manual_editing_lock_holds_the_automation_off_until_it_lapses() -> None:
    from saas_core.modules.shared.sites.models import PageAutomationPolicy
    from saas_core.modules.shared.sites.services import (
        PageEditingLocked,
        assert_page_writable,
    )

    client, organization, user = sites_client(slug="lock", role_key="owner")
    site = create_site(client)
    page_response = create_page(client, site.data["id"], idempotency_key="lock-page")
    page = Page.all_objects.get(pk=page_response.data["id"])
    page.automation_policy = PageAutomationPolicy.AUTOMATED
    page.editing_locked_until = timezone.now() + timedelta(minutes=5)
    page.editing_locked_by = user
    page.save(
        update_fields=[
            "automation_policy",
            "editing_locked_until",
            "editing_locked_by",
        ]
    )
    context = automation_context(
        organization.id,
        user.id,
        credential_id=grant_for_site(organization, user, site.data["id"]),
    )

    with pytest.raises(PageEditingLocked) as locked:
        assert_page_writable(page, context)
    # The refusal carries when to come back, so the integration can wait rather
    # than retry blindly.
    assert page.editing_locked_until.isoformat() in str(locked.value.detail)

    # A person is never blocked by the lock, and it lapses on its own.
    assert_page_writable(page, membership_context(organization, user))
    page.editing_locked_until = timezone.now() - timedelta(seconds=1)
    page.save(update_fields=["editing_locked_until"])
    assert_page_writable(page, context)


def test_site_publication_is_never_an_automations_to_make() -> None:
    """Publishing the site would otherwise ship the automation's own proposal:
    the page policy governs the draft, but a publication is site-wide."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.models import (
        ContentAutomationGrant,
        Page,
        PageAutomationPolicy,
    )
    from saas_core.modules.shared.sites.services import (
        PersonRequired,
        publish_site,
    )

    client, organization, user = sites_client(slug="proposal-publish", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="proposal-draft",
        heading="Gotowa strona",
    )
    save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Strona startowa",
        idempotency_key="proposal-translation-pl",
    )
    credential_id = uuid7()
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        site_id=site.data["id"],
        mode="autonomous",
        expires_at=timezone.now() + timedelta(days=7),
        max_changes_per_day=50,
        max_payload_bytes=100_000,
        created_by=user,
    )
    Page.all_objects.filter(site_id=site.data["id"]).update(
        automation_policy=PageAutomationPolicy.PROPOSED
    )

    with (
        activate_tenant_context(
            automation_context(
                organization.id,
                user.id,
                credential_id=credential_id,
                may_publish=True,
            )
        ),
        pytest.raises(PersonRequired),
    ):
        publish_site(site_id=site.data["id"], idempotency_key="automation-publishes")


def test_contract_directories_are_checked_before_the_workers_start() -> None:
    """A contract directory that never reached the image used to surface as a
    500 the first time somebody clicked, long after the deploy said success."""
    from django.test import override_settings

    from saas_core.modules.shared.sites.apps import check_content_contracts

    assert check_content_contracts() == []

    with override_settings(PAGE_TEMPLATE_CONTRACTS_PATH="/does/not/exist"):
        errors = check_content_contracts()
    assert [error.id for error in errors] == ["sites.E002"]


def test_section_layout_roundtrip_and_invalid_layout_rejected() -> None:
    client, _, _ = sites_client(slug="section-layout")
    site = create_site(client)
    page = create_page(client, site.data["id"])
    url = f"/api/v1/sites/pages/{page.data['id']}/draft/"
    data = {
        "title": "Actual offer",
        "layout": "specification",
        "items": [
            {"title": "Device", "text": "Actual scope"},
        ],
    }
    response = client.put(
        url,
        {
            "expected_version": 0,
            "blocks": [
                {"block_type": "core.feature_list", "schema_version": 2, "data": data},
            ],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="section-layout-save",
    )
    assert response.status_code == 201
    assert response.data["blocks"][0]["data"] == data
    saved = client.get(url)
    assert saved.status_code == 200
    assert saved.data["blocks"][0]["data"] == data
    invalid = client.put(
        url,
        {
            "expected_version": 1,
            "blocks": [
                {
                    "block_type": "core.feature_list",
                    "schema_version": 2,
                    "data": {**data, "layout": "arbitrary-code"},
                },
            ],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="section-layout-invalid",
    )
    assert invalid.status_code == 400
    assert invalid.data["code"] == "invalid_site_block_data"
    assert PageVersion.all_objects.filter(page_id=page.data["id"]).count() == 1


def test_all_section_seeds_validate_in_backend() -> None:
    from saas_core.modules.shared.sites.block_contracts import validate_site_block
    from saas_core.modules.shared.sites.page_templates import page_template_catalog

    catalog = json.loads(
        (settings.SITE_BLOCK_CONTRACTS_PATH / "section-templates.v1.json").read_text()
    )
    for template in catalog["templates"]:
        for data in template["seed"].values():
            validate_site_block(
                block_type=template["blockType"],
                schema_version=template["schemaVersion"],
                data=data,
            )
    recipe = page_template_catalog().get(template_id="core.service_landing", version=1)
    assert [block["data"].get("layout") for block in recipe.blocks] == [
        "centered",
        "cards",
        "accordion",
        None,
    ]
