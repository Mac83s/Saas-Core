from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import set_local_organization_id
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
    QuotaReservation,
    QuotaReservationState,
    QuotaUsage,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db

PASSWORD = "Bezpieczne-Haslo-2026!"
MEDIA_URL = "/api/v1/media/"
UPLOAD_URL = "/api/v1/media/uploads/"


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def media_client(
    *,
    slug: str,
    role_key: str = "manager",
    feature_enabled: bool = True,
    storage_limit: int = 10 * 1024**2,
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
        features={"storage.enabled": feature_enabled},
        quotas={"storage.bytes": storage_limit},
        sources={
            "storage.enabled": {"kind": "plan"},
            "storage.bytes": {"kind": "plan"},
        },
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


def initiate_upload(
    client: APIClient,
    *,
    filename: str = "zdjecie.jpg",
    content_type: str = "image/jpeg",
    size: int = 2048,
    idempotency_key: str = "media-upload-one",
) -> Any:
    return client.post(
        UPLOAD_URL,
        {"filename": filename, "content_type": content_type, "size": size},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _tenant_asset_count(organization: Organization) -> int:
    with transaction.atomic():
        set_local_organization_id(organization.id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM media_mediaasset WHERE organization_id = %s",
                [str(organization.id)],
            )
            return int(cursor.fetchone()[0])


def test_upload_initiation_is_csrf_protected_idempotent_audited_and_reserves_quota() -> None:
    client, organization, _ = media_client(slug="media-create")
    payload = {"filename": "zdjecie.jpg", "content_type": "image/jpeg", "size": 2048}

    missing_csrf = client.post(
        UPLOAD_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="media-one",
    )
    missing_key = client.post(
        UPLOAD_URL,
        payload,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    created = initiate_upload(client, idempotency_key="media-one")
    repeated = initiate_upload(client, idempotency_key="media-one")
    changed = initiate_upload(client, size=4096, idempotency_key="media-one")

    assert missing_csrf.status_code == 403
    assert missing_key.status_code == 409
    assert missing_key.data["code"] == "media_idempotency_conflict"
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.data["asset"]["id"] == created.data["asset"]["id"]
    assert changed.status_code == 409
    assert changed.data["code"] == "media_idempotency_conflict"
    assert _tenant_asset_count(organization) == 1

    usage = QuotaUsage.all_objects.get(organization=organization)
    reservation = QuotaReservation.all_objects.get(organization=organization)
    assert usage.used == 0
    assert usage.reserved == 2048
    assert reservation.amount == 2048
    assert reservation.state == QuotaReservationState.RESERVED
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action="media.asset.upload_initiated",
    )
    assert audit.target_id == created.data["asset"]["id"]
    assert "upload_url" not in audit.metadata
    assert "object_key" not in audit.metadata


def test_signed_put_uses_random_tenant_key_without_original_filename() -> None:
    client, organization, _ = media_client(slug="media-signed")

    response = initiate_upload(
        client,
        filename="../../Poufne Zdjęcie.jpg",
        content_type="IMAGE/JPEG",
    )

    assert response.status_code == 201
    assert response.data["asset"]["original_filename"] == "Poufne Zdjęcie.jpg"
    assert response.data["upload_headers"] == {"Content-Type": "image/jpeg"}
    parsed = urlparse(response.data["upload_url"])
    decoded_path = unquote(parsed.path)
    assert parsed.scheme == "http"
    assert parsed.netloc == "object-storage.test"
    assert f"/test-media/{organization.id}/originals/" in decoded_path
    assert "Poufne" not in decoded_path
    assert decoded_path.endswith(".jpg")
    assert int(parse_qs(parsed.query)["X-Amz-Expires"][0]) <= 900


@pytest.mark.parametrize("content_type", ["text/html", "application/javascript", "image/svg+xml"])
def test_upload_rejects_active_content_types(content_type: str) -> None:
    client, organization, _ = media_client(
        slug=f"media-reject-{content_type.split('/')[-1].replace('+', '-')}"
    )

    response = initiate_upload(client, content_type=content_type)

    assert response.status_code == 400
    assert response.data["code"] == "unsupported_media_type"
    assert _tenant_asset_count(organization) == 0
    assert not QuotaReservation.all_objects.filter(organization=organization).exists()


def test_upload_enforces_size_permission_entitlement_and_quota() -> None:
    too_large, too_large_organization, _ = media_client(
        slug="media-too-large",
        storage_limit=20 * 1024**2,
    )
    viewer, viewer_organization, _ = media_client(slug="media-viewer", role_key="viewer")
    disabled, disabled_organization, _ = media_client(
        slug="media-disabled",
        feature_enabled=False,
    )
    quota, quota_organization, _ = media_client(slug="media-quota", storage_limit=1024)

    too_large_response = initiate_upload(too_large, size=10 * 1024**2 + 1)
    viewer_response = viewer.get(MEDIA_URL)
    disabled_response = disabled.get(MEDIA_URL)
    quota_response = initiate_upload(quota, size=2048)

    assert too_large_response.status_code == 400
    assert too_large_response.data["code"] == "media_upload_too_large"
    assert viewer_response.status_code == 403
    assert viewer_response.data["code"] == "organization_permission_denied"
    assert disabled_response.status_code == 403
    assert disabled_response.data["code"] == "entitlement_required"
    assert quota_response.status_code == 409
    assert quota_response.data["code"] == "quota_exceeded"
    for organization in (
        too_large_organization,
        viewer_organization,
        disabled_organization,
        quota_organization,
    ):
        assert _tenant_asset_count(organization) == 0


def test_media_list_and_database_rls_isolate_tenants_and_block_cross_tenant_insert() -> None:
    client, organization, user = media_client(slug="media-tenant-one")
    foreign_client, foreign_organization, _ = media_client(slug="media-tenant-two")
    created = initiate_upload(client)

    own_list = client.get(MEDIA_URL)
    foreign_list = foreign_client.get(MEDIA_URL)

    assert created.status_code == 201
    assert [item["id"] for item in own_list.data["items"]] == [created.data["asset"]["id"]]
    assert foreign_list.data["items"] == []
    role_name = f"media_rls_test_{uuid7().hex}"
    quoted_role = connection.ops.quote_name(role_name)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {quoted_role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
        cursor.execute(f"GRANT SELECT, INSERT ON media_mediaasset TO {quoted_role}")
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")
        cursor.execute("SET LOCAL app.organization_id = ''")
        cursor.execute("SELECT COUNT(*) FROM media_mediaasset")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SET LOCAL app.organization_id = %s", [str(foreign_organization.id)])
        cursor.execute("SELECT COUNT(*) FROM media_mediaasset")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization.id)])
        cursor.execute("SELECT COUNT(*) FROM media_mediaasset")
        assert cursor.fetchone()[0] == 1
        cursor.execute("RESET ROLE")
    assert _tenant_asset_count(organization) == 1
    assert _tenant_asset_count(foreign_organization) == 0

    now = timezone.now()
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization.id)])
        cursor.execute(
            """
                INSERT INTO media_mediaasset (
                    id, organization_id, created_by_id, original_filename, object_key,
                    declared_mime, detected_mime, expected_size, actual_size, sha256,
                    width, height, state, quota_reservation_key, quota_committed,
                    rejection_code, upload_expires_at, uploaded_at, scanned_at, ready_at,
                    rejected_at, deleted_at, idempotency_key, request_hash, created_at,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, '', 1, NULL, '', NULL, NULL, 'pending',
                    %s, FALSE, '', %s, NULL, NULL, NULL, NULL, NULL, %s, %s, %s, %s
                )
                """,
            [
                str(uuid7()),
                str(foreign_organization.id),
                str(user.id),
                "cross.jpg",
                f"{foreign_organization.id}/originals/{uuid7()}.jpg",
                "image/jpeg",
                f"cross:{uuid7()}",
                now,
                f"cross-{uuid7()}",
                "0" * 64,
                now,
                now,
            ],
        )
