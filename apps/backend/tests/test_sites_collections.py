from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from saas_core.modules.shared.sites.models import (
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    PageAutomationPolicy,
)
from test_sites_api import create_site, csrf_value, sites_client

pytestmark = pytest.mark.django_db


def create_collection(
    client: APIClient,
    site_id: str,
    *,
    key: str = "blog",
    base_path: str = "blog",
    idempotency_key: str = "collection-create",
) -> Any:
    return client.post(
        f"/api/v1/sites/{site_id}/collections/",
        {"key": key, "name": key.title(), "kind": "blog", "base_path": base_path},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def create_entry(
    client: APIClient,
    collection_id: str,
    *,
    slug: str,
    idempotency_key: str,
) -> Any:
    return client.post(
        f"/api/v1/sites/collections/{collection_id}/entries/",
        {"slug": slug, "locale": "pl", "title": slug.replace("-", " ").title()},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def save_entry_draft(
    client: APIClient,
    entry_id: str,
    *,
    expected_version: int,
    text: str,
    idempotency_key: str,
) -> Any:
    return client.put(
        f"/api/v1/sites/entries/{entry_id}/draft/",
        {
            "expected_version": expected_version,
            "blocks": [
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": text},
                }
            ],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def publish(client: APIClient, entry_id: str, *, idempotency_key: str) -> Any:
    return client.post(
        f"/api/v1/sites/entries/{entry_id}/publication/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def test_entry_publishes_alone_and_snapshot_does_not_grow_with_the_archive() -> None:
    """The reason collections exist at all (ADR-035 §1).

    If entries shared the site's atomic snapshot, publishing the tenth article
    would carry the previous nine — and the three-hundredth would carry 299.
    """
    client, _, _ = sites_client(slug="collections", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    collection_id = collection.data["id"]

    sizes: list[int] = []
    for index in range(6):
        entry = create_entry(
            client,
            collection_id,
            slug=f"wpis-{index}",
            idempotency_key=f"entry-{index}",
        )
        save_entry_draft(
            client,
            entry.data["id"],
            expected_version=0,
            text=f"Treść wpisu numer {index}.",
            idempotency_key=f"draft-{index}",
        )
        published = publish(
            client, entry.data["id"], idempotency_key=f"publish-{index}"
        )
        assert published.status_code == 201
        snapshot = ContentEntryPublication.all_objects.get(
            pk=published.data["id"]
        ).snapshot
        # Each snapshot holds exactly one article, whichever number it is.
        assert snapshot["entry_id"] == str(entry.data["id"])
        assert len(snapshot["blocks"]) == 1
        sizes.append(len(str(snapshot)))

    assert collection.status_code == 201
    # The last article's snapshot is the same size as the first, not six times
    # larger. Compared loosely because the index appears in the copy.
    assert max(sizes) - min(sizes) < 40


def test_publishing_is_idempotent_and_withdrawal_keeps_the_history() -> None:
    client, _, _ = sites_client(slug="entry-lifecycle", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="pierwszy", idempotency_key="lifecycle"
    )
    entry_id = entry.data["id"]

    unpublishable = publish(client, entry_id, idempotency_key="too-early")
    save_entry_draft(
        client,
        entry_id,
        expected_version=0,
        text="Gotowa treść.",
        idempotency_key="lifecycle-draft",
    )
    first = publish(client, entry_id, idempotency_key="lifecycle-publish")
    replay = publish(client, entry_id, idempotency_key="lifecycle-publish")
    withdrawn = client.delete(
        f"/api/v1/sites/entries/{entry_id}/publication/",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    # An empty article is not publishable — better a refusal than a blank page.
    assert unpublishable.status_code == 409
    assert unpublishable.data["code"] == "content_entry_not_ready"
    assert first.status_code == 201
    # Replaying the same key returns the same publication rather than making a
    # second one, so a retried request cannot double-publish.
    assert replay.status_code == 200
    assert replay.data["id"] == first.data["id"]
    assert withdrawn.status_code == 200
    assert withdrawn.data["state"] == ContentEntryState.WITHDRAWN
    # Withdrawal takes the article off the site without destroying its history.
    assert ContentEntryPublication.all_objects.filter(entry_id=entry_id).count() == 1
    assert ContentEntry.all_objects.get(pk=entry_id).current_publication_id is None


def test_collection_policy_decides_whether_automation_may_write_entries() -> None:
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.collections import save_entry_draft as save
    from saas_core.modules.shared.sites.services import PageAutomationForbidden
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="entry-policy", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="policy-entry"
    )
    blocks = [
        {
            "block_type": "core.rich_text",
            "schema_version": 1,
            "data": {"text": "Treść od automatyzacji."},
        }
    ]

    # The policy lives on the collection: opening the blog to automation does
    # not open the rest of the site.
    with (
        activate_tenant_context(automation_context(organization.id, user.id)),
        pytest.raises(PageAutomationForbidden),
    ):
        save(
            entry_id=entry.data["id"],
            expected_version=0,
            blocks=blocks,
            idempotency_key="automation-refused",
        )

    from saas_core.modules.shared.sites.models import ContentCollection

    ContentCollection.all_objects.filter(pk=collection.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )
    with activate_tenant_context(automation_context(organization.id, user.id)):
        version, created = save(
            entry_id=entry.data["id"],
            expected_version=0,
            blocks=blocks,
            idempotency_key="automation-allowed",
        )

    assert created is True
    assert version.number == 1
