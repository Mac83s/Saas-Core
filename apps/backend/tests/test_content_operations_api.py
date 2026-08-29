"""The Content Operations API a connector actually talks to (W9.6.6).

The contract is frozen and validated by both repositories; these tests are
about the receiving half — what this server does with a well-formed document,
and what it refuses.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from test_sites_api import create_page, create_site, csrf_value, save_draft, sites_client
from test_sites_collections import (
    create_collection,
    create_entry,
    publish,
    save_entry_draft,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    # Sign-in is rate limited and each test here signs in a fresh owner;
    # the limiter counts in the cache, so a shared one makes later tests 429.
    cache.clear()


def _change_set(**overrides: Any) -> dict[str, Any]:
    document = {
        "contract_version": 1,
        "idempotency_key": f"scr-{uuid.uuid4()}",
        "target": {},
        "base": {
            "version": 0,
            "snapshot_hash": "sha256:" + "a1" * 32,
            "observed_at": "2026-08-29T09:00:00Z",
        },
        "rationale": {
            "summary": "Treść nie odpowiada na intencję wyszukiwania.",
            "risk": "low",
            "sources": [
                {
                    "kind": "search_console",
                    "reference": "query=fizjoterapia;position=14",
                    "observed_at": "2026-08-28T22:00:00Z",
                }
            ],
        },
        "commands": [],
    }
    document.update(overrides)
    return document


def _preview(client: APIClient, document: dict[str, Any]) -> Any:
    return client.post(
        "/api/v1/sites/changes/",
        {"change_set": document},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )


def _apply(client: APIClient, document: dict[str, Any], **body: Any) -> Any:
    return client.post(
        "/api/v1/sites/changes/apply/",
        {"change_set": document, **body},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )


def test_inventory_is_one_read_of_one_moment_with_an_etag() -> None:
    """A connector assembling its picture endpoint by endpoint would plan
    against a state that never existed."""
    client, _, _ = sites_client(slug="inventory", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="inv-page")
    create_collection(client, site.data["id"])

    first = client.get("/api/v1/sites/inventory/")
    assert first.status_code == 200
    body = first.json()
    assert body["contract_version"] >= 1
    # The response is JSON, so identifiers are strings; `data["id"]` from the
    # creating call is still a UUID object.
    entry = next(
        item for item in body["sites"] if item["site_id"] == str(site.data["id"])
    )
    assert [item["page_id"] for item in entry["pages"]] == [str(page.data["id"])]
    assert [item["key"] for item in entry["collections"]] == ["blog"]

    etag = first["ETag"]
    assert etag
    # Asking again with the tag costs nothing when nothing the caller acts on
    # has moved — and the moment it was read is outside the hash on purpose.
    again = client.get("/api/v1/sites/inventory/", HTTP_IF_NONE_MATCH=etag)
    assert again.status_code == 304

    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="inv-draft",
        heading="Nowy nagłówek",
    )
    changed = client.get("/api/v1/sites/inventory/", HTTP_IF_NONE_MATCH=etag)
    assert changed.status_code == 200
    assert changed["ETag"] != etag


def test_a_change_set_previews_the_diff_it_would_apply() -> None:
    client, _, _ = sites_client(slug="changeset", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="cs-page")
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="cs-draft",
        heading="Stary nagłówek",
    )

    document = _change_set(
        target={
            "kind": "site_page",
            "site_id": site.data["id"],
            "page_id": page.data["id"],
            "locale": "pl",
        },
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Nowa treść od optymalizatora."},
                },
            }
        ],
    )
    document["base"]["version"] = 1

    preview = _preview(client, document)
    assert preview.status_code == 200
    diff = preview.json()
    # The diff is derived from the plan that would be applied, not from the
    # sender's account of its own intent.
    assert diff["blocks_after"][0]["data"]["text"] == "Nowa treść od optymalizatora."
    assert diff["blocks_before"] != diff["blocks_after"]
    assert diff["approval_digest"]

    # Preview alone changes nothing.
    draft = client.get(f"/api/v1/sites/pages/{page.data['id']}/draft/").json()
    assert draft["version"] == 1

    applied = _apply(client, document, approval_digest=diff["approval_digest"])
    assert applied.status_code == 201
    assert applied.json()["published"] is False
    after = client.get(f"/api/v1/sites/pages/{page.data['id']}/draft/").json()
    assert after["version"] == 2
    assert after["blocks"][0]["data"]["text"] == "Nowa treść od optymalizatora."


def test_a_stale_base_version_demands_an_explicit_recomputation() -> None:
    """`409` and nothing else: overwriting the state somebody else wrote is
    exactly what the base version exists to prevent."""
    client, _, _ = sites_client(slug="changeset-stale", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="stale-page")
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="stale-draft",
        heading="Pierwsza",
    )

    document = _change_set(
        target={
            "kind": "site_page",
            "site_id": site.data["id"],
            "page_id": page.data["id"],
            "locale": "pl",
        },
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Propozycja."},
                },
            }
        ],
    )
    document["base"]["version"] = 1

    # Somebody edits the page between the connector's read and its write.
    save_draft(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="stale-human",
        heading="Druga",
    )

    response = _apply(client, document)
    assert response.status_code == 409
    assert response.json()["code"] == "change_set_stale"


def test_an_approval_digest_does_not_survive_the_payload_changing() -> None:
    client, _, _ = sites_client(slug="changeset-digest", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="digest-page")
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="digest-draft",
        heading="Nagłówek",
    )

    document = _change_set(
        target={
            "kind": "site_page",
            "site_id": site.data["id"],
            "page_id": page.data["id"],
            "locale": "pl",
        },
        commands=[
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Zatwierdzona treść."},
                },
            }
        ],
    )
    document["base"]["version"] = 1
    digest = _preview(client, document).json()["approval_digest"]

    # The same approval, a different payload. This is the substitution the
    # digest exists to catch.
    document["commands"][0]["block"]["data"]["text"] = "Coś zupełnie innego."
    response = _apply(client, document, approval_digest=digest)
    assert response.status_code == 409
    assert response.json()["code"] == "approval_digest_mismatch"


def test_an_internal_link_to_an_address_that_does_not_exist_is_refused() -> None:
    """A broken link on a customer's site is worse than a missing one, and
    nothing later goes back to check."""
    client, _, _ = sites_client(slug="changeset-link", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="link-page")
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="link-draft",
        heading="Nagłówek",
    )

    document = _change_set(
        target={
            "kind": "site_page",
            "site_id": site.data["id"],
            "page_id": page.data["id"],
            "locale": "pl",
        },
        commands=[
            {
                "command": "internal_link.add",
                "position": 0,
                "target_path": "/strona-ktorej-nie-ma/",
                "anchor_text": "zobacz też",
            }
        ],
    )
    document["base"]["version"] = 1

    response = _preview(client, document)
    assert response.status_code == 422
    assert response.json()["code"] == "change_set_link_rejected"


def test_a_contract_version_this_build_does_not_implement_is_refused() -> None:
    client, _, _ = sites_client(slug="changeset-version", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="version-page")

    document = _change_set(
        contract_version=99,
        target={
            "kind": "site_page",
            "site_id": site.data["id"],
            "page_id": page.data["id"],
            "locale": "pl",
        },
        commands=[
            {
                "command": "translation.update",
                "fields": {"title": "Tytuł"},
            }
        ],
    )
    response = _preview(client, document)
    # A version above ours is refused too: the sender describes a contract this
    # build does not implement, and accepting it would mean guessing.
    assert response.status_code == 422
    assert response.json()["code"] == "contract_version_unsupported"


def test_a_malformed_change_set_is_refused_the_way_the_sender_can_reproduce() -> None:
    client, _, _ = sites_client(slug="changeset-shape", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="shape-page")

    document = _change_set(
        target={
            "kind": "site_page",
            "site_id": site.data["id"],
            "page_id": page.data["id"],
            "locale": "pl",
        },
        commands=[{"command": "page.delete", "page_id": page.data["id"]}],
    )
    response = _preview(client, document)
    assert response.status_code == 400
    assert response.json()["code"] == "change_set_malformed"


def test_a_change_set_reaches_a_blog_entry_as_well_as_a_page() -> None:
    client, _, _ = sites_client(slug="changeset-entry", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="cs-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Pierwsza wersja.",
        idempotency_key="cs-entry-draft",
    )
    publish(client, entry.data["id"], idempotency_key="cs-entry-publish")

    document = _change_set(
        target={
            "kind": "content_entry",
            "site_id": site.data["id"],
            "collection_id": collection.data["id"],
            "entry_id": entry.data["id"],
            "locale": "pl",
        },
        commands=[
            {
                "command": "block.insert",
                "position": 1,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Akapit dopisany przez optymalizatora."},
                },
            }
        ],
    )
    document["base"]["version"] = 1

    applied = _apply(client, document)
    assert applied.status_code == 201
    draft = client.get(f"/api/v1/sites/entries/{entry.data['id']}/draft/").json()
    assert len(draft["blocks"]) == 2
    # Accepting a change is not the same act as putting it in front of readers.
    assert applied.json()["published"] is False
    listed = json.loads(
        client.get(
            f"/api/v1/sites/collections/{collection.data['id']}/entries/"
        ).content
    )
    assert listed["items"][0]["state"] == "published"
