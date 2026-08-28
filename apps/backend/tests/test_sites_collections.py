from __future__ import annotations

from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.shared.sites.models import (
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    PageAutomationPolicy,
)
from test_sites_api import create_site, csrf_value, sites_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    # Sign-in is rate limited, and each test here signs in a fresh owner; the
    # limiter counts in the cache, so a shared one makes later tests fail 429.
    cache.clear()


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
    # The grant is what this credential was hired for; the policy is a separate
    # gate on top of it. This test isolates the policy, so the grant is present.
    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    credential_id = uuid7()
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        collection_id=collection.data["id"],
        mode="autonomous",
        created_by=user,
    )

    # The policy lives on the collection: opening the blog to automation does
    # not open the rest of the site.
    with (
        activate_tenant_context(
            automation_context(organization.id, user.id, credential_id=credential_id)
        ),
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
    with activate_tenant_context(
        automation_context(organization.id, user.id, credential_id=credential_id)
    ):
        version, created = save(
            entry_id=entry.data["id"],
            expected_version=0,
            blocks=blocks,
            idempotency_key="automation-allowed",
        )

    assert created is True
    assert version.number == 1


def test_published_entry_is_reachable_on_the_public_site() -> None:
    """An article nobody can open is not published in any useful sense."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from saas_core.modules.shared.sites.models import (
        Domain,
        DomainKind,
        DomainStatus,
        DomainTlsStatus,
    )

    client, _, _ = sites_client(slug="public-entry", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="pierwszy-wpis", idempotency_key="pub-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Treść pierwszego wpisu.",
        idempotency_key="pub-entry-draft",
    )
    publish(client, entry.data["id"], idempotency_key="pub-entry-publish")
    platform = Domain.all_objects.get(site_id=site.data["id"], kind=DomainKind.PLATFORM)
    Domain.all_objects.filter(pk=platform.pk).update(
        status=DomainStatus.VERIFIED, tls_status=DomainTlsStatus.ELIGIBLE
    )

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        found = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/pierwszy-wpis/"},
            HTTP_HOST=platform.hostname,
        )
        # The same address without the trailing slash is the same article.
        no_slash = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/pierwszy-wpis"},
            HTTP_HOST=platform.hostname,
        )
        missing = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/nie-ma-takiego/"},
            HTTP_HOST=platform.hostname,
        )

    assert found.status_code == 200
    assert found.data["title"] == "Pierwszy Wpis"
    assert found.data["locale"] == "pl"
    assert found.data["blocks"][0]["block_type"] == "core.rich_text"
    assert no_slash.status_code == 200
    assert missing.status_code == 404


def test_withdrawn_entry_disappears_from_the_public_site() -> None:
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from saas_core.modules.shared.sites.models import (
        Domain,
        DomainKind,
        DomainStatus,
        DomainTlsStatus,
    )

    client, _, _ = sites_client(slug="withdraw-entry", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="do-wycofania", idempotency_key="wd-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Treść do wycofania.",
        idempotency_key="wd-draft",
    )
    publish(client, entry.data["id"], idempotency_key="wd-publish")
    platform = Domain.all_objects.get(site_id=site.data["id"], kind=DomainKind.PLATFORM)
    Domain.all_objects.filter(pk=platform.pk).update(
        status=DomainStatus.VERIFIED, tls_status=DomainTlsStatus.ELIGIBLE
    )

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        before = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/do-wycofania/"},
            HTTP_HOST=platform.hostname,
        )
        client.delete(
            f"/api/v1/sites/entries/{entry.data['id']}/publication/",
            HTTP_X_CSRFTOKEN=csrf_value(client),
        )
        after = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/do-wycofania/"},
            HTTP_HOST=platform.hostname,
        )

    assert before.status_code == 200
    # Withdrawal has to take effect for readers immediately, not at the next
    # site publication.
    assert after.status_code == 404


def test_api_key_reaches_the_blog_and_is_bounded_by_its_scopes() -> None:
    """SeoContentRank authenticates with a key, not a session.

    The panel's own endpoints are reused deliberately: one set of domain rules
    for both channels, with the key deciding how far the caller gets.
    """
    from django.contrib.auth.hashers import make_password
    from django.test import Client

    from saas_core.modules.shared.notifications.models import (
        ApiKey,
        ApiKeyCredentialRoute,
    )
    from saas_core.modules.shared.sites.models import (
        ContentAutomationGrant,
        ContentCollection,
    )

    client, organization, user = sites_client(slug="api-key-blog", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis-scr", idempotency_key="scr-entry"
    )

    raw = "sc_live_" + "k" * 32
    api_key = ApiKey.all_objects.create(
        organization=organization,
        name="SeoContentRank",
        prefix=raw[:18],
        secret_hash=make_password(raw),
        scopes=["content:read", "content:draft"],
        created_by=user,
    )
    ApiKeyCredentialRoute.objects.create(
        prefix=raw[:18],
        api_key_id=api_key.id,
        organization_id=organization.id,
        secret_hash=api_key.secret_hash,
        scopes=["content:read", "content:draft"],
    )
    # A key with no grant reaches nothing: authenticating proves which
    # organization is calling, not what it was hired to do.
    ungranted = Client().get(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=api_key.id,
        collection_id=collection.data["id"],
        mode="autonomous",
        created_by=user,
    )

    body = {
        "expected_version": 0,
        "blocks": [
            {
                "block_type": "core.rich_text",
                "schema_version": 1,
                "data": {"text": "Treść napisana przez automatyzację."},
            }
        ],
    }
    keyed = Client()
    unauthenticated = keyed.get(f"/api/v1/sites/entries/{entry.data['id']}/draft/")
    bad_key = keyed.get(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        HTTP_AUTHORIZATION="Bearer sc_live_" + "x" * 32,
    )
    read = keyed.get(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    # The collection is `manual`, so a valid key still cannot write.
    refused = keyed.put(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
        HTTP_IDEMPOTENCY_KEY="scr-refused",
    )
    ContentCollection.all_objects.filter(pk=collection.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )
    written = keyed.put(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
        HTTP_IDEMPOTENCY_KEY="scr-written",
    )
    # The key carries no publish scope, so publishing is refused at the door.
    published = keyed.post(
        f"/api/v1/sites/entries/{entry.data['id']}/publication/",
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
        HTTP_IDEMPOTENCY_KEY="scr-publish",
    )

    assert ungranted.status_code == 403
    assert ungranted.json()["code"] == "automation_grant_missing"
    assert unauthenticated.status_code == 403
    assert bad_key.status_code == 401
    assert read.status_code == 200
    assert refused.status_code == 403
    assert refused.json()["code"] == "page_automation_forbidden"
    assert written.status_code == 201
    assert published.status_code == 401


def test_grant_bounds_the_credential_by_resource_expiry_and_revocation() -> None:
    """The grant is what stands between "we hold the key" and "a customer's
    whole site is reachable by an integration"."""
    from datetime import timedelta

    from django.utils import timezone

    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.collections import get_entry_draft
    from saas_core.modules.shared.sites.models import ContentAutomationGrant
    from saas_core.modules.shared.sites.services import AutomationGrantMissing
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="grant-scope", role_key="owner")
    site = create_site(client)
    blog = create_collection(client, site.data["id"], idempotency_key="grant-blog")
    news = create_collection(
        client,
        site.data["id"],
        key="aktualnosci",
        base_path="aktualnosci",
        idempotency_key="grant-news",
    )
    blog_entry = create_entry(
        client, blog.data["id"], slug="wpis-bloga", idempotency_key="grant-e1"
    )
    news_entry = create_entry(
        client, news.data["id"], slug="wpis-news", idempotency_key="grant-e2"
    )

    credential_id = uuid7()
    grant = ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        collection_id=blog.data["id"],
        mode="autonomous",
        created_by=user,
    )
    context = automation_context(
        organization.id, user.id, credential_id=credential_id
    )

    with activate_tenant_context(context):
        granted = get_entry_draft(entry_id=blog_entry.data["id"])
        # A collection grant covers that collection only. Giving away the blog
        # must not give away the news section beside it.
        with pytest.raises(AutomationGrantMissing):
            get_entry_draft(entry_id=news_entry.data["id"])

    grant.expires_at = timezone.now() - timedelta(seconds=1)
    grant.save(update_fields=["expires_at"])
    with activate_tenant_context(context), pytest.raises(AutomationGrantMissing):
        get_entry_draft(entry_id=blog_entry.data["id"])

    # Emergency revoke: immediate, and the row survives for the audit trail.
    grant.expires_at = None
    grant.revoked_at = timezone.now()
    grant.save(update_fields=["expires_at", "revoked_at"])
    with activate_tenant_context(context), pytest.raises(AutomationGrantMissing):
        get_entry_draft(entry_id=blog_entry.data["id"])

    assert str(granted.entry.id) == str(blog_entry.data["id"])
    assert ContentAutomationGrant.all_objects.filter(pk=grant.pk).exists()


def test_site_grant_covers_its_collections_but_a_collection_grant_does_not_widen() -> (
    None
):
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.collections import get_entry_draft
    from saas_core.modules.shared.sites.models import ContentAutomationGrant
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="grant-site", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="site-grant-e"
    )

    credential_id = uuid7()
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        site_id=site.data["id"],
        mode="autonomous",
        created_by=user,
    )

    with activate_tenant_context(
        automation_context(organization.id, user.id, credential_id=credential_id)
    ):
        draft = get_entry_draft(entry_id=entry.data["id"])

    # A whole-site grant reaches the collections inside it, which is what makes
    # it the wider of the two and worth choosing deliberately.
    assert str(draft.entry.id) == str(entry.data["id"])


def test_proposed_policy_lets_automation_draft_but_not_publish() -> None:
    """The middle setting: a cautious client wants the article written for them
    and still decides for themselves whether readers ever see it."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.collections import (
        publish_entry,
        save_entry_draft,
        withdraw_entry,
    )
    from saas_core.modules.shared.sites.models import (
        ContentAutomationGrant,
        ContentCollection,
        ContentEntryVersion,
    )
    from saas_core.modules.shared.sites.services import PageAutomationForbidden
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="entry-proposed", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="proposed-entry"
    )
    credential_id = uuid7()
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        collection_id=collection.data["id"],
        mode="autonomous",
        created_by=user,
    )
    ContentCollection.all_objects.filter(pk=collection.data["id"]).update(
        automation_policy=PageAutomationPolicy.PROPOSED
    )

    with activate_tenant_context(
        automation_context(
            organization.id,
            user.id,
            credential_id=credential_id,
            may_publish=True,
        )
    ):
        version, created = save_entry_draft(
            entry_id=entry.data["id"],
            expected_version=0,
            blocks=[
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Propozycja od automatyzacji."},
                }
            ],
            idempotency_key="proposal-draft",
        )
        assert created is True

        # Publishing its own proposal would make the acceptance step a fiction.
        with pytest.raises(PageAutomationForbidden):
            publish_entry(
                entry_id=entry.data["id"], idempotency_key="proposal-publish"
            )
        with pytest.raises(PageAutomationForbidden):
            withdraw_entry(entry_id=entry.data["id"])

    stored = ContentEntryVersion.all_objects.get(pk=version.id)
    # The panel tells a proposal from the operator's own draft by this column;
    # `created_by` names the person the credential was issued by, not the writer.
    assert stored.created_by_credential == credential_id

    published = client.post(
        f"/api/v1/sites/entries/{entry.data['id']}/publication/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="human-accepts",
    )
    assert published.status_code == 201


def test_entry_listing_reports_who_wrote_the_waiting_draft() -> None:
    client, _organization, _user = sites_client(slug="entry-author", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="author-entry"
    )
    listed = client.get(f"/api/v1/sites/collections/{collection.data['id']}/entries/")
    assert listed.json()["items"][0]["draft_author"] is None

    client.put(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Napisane ręcznie."},
                }
            ],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="author-draft",
    )
    listed = client.get(f"/api/v1/sites/collections/{collection.data['id']}/entries/")
    assert listed.json()["items"][0]["draft_author"] == "person"


def test_api_key_row_is_read_only_after_the_tenant_setting() -> None:
    """`notifications_apikey` enforces row-level security, so reading the key
    before `SET LOCAL app.organization_id` returns nothing and every credential
    looks invalid.

    The test database connects as an owner that bypasses RLS, which is why a
    passing suite said nothing: this asserts the statement *order* instead, the
    one thing that stays observable either way.
    """
    from django.contrib.auth.hashers import make_password
    from django.db import connection
    from django.test import Client
    from django.test.utils import CaptureQueriesContext

    from saas_core.modules.shared.notifications.models import (
        ApiKey,
        ApiKeyCredentialRoute,
    )
    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    client, organization, user = sites_client(slug="api-key-order", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis-order", idempotency_key="order-entry"
    )
    raw = "sc_live_" + "o" * 32
    scopes = ["content:read", "content:draft"]
    api_key = ApiKey.all_objects.create(
        organization=organization,
        name="SeoContentRank",
        prefix=raw[:18],
        secret_hash=make_password(raw),
        scopes=scopes,
        created_by=user,
    )
    ApiKeyCredentialRoute.objects.create(
        prefix=raw[:18],
        api_key_id=api_key.id,
        organization_id=organization.id,
        secret_hash=api_key.secret_hash,
        scopes=scopes,
    )
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=api_key.id,
        collection_id=collection.data["id"],
        mode="autonomous",
        created_by=user,
    )

    with CaptureQueriesContext(connection) as captured:
        response = Client().get(
            f"/api/v1/sites/entries/{entry.data['id']}/draft/",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )
    assert response.status_code == 200

    statements = [query["sql"] for query in captured.captured_queries]
    tenant_set = next(
        index
        for index, sql in enumerate(statements)
        if "app.organization_id" in sql and "SET LOCAL" in sql.upper()
    )
    key_read = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "notifications_apikey"' in sql and sql.upper().startswith("SELECT")
    )
    assert tenant_set < key_read


def _verified_platform_domain(site_id: str) -> object:
    from saas_core.modules.shared.sites.models import (
        Domain,
        DomainKind,
        DomainStatus,
        DomainTlsStatus,
    )

    platform = Domain.all_objects.get(site_id=site_id, kind=DomainKind.PLATFORM)
    Domain.all_objects.filter(pk=platform.pk).update(
        status=DomainStatus.VERIFIED, tls_status=DomainTlsStatus.ELIGIBLE
    )
    return platform


def test_blog_index_lists_published_entries_without_anyone_editing_it() -> None:
    """ADR-035 §7: the index is a projection, not a page somebody maintains.

    A hand-kept list is wrong the moment an article is published and nobody
    remembers to update it, which is every time.
    """
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="blog-index", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    platform = _verified_platform_domain(site.data["id"])

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        empty = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/"},
            HTTP_HOST=platform.hostname,
        )
    # An empty blog still has an address: answering 404 would break the link in
    # the menu until the first article lands.
    assert empty.status_code == 200
    assert empty.json()["blocks"][0]["block_type"] == "core.entry_list"
    assert empty.json()["blocks"][0]["data"]["items"] == []

    entry = create_entry(
        client, collection.data["id"], slug="pierwszy", idempotency_key="index-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Treść pierwszego wpisu.",
        idempotency_key="index-entry-draft",
    )
    publish(client, entry.data["id"], idempotency_key="index-entry-publish")

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        listed = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/"},
            HTTP_HOST=platform.hostname,
        )
    items = listed.json()["blocks"][0]["data"]["items"]
    assert [item["path"] for item in items] == ["/blog/pierwszy/"]
    assert items[0]["title"] == "Pierwszy"
    assert listed.json()["canonical_url"].endswith("/blog/")


def test_feed_and_sitemap_expose_what_a_crawler_cannot_reach_by_links() -> None:
    """A crawler that only follows links never reaches an article the menu does
    not point at, which is every article once the front page moves on."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="blog-feed", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="feed-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Treść wpisu w kanale.",
        idempotency_key="feed-entry-draft",
    )
    publish(client, entry.data["id"], idempotency_key="feed-entry-publish")
    platform = _verified_platform_domain(site.data["id"])

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        # The same `Accept` a feed reader and our own proxy send. Asking
        # with DRF's permissive default hid a 406 that every real client got.
        feed = PublicClient().get(
            "/api/v1/public/site/feed.xml",
            HTTP_HOST=platform.hostname,
            HTTP_ACCEPT="application/xml",
        )
        sitemap = PublicClient().get(
            "/api/v1/public/site/sitemap.xml",
            HTTP_HOST=platform.hostname,
            HTTP_ACCEPT="application/xml",
        )

    assert feed.status_code == 200
    assert feed["Content-Type"].startswith("application/rss+xml")
    feed_body = feed.content.decode()
    assert "<rss version=\"2.0\">" in feed_body
    assert "https://" + platform.hostname + "/blog/wpis/" in feed_body
    # RFC 822 day and month names, never the server locale's — a Polish locale
    # would emit "pon" and every reader would reject the date.
    assert any(day in feed_body for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))

    assert sitemap.status_code == 200
    sitemap_body = sitemap.content.decode()
    assert "https://" + platform.hostname + "/blog/" in sitemap_body
    assert "https://" + platform.hostname + "/blog/wpis/" in sitemap_body


def test_feed_escapes_entry_titles_rather_than_emitting_raw_markup() -> None:
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="blog-escape", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    hostile = client.post(
        "/api/v1/sites/collections/" + collection.data["id"] + "/entries/",
        {"slug": "wrogi", "locale": "pl", "title": "<script>alert(1)</script>"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="escape-entry",
    )
    save_entry_draft(
        client,
        hostile.data["id"],
        expected_version=0,
        text="Treść.",
        idempotency_key="escape-draft",
    )
    publish(client, hostile.data["id"], idempotency_key="escape-publish")
    platform = _verified_platform_domain(site.data["id"])

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        feed = PublicClient().get(
            "/api/v1/public/site/feed.xml",
            HTTP_HOST=platform.hostname,
            HTTP_ACCEPT="application/xml",
        )
    body = feed.content.decode()
    assert "&lt;script&gt;" in body
    assert "<script>" not in body


def test_public_projections_refuse_a_host_they_do_not_know() -> None:
    """The host is the whole routing key, so an unknown one must not fall back
    to some other organization's articles."""
    from rest_framework.test import APIClient as PublicClient

    feed = PublicClient().get(
        "/api/v1/public/site/feed.xml",
        HTTP_HOST="nieznany.example.test",
        HTTP_ACCEPT="application/xml",
    )
    sitemap = PublicClient().get(
        "/api/v1/public/site/sitemap.xml",
        HTTP_HOST="nieznany.example.test",
        HTTP_ACCEPT="application/xml",
    )
    assert feed.status_code == 404
    assert sitemap.status_code == 404


def test_robots_points_a_crawler_at_the_sitemap() -> None:
    """Nobody submits a sitemap by hand for a small client's site, so the only
    way a crawler learns it exists is this line."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="blog-robots", role_key="owner")
    site = create_site(client)
    platform = _verified_platform_domain(site.data["id"])

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        robots = PublicClient().get(
            "/api/v1/public/site/robots.txt",
            HTTP_HOST=platform.hostname,
            HTTP_ACCEPT="text/plain",
        )
    assert robots.status_code == 200
    assert robots["Content-Type"].startswith("text/plain")
    body = robots.content.decode()
    assert "Sitemap: https://" + platform.hostname + "/sitemap.xml" in body

    unknown = PublicClient().get(
        "/api/v1/public/site/robots.txt",
        HTTP_HOST="nieznany.example.test",
        HTTP_ACCEPT="text/plain",
    )
    assert unknown.status_code == 404


def test_collection_can_be_linked_from_the_published_menu() -> None:
    """Without this the blog exists at its own address and nothing on the site
    points at it, so a visitor never finds it."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from test_sites_api import (
        create_page,
        navigation_request,
        publish_site_request,
        save_draft,
        save_translation,
    )

    client, _, _ = sites_client(slug="blog-menu", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    page = create_page(client, site.data["id"])
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="menu-draft",
        heading="Strona startowa",
    )
    save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Strona startowa",
        idempotency_key="menu-translation-pl",
    )
    navigation_request(
        client,
        site.data["id"],
        expected_version=0,
        items=[{"page_id": page.data["id"], "parent_page_id": None, "visible": True}],
    )
    linked = client.put(
        f"/api/v1/sites/collections/{collection.data['id']}/navigation/",
        {"show_in_navigation": True},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert linked.status_code == 200
    assert linked.data["show_in_navigation"] is True

    publish_site_request(client, site.data["id"], idempotency_key="menu-publish")
    platform = _verified_platform_domain(site.data["id"])

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        home = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/start/"},
            HTTP_HOST=platform.hostname,
        )
    menu = home.json()["navigation"]
    assert [item["path"] for item in menu] == ["/start/", "/blog/"]
    assert menu[-1]["title"] == "Blog"


def test_only_a_person_links_a_collection_into_the_menu() -> None:
    """The menu is what a visitor is steered by, so a credential must not be
    able to put its own surface into it."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.collections import set_collection_navigation
    from saas_core.modules.shared.sites.services import PageAutomationForbidden
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="blog-menu-guard", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])

    from django.test import Client as PlainClient

    # The endpoint is session-only, so a credential never reaches the service.
    refused = PlainClient().put(
        f"/api/v1/sites/collections/{collection.data['id']}/navigation/",
        data='{"show_in_navigation": true}',
        content_type="application/json",
    )
    assert refused.status_code == 403

    # And the service refuses one too, so a later channel cannot reopen the gap
    # by forgetting what the route knew.
    with (
        activate_tenant_context(automation_context(organization.id, user.id)),
        pytest.raises(PageAutomationForbidden),
    ):
        set_collection_navigation(collection_id=collection.data["id"], show=True)


def test_published_media_is_public_and_unpublished_media_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An id in a URL must not be a read handle on any organization's media.

    Ids are guessable enough that "nobody will try" is not a security argument,
    so the rule is narrow: an asset is public only while something published
    names it.
    """
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from saas_core.modules.shared.sites.models import ContentEntryVersion
    from test_media_api import MemoryStorage
    from test_sites_api import create_media_asset

    client, organization, user = sites_client(slug="blog-media", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="ze-zdjeciem", idempotency_key="media-entry"
    )
    asset = create_media_asset(organization, user)
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (b"\x89PNG\r\n\x1a\n", "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage",
        lambda: storage,
    )

    saved = client.put(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                {
                    "block_type": "core.hero",
                    "schema_version": 3,
                    "data": {
                        "title": "Wpis ze zdjęciem",
                        "image": {"asset_id": str(asset.id), "alt": "Zdjęcie"},
                    },
                }
            ],
            "media_asset_ids": [str(asset.id)],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="media-draft",
    )
    assert saved.status_code == 201
    assert saved.data["media_asset_ids"] == [str(asset.id)]
    assert ContentEntryVersion.all_objects.filter(entry_id=entry.data["id"]).count() == 1

    platform = _verified_platform_domain(site.data["id"])
    media_path = f"/api/v1/public/site/media/{asset.id}/"

    # Nothing is published yet, so the picture is still private.
    unpublished = PublicClient().get(media_path, HTTP_HOST=platform.hostname)
    assert unpublished.status_code == 404

    publish(client, entry.data["id"], idempotency_key="media-publish")

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        served = PublicClient().get(media_path, HTTP_HOST=platform.hostname)
    assert served.status_code == 200
    assert served["Cache-Control"] == "public, max-age=31536000, immutable"
    assert served.content == b"\x89PNG\r\n\x1a\n"

    # A different site's visitor must not reach it, whatever id they guess.
    other_client, _, _ = sites_client(slug="blog-media-other", role_key="owner")
    other_site = create_site(other_client)
    other_platform = _verified_platform_domain(other_site.data["id"])
    stranger = PublicClient().get(media_path, HTTP_HOST=other_platform.hostname)
    assert stranger.status_code == 404


def test_hero_keeps_rendering_when_it_has_no_picture() -> None:
    """v2 heroes were saved before images existed and must survive untouched."""
    from saas_core.modules.shared.sites.block_contracts import validate_site_block

    validate_site_block(
        block_type="core.hero",
        schema_version=2,
        data={"title": "Bez zdjęcia"},
    )
    validate_site_block(
        block_type="core.hero",
        schema_version=3,
        data={"title": "Bez zdjęcia"},
    )


def test_public_media_reads_the_asset_inside_the_tenant_setting() -> None:
    """`media_mediaasset` enforces row-level security, so reading the asset
    before `SET LOCAL app.organization_id` finds nothing and every picture on
    every published page answers 404.

    The test database connects as an owner that bypasses RLS, which is why a
    green suite said nothing the first time. This asserts the statement order,
    which stays observable either way.
    """
    from django.db import connection
    from django.test import Client, override_settings
    from django.test.utils import CaptureQueriesContext

    from test_media_api import MemoryStorage
    from test_sites_api import create_media_asset

    client, organization, user = sites_client(slug="media-order", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="obrazek", idempotency_key="order-media"
    )
    asset = create_media_asset(organization, user)
    client.put(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Treść wpisu z obrazkiem."},
                }
            ],
            "media_asset_ids": [str(asset.id)],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="order-media-draft",
    )
    publish(client, entry.data["id"], idempotency_key="order-media-publish")
    platform = _verified_platform_domain(site.data["id"])

    storage = MemoryStorage()
    storage.objects[asset.object_key] = (b"\x89PNG\r\n\x1a\n", "image/png")
    with (
        override_settings(PUBLIC_SITE_SCHEME="https"),
        CaptureQueriesContext(connection) as captured,
    ):
        import saas_core.modules.shared.sites.public_media as media_module

        original = media_module.get_object_storage
        media_module.get_object_storage = lambda: storage
        try:
            response = Client().get(
                f"/api/v1/public/site/media/{asset.id}/",
                HTTP_HOST=platform.hostname,
            )
        finally:
            media_module.get_object_storage = original
    assert response.status_code == 200

    statements = [query["sql"] for query in captured.captured_queries]
    tenant_set = next(
        index
        for index, sql in enumerate(statements)
        if "app.organization_id" in sql and "SET LOCAL" in sql.upper()
    )
    asset_read = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "media_mediaasset"' in sql and sql.upper().startswith("SELECT")
    )
    assert tenant_set < asset_read
