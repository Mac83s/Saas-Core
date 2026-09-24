"""Provenance of AI media (ADR-059 pkt 6).

An AI asset gets the IPTC DigitalSourceType in every file the pipeline writes,
keeps the provider original as private evidence until the asset is tombstoned,
and is the only kind `ai_generated_asset_ids` reports.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from saas_core.modules.shared.media.api import ai_generated_asset_ids
from saas_core.modules.shared.media.models import AiOrigin, MediaAsset, MediaAssetState
from saas_core.modules.shared.media.scanner import MalwareVerdict
from saas_core.modules.shared.media.tasks import (
    cleanup_tombstoned_media_asset_task,
    process_media_asset_task,
)
from test_media_api import (
    MemoryStorage,
    VerdictScanner,
    complete_upload,
    create_ready_asset,
    delete_asset,
    encoded_image,
    initiate_upload,
    media_client,
)

pytestmark = pytest.mark.django_db

MARK = b"trainedAlgorithmicMedia"
_clients: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def clear_login_limiter() -> None:
    cache.clear()


def _process(
    monkeypatch: pytest.MonkeyPatch,
    capture: Any,
    *,
    slug: str,
    ai_origin: str,
) -> tuple[MediaAsset, MemoryStorage, list[tuple[str, str]], str]:
    client, _, _ = media_client(slug=slug, storage_limit=10**7)
    _clients[slug] = client
    raw = encoded_image("JPEG")
    created = initiate_upload(client, size=len(raw), idempotency_key=f"{slug}-upload")
    MediaAsset.all_objects.filter(pk=created.data["asset"]["id"]).update(ai_origin=ai_origin)
    asset = MediaAsset.all_objects.get(pk=created.data["asset"]["id"])
    source_key = asset.object_key
    storage = MemoryStorage()
    storage.objects[source_key] = (raw, "image/jpeg")
    delayed: list[tuple[str, str]] = []
    cleanups: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner",
        lambda: VerdictScanner(MalwareVerdict.CLEAN),
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.process_media_asset_task.delay",
        lambda *args: delayed.append(args),
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.cleanup_media_source_object_task.delay",
        lambda *args: cleanups.append(args),
    )
    with capture(execute=True):
        assert complete_upload(client, str(asset.id)).status_code == 200
    with capture(execute=True):
        process_media_asset_task(*delayed[0])
    # The early return on an already READY asset takes the same branch.
    with capture(execute=True):
        process_media_asset_task(*delayed[0])
    asset.refresh_from_db()
    return asset, storage, cleanups, source_key


def test_ai_asset_is_marked_in_every_file_and_keeps_its_original(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    asset, storage, cleanups, source_key = _process(
        monkeypatch,
        django_capture_on_commit_callbacks,
        slug="ai-origin-generated",
        ai_origin=AiOrigin.GENERATED,
    )

    assert asset.state == MediaAssetState.READY
    assert MARK in storage.objects[asset.object_key][0]
    assert set(asset.variants) == {"preview", "thumbnail"}
    for variant in asset.variants.values():
        assert MARK in storage.objects[variant["object_key"]][0]
    # The provider original stays as private evidence: no cleanup was queued.
    assert cleanups == []
    assert asset.source_object_key == source_key
    assert source_key in storage.objects


def test_ordinary_asset_is_unmarked_and_its_upload_is_cleaned(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    asset, storage, cleanups, _ = _process(
        monkeypatch,
        django_capture_on_commit_callbacks,
        slug="ai-origin-none",
        ai_origin=AiOrigin.NONE,
    )

    assert MARK not in storage.objects[asset.object_key][0]
    assert len(cleanups) == 2
    assert {args[0] for args in cleanups} == {str(asset.id)}


def test_tombstone_deletes_the_kept_original_with_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    client, organization, user = media_client(slug="ai-origin-tombstone")
    asset = create_ready_asset(organization, user, suffix="ai-tombstone")
    MediaAsset.all_objects.filter(pk=asset.id).update(ai_origin=AiOrigin.GENERATED)
    storage = MemoryStorage()
    keys = {
        asset.object_key,
        asset.source_object_key,
        *(variant["object_key"] for variant in asset.variants.values()),
    }
    assert len(keys) == 4
    for key in keys:
        storage.objects[key] = (b"content", "image/jpeg")
    queued: list[list[str]] = []
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.tasks.cleanup_tombstoned_media_asset_task.apply_async",
        lambda *, args, countdown: queued.append(args),
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert delete_asset(client, str(asset.id), idempotency_key="ai-del").status_code == 202
    cleanup_tombstoned_media_asset_task(*queued[0])

    assert set(storage.delete_calls) == keys
    assert storage.objects == {}


def test_ai_generated_asset_ids_reports_only_generated_assets_of_that_tenant() -> None:
    _, organization, user = media_client(slug="ai-origin-ids")
    _, foreign, stranger = media_client(slug="ai-origin-ids-other")
    generated = create_ready_asset(organization, user, suffix="ai-yes")
    plain = create_ready_asset(organization, user, suffix="ai-no")
    theirs = create_ready_asset(foreign, stranger, suffix="ai-theirs")
    MediaAsset.all_objects.filter(pk__in=[generated.id, theirs.id]).update(
        ai_origin=AiOrigin.GENERATED
    )

    found = ai_generated_asset_ids(
        organization_id=organization.id,
        asset_ids=[str(generated.id), str(plain.id), str(theirs.id), str(uuid7())],
    )

    assert found == {str(generated.id)}
    assert ai_generated_asset_ids(organization_id=organization.id, asset_ids=[]) == set()


def test_migration_marks_template_media_as_generated_and_walks_back() -> None:
    _, organization, user = media_client(slug="ai-origin-migration")
    rows = {
        "template:abc": AiOrigin.GENERATED,
        "template-photo:def": AiOrigin.GENERATED,
        "customer-upload": AiOrigin.NONE,
    }
    ids = {}
    for key in rows:
        asset = create_ready_asset(organization, user, suffix=key.replace(":", "-"))
        MediaAsset.all_objects.filter(pk=asset.id).update(idempotency_key=key)
        ids[key] = asset.id
    before = ("media", "0007_media_reference_allows_erasure")
    after = ("media", "0008_mediaasset_ai_origin")
    with connection.cursor() as cursor:
        # Fire the deferred FK checks now; PostgreSQL refuses ALTER TABLE on a
        # table with pending trigger events.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    executor = MigrationExecutor(connection)
    executor.migrate([before])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'media_mediaasset' AND column_name = 'ai_origin'"
        )
        assert cursor.fetchone()[0] == 0
    executor = MigrationExecutor(connection)
    executor.migrate([after])

    for key, expected in rows.items():
        assert MediaAsset.all_objects.get(pk=ids[key]).ai_origin == expected


def test_media_list_reports_each_assets_ai_origin(
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The serializer and OpenAPI declared it, the panel filtered on it, and
    the list never sent it: every picker treated AI images as real photos."""
    asset, _, _, _ = _process(
        monkeypatch,
        django_capture_on_commit_callbacks,
        slug="ai-origin-list",
        ai_origin=AiOrigin.GENERATED,
    )
    items = _clients["ai-origin-list"].get("/api/v1/media/").data["items"]
    assert {str(item["id"]): item["ai_origin"] for item in items} == {
        str(asset.id): AiOrigin.GENERATED
    }
