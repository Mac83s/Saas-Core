from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.tasks import tenant_task_context
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    QuotaReservation,
    QuotaReservationState,
    QuotaUsage,
    SubscriptionState,
)
from saas_core.modules.shared.billing.quotas import commit_quota, reserve_quota
from saas_core.modules.shared.media.images import ProcessedImage, ProcessedVariant
from saas_core.modules.shared.media.models import (
    MediaAsset,
    MediaAssetState,
    MediaReference,
    MediaReferenceOwner,
)
from saas_core.modules.shared.media.scanner import (
    MalwareScannerUnavailable,
    MalwareVerdict,
)
from saas_core.modules.shared.media.services import process_media_asset
from saas_core.modules.shared.media.storage import ObjectMetadata, ObjectNotFoundError

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
        role=Role.objects.get(key=role_key, organization=None, organization_type=""),
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


def complete_upload(client: APIClient, asset_id: str) -> Any:
    return client.post(
        f"{UPLOAD_URL}{asset_id}/complete/",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )


def delete_asset(
    client: APIClient,
    asset_id: str,
    *,
    idempotency_key: str,
) -> Any:
    return client.delete(
        f"{MEDIA_URL}{asset_id}/",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def create_ready_asset(
    organization: Organization,
    user: User,
    *,
    suffix: str,
) -> MediaAsset:
    membership = Membership.objects.select_related("organization", "role").get(
        organization=organization,
        user=user,
    )
    context = context_from_membership(membership)
    quota_key = f"media-cleanup:{suffix}:{uuid7()}"
    with activate_tenant_context(context):
        reserve_quota(
            "storage.bytes",
            amount=30,
            idempotency_key=quota_key,
        )
        commit_quota(quota_key)
    asset_id = uuid7()
    return MediaAsset.all_objects.create(
        id=asset_id,
        organization=organization,
        original_filename=f"{suffix}.jpg",
        object_key=f"{organization.id}/processed/{asset_id}/original.jpg",
        source_object_key=f"{organization.id}/originals/{asset_id}.jpg",
        declared_mime="image/jpeg",
        detected_mime="image/jpeg",
        expected_size=10,
        actual_size=10,
        stored_size=30,
        sha256="a" * 64,
        width=10,
        height=10,
        state=MediaAssetState.READY,
        quota_reservation_key=quota_key,
        quota_committed=True,
        variants={
            "preview": {
                "object_key": f"{organization.id}/variants/{asset_id}/preview.webp",
                "content_type": "image/webp",
                "size": 10,
                "width": 10,
                "height": 10,
            },
            "thumbnail": {
                "object_key": f"{organization.id}/variants/{asset_id}/thumbnail.webp",
                "content_type": "image/webp",
                "size": 10,
                "width": 10,
                "height": 10,
            },
        },
        upload_expires_at=timezone.now() - timedelta(seconds=1),
        uploaded_at=timezone.now(),
        scanned_at=timezone.now(),
        ready_at=timezone.now(),
        created_by=user,
        idempotency_key=f"ready-{suffix}-{uuid7()}",
        request_hash="b" * 64,
    )


class HeadStorage:
    def __init__(self, metadata: ObjectMetadata | None) -> None:
        self.metadata = metadata
        self.calls: list[str] = []

    def head(self, *, object_key: str) -> ObjectMetadata:
        self.calls.append(object_key)
        if self.metadata is None:
            raise ObjectNotFoundError(object_key)
        return self.metadata


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls: list[str] = []
        self.delete_calls: list[str] = []

    def head(self, *, object_key: str) -> ObjectMetadata:
        try:
            content, content_type = self.objects[object_key]
        except KeyError as error:
            raise ObjectNotFoundError(object_key) from error
        return ObjectMetadata(content_length=len(content), content_type=content_type)

    def read(self, *, object_key: str, max_bytes: int) -> bytes:
        try:
            content = self.objects[object_key][0]
        except KeyError as error:
            raise ObjectNotFoundError(object_key) from error
        assert len(content) <= max_bytes
        return content

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.put_calls.append(object_key)
        self.objects[object_key] = (content, content_type)

    def delete(self, *, object_key: str) -> None:
        self.delete_calls.append(object_key)
        self.objects.pop(object_key, None)


class VerdictScanner:
    def __init__(self, verdict: MalwareVerdict) -> None:
        self.verdict = verdict
        self.calls = 0

    def scan(self, content: bytes) -> MalwareVerdict:
        assert content
        self.calls += 1
        return self.verdict


class UnavailableScanner:
    def scan(self, content: bytes) -> MalwareVerdict:
        raise MalwareScannerUnavailable from None


def encoded_image(
    image_format: str,
    *,
    size: tuple[int, int] = (640, 480),
    with_exif: bool = False,
) -> bytes:
    image = Image.new("RGB", size, color=(24, 96, 180))
    output = BytesIO()
    save_options: dict[str, object] = {}
    if with_exif:
        exif = Image.Exif()
        exif[0x010E] = "private fixture metadata"
        save_options["exif"] = exif
    image.save(output, format=image_format, **save_options)
    return output.getvalue()


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


def test_upload_completion_is_csrf_protected_idempotent_audited_and_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, organization, _ = media_client(slug="media-complete")
    foreign_client, _, _ = media_client(slug="media-complete-foreign")
    created = initiate_upload(client)
    asset_id = created.data["asset"]["id"]
    storage = HeadStorage(
        ObjectMetadata(content_length=2048, content_type="image/jpeg; charset=binary")
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )

    missing_csrf = client.post(f"{UPLOAD_URL}{asset_id}/complete/")
    foreign = complete_upload(foreign_client, asset_id)
    completed = complete_upload(client, asset_id)
    repeated = complete_upload(client, asset_id)

    assert missing_csrf.status_code == 403
    assert foreign.status_code == 404
    assert foreign.data["code"] == "media_asset_not_found"
    assert completed.status_code == 200
    assert completed.data["state"] == MediaAssetState.UPLOADED
    assert completed.data["actual_size"] == 2048
    assert repeated.status_code == 200
    assert repeated.data == completed.data
    assert len(storage.calls) == 1
    asset = MediaAsset.all_objects.get(pk=asset_id, organization=organization)
    assert asset.uploaded_at is not None
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="media.asset.upload_completed",
            target_id=asset_id,
        ).count()
        == 1
    )


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        (None, "media_upload_missing"),
        (
            ObjectMetadata(content_length=2049, content_type="image/jpeg"),
            "media_upload_metadata_mismatch",
        ),
        (
            ObjectMetadata(content_length=2048, content_type="text/html"),
            "media_upload_metadata_mismatch",
        ),
    ],
)
def test_upload_completion_rejects_missing_or_mismatched_object_without_state_change(
    monkeypatch: pytest.MonkeyPatch,
    metadata: ObjectMetadata | None,
    code: str,
) -> None:
    client, organization, _ = media_client(slug=f"media-head-{code}-{metadata is None}")
    created = initiate_upload(client)
    asset_id = created.data["asset"]["id"]
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: HeadStorage(metadata),
    )

    response = complete_upload(client, asset_id)

    assert response.status_code == 409
    assert response.data["code"] == code
    asset = MediaAsset.all_objects.get(pk=asset_id, organization=organization)
    assert asset.state == MediaAssetState.PENDING
    assert asset.actual_size is None
    assert asset.uploaded_at is None


def test_upload_completion_rejects_expired_intent_before_storage_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, organization, _ = media_client(slug="media-complete-expired")
    created = initiate_upload(client)
    asset_id = created.data["asset"]["id"]
    MediaAsset.all_objects.filter(pk=asset_id, organization=organization).update(
        upload_expires_at=timezone.now() - timedelta(seconds=1)
    )
    storage = HeadStorage(ObjectMetadata(content_length=2048, content_type="image/jpeg"))
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )

    response = complete_upload(client, asset_id)

    assert response.status_code == 409
    assert response.data["code"] == "media_upload_expired"
    assert storage.calls == []


def test_signed_task_scans_sanitizes_variants_and_commits_storage_quota_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, _ = media_client(slug="media-process-ready", storage_limit=10**7)
    raw_content = encoded_image("JPEG", with_exif=True)
    created = initiate_upload(
        client,
        size=len(raw_content),
        idempotency_key="media-process-ready",
    )
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    source_object_key = asset.object_key
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (raw_content, "image/jpeg")
    scanner = VerdictScanner(MalwareVerdict.CLEAN)
    delayed: list[tuple[str, str]] = []
    cleanup_delayed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner",
        lambda: scanner,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.process_media_asset_task.delay",
        lambda asset_id, contract: delayed.append((asset_id, contract)),
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.cleanup_media_source_object_task.delay",
        lambda asset_id, contract: cleanup_delayed.append((asset_id, contract)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        completed = complete_upload(client, str(asset.id))

    assert completed.status_code == 200
    assert len(delayed) == 1
    from saas_core.modules.shared.media.tasks import (
        cleanup_media_source_object_task,
        process_media_asset_task,
    )

    with django_capture_on_commit_callbacks(execute=True):
        process_media_asset_task(*delayed[0])
    assert len(cleanup_delayed) == 1
    cleanup_media_source_object_task(*cleanup_delayed[0])
    first_put_count = len(storage.put_calls)
    process_media_asset_task(*delayed[0])

    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    reservation = QuotaReservation.all_objects.get(organization=organization)
    assert asset.state == MediaAssetState.READY
    assert asset.detected_mime == "image/jpeg"
    assert asset.width == 640
    assert asset.height == 480
    assert asset.ready_at is not None
    assert asset.scanned_at is not None
    assert asset.quota_committed is True
    assert asset.source_object_key == ""
    assert asset.stored_size == usage.used == reservation.amount
    assert usage.reserved == 0
    assert reservation.state == QuotaReservationState.COMMITTED
    assert set(asset.variants) == {"preview", "thumbnail"}
    assert len(storage.put_calls) == first_put_count == 3
    assert scanner.calls == 1
    assert source_object_key not in storage.objects
    sanitized = storage.objects[asset.object_key][0]
    with Image.open(BytesIO(sanitized)) as decoded:
        assert not decoded.getexif()
    for variant in asset.variants.values():
        assert variant["object_key"] in storage.objects
        assert storage.objects[variant["object_key"]][1] == "image/webp"
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="media.asset.ready",
            target_id=asset.id,
        ).count()
        == 1
    )


def test_delete_tombstones_and_cleans_objects_and_quota_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, user = media_client(slug="media-delete-ready")
    asset = create_ready_asset(organization, user, suffix="delete-ready")
    MediaReference.all_objects.create(
        organization=organization,
        asset=asset,
        owner_type=MediaReferenceOwner.PAGE_VERSION,
        owner_id=uuid7(),
    )
    storage = MemoryStorage()
    object_keys = {
        asset.object_key,
        asset.source_object_key,
        *(str(variant["object_key"]) for variant in asset.variants.values()),
    }
    for object_key in object_keys:
        storage.objects[object_key] = (b"content", "image/jpeg")
    delayed: list[tuple[tuple[str, str], int]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.cleanup_tombstoned_media_asset_task.apply_async",
        lambda *, args, countdown: delayed.append((tuple(args), countdown)),
    )

    missing_csrf = client.delete(
        f"{MEDIA_URL}{asset.id}/",
        HTTP_IDEMPOTENCY_KEY="delete-ready",
    )
    with django_capture_on_commit_callbacks(execute=True):
        deleted = delete_asset(client, str(asset.id), idempotency_key="delete-ready")
    with django_capture_on_commit_callbacks(execute=True):
        repeated = delete_asset(client, str(asset.id), idempotency_key="delete-ready")

    assert missing_csrf.status_code == 403
    assert deleted.status_code == repeated.status_code == 202
    assert str(deleted.data["id"]) == str(repeated.data["id"]) == str(asset.id)
    assert deleted.data["cleanup_completed_at"] is None
    assert len(delayed) == 2
    assert all(countdown == 0 for _, countdown in delayed)
    assert client.get(MEDIA_URL).data["items"] == []
    asset.refresh_from_db()
    assert asset.deleted_at is not None
    assert asset.deleted_by_id == user.id
    assert asset.deletion_idempotency_key == "delete-ready"
    assert storage.delete_calls == []
    with pytest.raises(DatabaseError), transaction.atomic():
        MediaAsset.all_objects.filter(pk=asset.id).update(deleted_at=None)

    from saas_core.modules.shared.media.tasks import cleanup_tombstoned_media_asset_task

    cleanup_tombstoned_media_asset_task(str(uuid7()), delayed[0][0][1])
    asset.refresh_from_db()
    assert asset.cleanup_completed_at is None
    cleanup_tombstoned_media_asset_task(*delayed[0][0])
    cleanup_tombstoned_media_asset_task(*delayed[1][0])

    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    reservation = QuotaReservation.all_objects.get(
        organization=organization,
        idempotency_key=asset.quota_reservation_key,
    )
    assert asset.cleanup_completed_at is not None
    assert asset.quota_committed is False
    assert asset.source_object_key == ""
    assert set(storage.delete_calls) == object_keys
    assert len(storage.delete_calls) == len(object_keys)
    assert storage.objects == {}
    assert usage.used == usage.reserved == 0
    assert reservation.state == QuotaReservationState.RELEASED
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="media.asset.tombstoned",
            target_id=asset.id,
        ).count()
        == 1
    )
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization,
            action="media.asset.cleaned",
            target_id=asset.id,
        ).count()
        == 1
    )
    with django_capture_on_commit_callbacks(execute=True):
        completed_retry = delete_asset(
            client,
            str(asset.id),
            idempotency_key="delete-ready",
        )
    assert completed_retry.status_code == 202
    assert completed_retry.data["cleanup_completed_at"] is not None
    assert len(delayed) == 2

    other_asset = create_ready_asset(organization, user, suffix="delete-conflict")
    conflict = delete_asset(client, str(other_asset.id), idempotency_key="delete-ready")
    assert conflict.status_code == 409
    assert conflict.data["code"] == "media_idempotency_conflict"


def test_delete_keeps_published_objects_and_rejects_foreign_or_unauthorized_access(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, user = media_client(slug="media-delete-referenced")
    asset = create_ready_asset(organization, user, suffix="delete-referenced")
    MediaReference.all_objects.create(
        organization=organization,
        asset=asset,
        owner_type=MediaReferenceOwner.PUBLICATION,
        owner_id=uuid7(),
    )
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (b"published", "image/jpeg")
    delayed: list[tuple[tuple[str, str], int]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.cleanup_tombstoned_media_asset_task.apply_async",
        lambda *, args, countdown: delayed.append((tuple(args), countdown)),
    )
    foreign, _, _ = media_client(slug="media-delete-foreign")
    viewer, viewer_organization, viewer_user = media_client(
        slug="media-delete-viewer",
        role_key="viewer",
    )
    viewer_asset = create_ready_asset(
        viewer_organization,
        viewer_user,
        suffix="delete-viewer",
    )

    foreign_response = delete_asset(
        foreign,
        str(asset.id),
        idempotency_key="delete-foreign",
    )
    viewer_response = delete_asset(
        viewer,
        str(viewer_asset.id),
        idempotency_key="delete-viewer",
    )
    with django_capture_on_commit_callbacks(execute=True):
        deleted = delete_asset(
            client,
            str(asset.id),
            idempotency_key="delete-referenced",
        )

    assert foreign_response.status_code == 404
    assert foreign_response.data["code"] == "media_asset_not_found"
    assert viewer_response.status_code == 403
    assert viewer_response.data["code"] == "organization_permission_denied"
    assert deleted.status_code == 202
    assert len(delayed) == 1

    from saas_core.modules.shared.media.tasks import cleanup_tombstoned_media_asset_task

    cleanup_tombstoned_media_asset_task(*delayed[0][0])
    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    assert asset.deleted_at is not None
    assert asset.cleanup_completed_at is None
    assert asset.quota_committed is True
    assert storage.delete_calls == []
    assert asset.object_key in storage.objects
    assert usage.used == 30


def test_delete_defers_pending_upload_cleanup_until_signed_put_expires(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, _ = media_client(slug="media-delete-pending")
    created = initiate_upload(
        client,
        size=2048,
        idempotency_key="delete-pending-upload",
    )
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (b"late-upload", "image/jpeg")
    delayed: list[tuple[tuple[str, str], int]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.cleanup_tombstoned_media_asset_task.apply_async",
        lambda *, args, countdown: delayed.append((tuple(args), countdown)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        deleted = delete_asset(
            client,
            str(asset.id),
            idempotency_key="delete-pending",
        )

    assert deleted.status_code == 202
    assert len(delayed) == 1
    assert delayed[0][1] > 0

    from saas_core.modules.shared.media.tasks import cleanup_tombstoned_media_asset_task

    cleanup_tombstoned_media_asset_task(*delayed[0][0])
    asset.refresh_from_db()
    assert asset.cleanup_completed_at is None
    assert len(delayed) == 2
    assert delayed[1][1] > 0
    assert storage.delete_calls == []

    MediaAsset.all_objects.filter(pk=asset.id).update(
        upload_expires_at=timezone.now() - timedelta(seconds=1)
    )
    cleanup_tombstoned_media_asset_task(*delayed[1][0])
    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    reservation = QuotaReservation.all_objects.get(
        organization=organization,
        idempotency_key=asset.quota_reservation_key,
    )
    assert asset.cleanup_completed_at is not None
    assert storage.delete_calls == [asset.object_key]
    assert usage.used == usage.reserved == 0
    assert reservation.state == QuotaReservationState.RELEASED


@pytest.mark.parametrize(
    ("raw_format", "declared_mime", "verdict", "rejection_code"),
    [
        ("PNG", "image/jpeg", MalwareVerdict.CLEAN, "media_image_invalid"),
        ("JPEG", "image/jpeg", MalwareVerdict.INFECTED, "media_malware_detected"),
    ],
)
def test_processing_rejects_false_mime_and_malware_and_releases_quota(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
    raw_format: str,
    declared_mime: str,
    verdict: MalwareVerdict,
    rejection_code: str,
) -> None:
    slug = f"media-reject-{raw_format.lower()}-{verdict}"
    client, organization, _ = media_client(slug=slug, storage_limit=10**7)
    raw_content = encoded_image(raw_format)
    created = initiate_upload(
        client,
        content_type=declared_mime,
        size=len(raw_content),
        idempotency_key=slug,
    )
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (raw_content, declared_mime)
    scanner = VerdictScanner(verdict)
    delayed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner",
        lambda: scanner,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.process_media_asset_task.delay",
        lambda asset_id, contract: delayed.append((asset_id, contract)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert complete_upload(client, str(asset.id)).status_code == 200
    from saas_core.modules.shared.media.tasks import process_media_asset_task

    process_media_asset_task(*delayed[0])

    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    reservation = QuotaReservation.all_objects.get(organization=organization)
    assert asset.state == MediaAssetState.REJECTED
    assert asset.rejection_code == rejection_code
    assert asset.object_key not in storage.objects
    assert usage.used == 0
    assert usage.reserved == 0
    assert reservation.state == QuotaReservationState.RELEASED
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action="media.asset.rejected",
        target_id=asset.id,
    )
    assert audit.metadata == {"reason": rejection_code}


def test_scanner_outage_is_fail_closed_and_rolls_asset_back_for_retry(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, _ = media_client(slug="media-scanner-outage", storage_limit=10**7)
    raw_content = encoded_image("JPEG")
    created = initiate_upload(
        client,
        size=len(raw_content),
        idempotency_key="media-scanner-outage",
    )
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (raw_content, "image/jpeg")
    delayed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.process_media_asset_task.delay",
        lambda asset_id, contract: delayed.append((asset_id, contract)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert complete_upload(client, str(asset.id)).status_code == 200
    with (
        pytest.raises(MalwareScannerUnavailable),
        tenant_task_context(delayed[0][1]),
    ):
        process_media_asset(
            asset_id=asset.id,
            storage=storage,
            scanner=UnavailableScanner(),
        )

    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    assert asset.state == MediaAssetState.UPLOADED
    assert asset.quota_committed is False
    assert usage.used == 0
    assert usage.reserved == len(raw_content)
    assert storage.put_calls == []


def test_processing_rejects_when_sanitized_original_and_variants_exceed_quota(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    raw_content = encoded_image("JPEG", size=(1600, 1200))
    client, organization, _ = media_client(
        slug="media-process-quota",
        storage_limit=len(raw_content) + 1,
    )
    created = initiate_upload(
        client,
        size=len(raw_content),
        idempotency_key="media-process-quota",
    )
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (raw_content, "image/jpeg")
    delayed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage",
        lambda: storage,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner",
        lambda: VerdictScanner(MalwareVerdict.CLEAN),
    )
    oversized = ProcessedImage(
        content=b"x" * len(raw_content),
        content_type="image/jpeg",
        sha256="0" * 64,
        width=1600,
        height=1200,
        variants=(
            ProcessedVariant(
                kind="thumbnail",
                content=b"variant",
                content_type="image/webp",
                width=320,
                height=240,
            ),
        ),
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.process_image",
        lambda content, declared_mime: oversized,
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.process_media_asset_task.delay",
        lambda asset_id, contract: delayed.append((asset_id, contract)),
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert complete_upload(client, str(asset.id)).status_code == 200
    from saas_core.modules.shared.media.tasks import process_media_asset_task

    process_media_asset_task(*delayed[0])

    asset.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=organization)
    reservation = QuotaReservation.all_objects.get(organization=organization)
    assert asset.state == MediaAssetState.REJECTED
    assert asset.rejection_code == "media_quota_exceeded"
    assert storage.objects == {}
    assert usage.used == 0
    assert usage.reserved == 0
    assert reservation.state == QuotaReservationState.RELEASED


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
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    reference = MediaReference.all_objects.create(
        organization=organization,
        asset=asset,
        owner_type=MediaReferenceOwner.PAGE_VERSION,
        owner_id=uuid7(),
    )
    role_name = f"media_rls_test_{uuid7().hex}"
    quoted_role = connection.ops.quote_name(role_name)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {quoted_role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
        cursor.execute(f"GRANT SELECT, INSERT ON media_mediaasset TO {quoted_role}")
        cursor.execute(f"GRANT SELECT, INSERT ON media_mediareference TO {quoted_role}")
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")
        cursor.execute("SET LOCAL app.organization_id = ''")
        cursor.execute("SELECT COUNT(*) FROM media_mediaasset")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM media_mediareference")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SET LOCAL app.organization_id = %s", [str(foreign_organization.id)])
        cursor.execute("SELECT COUNT(*) FROM media_mediaasset")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM media_mediareference")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization.id)])
        cursor.execute("SELECT COUNT(*) FROM media_mediaasset")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM media_mediareference")
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
                    source_object_key, declared_mime, detected_mime, expected_size,
                    actual_size, stored_size, sha256,
                    width, height, state, quota_reservation_key, quota_committed,
                    variants, rejection_code, upload_expires_at, uploaded_at, scanned_at, ready_at,
                    rejected_at, deleted_at, idempotency_key, request_hash, created_at,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, '', %s, '', 1, NULL, NULL, '', NULL, NULL, 'pending',
                    %s, FALSE, '{}'::jsonb, '', %s, NULL, NULL, NULL, NULL, NULL, %s, %s, %s, %s
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

    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization.id)])
        cursor.execute(
            """
                INSERT INTO media_mediareference (
                    id, organization_id, asset_id, owner_type, owner_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                str(uuid7()),
                str(foreign_organization.id),
                str(asset.id),
                MediaReferenceOwner.PAGE_VERSION,
                str(uuid7()),
                now,
            ],
        )
    assert MediaReference.all_objects.get(pk=reference.id).asset_id == asset.id
    with pytest.raises(DatabaseError), transaction.atomic():
        MediaReference.all_objects.filter(pk=reference.id).update(owner_id=uuid7())
    with pytest.raises(DatabaseError), transaction.atomic():
        MediaReference.all_objects.filter(pk=reference.id).delete()
