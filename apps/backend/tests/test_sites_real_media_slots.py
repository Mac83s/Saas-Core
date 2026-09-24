"""Evidence slots refuse AI media on the server (ADR-059 pkt 8).

A portrait beside a quote and an author's photo claim a real person. The panel
hides AI images there, but the frontend is not a security boundary: every way a
draft is saved or published answers 422 for an AI image in those slots.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from saas_core.modules.shared.media.models import AiOrigin, MediaAsset
from test_content_operations_api import _apply, _change_set, _preview
from test_sites_api import (
    create_media_asset,
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_translation,
    sites_client,
)
from test_sites_collections import create_collection, create_entry, publish

pytestmark = pytest.mark.django_db

REFUSED = "ai_media_not_allowed_in_slot"


@pytest.fixture(autouse=True)
def clear_login_limiter() -> None:
    cache.clear()


def image(asset: MediaAsset) -> dict[str, str]:
    return {"asset_id": str(asset.id), "alt": "Zdjęcie"}


def quote(asset: MediaAsset) -> dict[str, Any]:
    return {
        "block_type": "core.quote",
        "schema_version": 1,
        "data": {"quote": "Polecam.", "author": "Anna", "image": image(asset)},
    }


def author(asset: MediaAsset) -> dict[str, Any]:
    return {
        "block_type": "core.rich_text",
        "schema_version": 3,
        "data": {
            "content": [{"type": "paragraph", "content": [{"text": "Treść"}]}],
            "author": {"name": "Anna", "image": image(asset)},
        },
    }


def hero(asset: MediaAsset) -> dict[str, Any]:
    return {
        "block_type": "core.hero",
        "schema_version": 3,
        "data": {"title": "Oferta", "image": image(asset)},
    }


def generated(asset: MediaAsset) -> MediaAsset:
    MediaAsset.all_objects.filter(pk=asset.id).update(ai_origin=AiOrigin.GENERATED)
    return asset


def put_draft(client: Any, url: str, blocks: list[dict[str, Any]], key: str, version: int = 0):
    return client.put(
        url,
        {
            "expected_version": version,
            "blocks": blocks,
            # Nested images are referenced from block data by the service.
            "media_asset_ids": [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


@pytest.fixture
def page_surface():
    client, org, owner = sites_client(slug="real-media-page", role_key="owner")
    site = create_site(client).data["id"]
    page = create_page(client, site).data["id"]
    return client, org, owner, site, page


@pytest.mark.parametrize("slot", [quote, author])
def test_page_draft_refuses_ai_media_in_evidence_slots(page_surface, slot) -> None:
    client, org, owner, _, page = page_surface
    url = f"/api/v1/sites/pages/{page}/draft/"
    ai_asset = generated(create_media_asset(org, owner))
    real_asset = create_media_asset(org, owner)

    refused = put_draft(client, url, [slot(ai_asset)], "ai-slot")
    assert refused.status_code == 422, refused.data
    assert refused.data["code"] == REFUSED

    assert put_draft(client, url, [slot(real_asset)], "real-slot").status_code == 201
    # The badge marks AI media everywhere else; a hero is not evidence.
    hero_saved = put_draft(client, url, [hero(ai_asset)], "ai-hero", version=1)
    assert hero_saved.status_code == 201, hero_saved.data


def test_change_set_inserting_an_ai_portrait_is_refused(page_surface) -> None:
    client, org, owner, site, page = page_surface
    ai_asset = generated(create_media_asset(org, owner))
    target = {"kind": "site_page", "site_id": str(site), "page_id": str(page), "locale": "pl"}
    base = client.get("/api/v1/sites/content-base/", target).json()
    block = quote(ai_asset)
    doc = _change_set(
        target=target,
        base=base["base"],
        commands=[
            {
                "command": "block.insert",
                "position": 0,
                "block": {
                    "type": block["block_type"],
                    "schema_version": block["schema_version"],
                    "data": block["data"],
                },
            }
        ],
    )
    preview = _preview(client, doc)
    assert preview.status_code == 200, preview.data
    # The set applies through save_draft, which is where the guard sits.
    result = _apply(
        client,
        doc,
        approval_digest=preview.data["approval_digest"],
        approval_token=preview.data["approval_token"],
    )
    assert result.status_code == 422, result.data
    assert result.data["code"] == REFUSED


def test_site_publication_refuses_a_draft_saved_before_the_asset_was_marked(
    page_surface,
) -> None:
    client, org, owner, site, page = page_surface
    asset = create_media_asset(org, owner)
    saved = put_draft(client, f"/api/v1/sites/pages/{page}/draft/", [quote(asset)], "draft")
    assert saved.status_code == 201, saved.data
    translated = save_translation(
        client,
        page,
        "pl",
        expected_version=0,
        slug="o-nas",
        title="O nas",
        description="Kim jesteśmy",
        idempotency_key="t",
    )
    assert translated.status_code in (200, 201), translated.data
    generated(asset)

    refused = publish_site_request(client, site, idempotency_key="publish")

    assert refused.status_code == 422, refused.data
    assert refused.data["code"] == REFUSED


@pytest.mark.parametrize("slot", [quote, author])
def test_entry_draft_and_publication_refuse_ai_media_in_evidence_slots(slot) -> None:
    client, org, owner = sites_client(slug="real-media-entry", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(client, collection.data["id"], slug="wpis", idempotency_key="entry")
    url = f"/api/v1/sites/entries/{entry.data['id']}/draft/"
    ai_asset = generated(create_media_asset(org, owner))
    real_asset = create_media_asset(org, owner)

    refused = put_draft(client, url, [slot(ai_asset)], "ai-entry")
    assert refused.status_code == 422, refused.data
    assert refused.data["code"] == REFUSED

    assert put_draft(client, url, [slot(real_asset)], "real-entry").status_code == 201
    generated(real_asset)
    published = publish(client, entry.data["id"], idempotency_key="entry-publish")
    assert published.status_code == 422, published.data
    assert published.data["code"] == REFUSED
