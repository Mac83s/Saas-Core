from __future__ import annotations

from datetime import timedelta
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
    assert '<rss version="2.0" xmlns:dc=' in feed_body
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


def test_an_article_gets_a_second_language_that_publishes_on_its_own() -> None:
    """The Polish and English texts are two different texts, written and
    published at different times, so each keeps its own lifecycle."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="entry-i18n", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    polish = create_entry(
        client, collection.data["id"], slug="po-polsku", idempotency_key="i18n-pl"
    )
    save_entry_draft(
        client,
        polish.data["id"],
        expected_version=0,
        text="Treść po polsku.",
        idempotency_key="i18n-pl-draft",
    )
    publish(client, polish.data["id"], idempotency_key="i18n-pl-publish")

    english = client.post(
        f"/api/v1/sites/entries/{polish.data['id']}/translations/",
        {"locale": "en", "slug": "in-english", "title": "In English"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="i18n-en",
    )
    assert english.status_code == 201
    assert english.data["translation_group"] == polish.data["translation_group"]
    assert english.data["locale"] == "en"

    platform = _verified_platform_domain(site.data["id"])
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        served = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/po-polsku/"},
            HTTP_HOST=platform.hostname,
        )
    # The English version is still a draft, so advertising it would point a
    # search engine at a 404.
    assert list(served.json()["hreflang"]) == ["pl"]

    save_entry_draft(
        client,
        english.data["id"],
        expected_version=0,
        text="Text in English.",
        idempotency_key="i18n-en-draft",
    )
    publish(client, english.data["id"], idempotency_key="i18n-en-publish")

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        both = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/po-polsku/"},
            HTTP_HOST=platform.hostname,
        )
        index = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/"},
            HTTP_HOST=platform.hostname,
        )
    assert sorted(both.json()["hreflang"]) == ["en", "pl"]
    assert both.json()["hreflang"]["en"].endswith("/blog/in-english/")

    # One row per article, not one per language: listing both would show the
    # reader the same article twice under two titles.
    items = index.json()["blocks"][0]["data"]["items"]
    assert [item["path"] for item in items] == ["/blog/po-polsku/"]


def test_a_language_cannot_be_added_to_the_same_article_twice() -> None:
    client, _, _ = sites_client(slug="entry-i18n-dup", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="jeden", idempotency_key="dup-pl"
    )

    def translate(slug: str, idempotency_key: str) -> Any:
        return client.post(
            f"/api/v1/sites/entries/{entry.data['id']}/translations/",
            {"locale": "en", "slug": slug, "title": "In English"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(client),
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )

    assert translate("first", "dup-en-1").status_code == 201
    # A second English version would leave hreflang naming two addresses for
    # one language, which a search engine reads as a mistake.
    second = translate("second", "dup-en-2")
    assert second.status_code == 409
    assert second.data["code"] == "entry_translation_exists"

    listed = client.get(f"/api/v1/sites/entries/{entry.data['id']}/translations/")
    assert sorted(item["locale"] for item in listed.data) == ["en", "pl"]


def test_capabilities_describe_shape_and_limits_without_any_draft() -> None:
    """SeoContentRank has no database, so this read is how it learns what is
    possible — and it must not become a way to survey unpublished work."""
    from saas_core.modules.shared.sites.capabilities import CONTENT_CONTRACT_VERSION

    client, _, _ = sites_client(slug="capabilities", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="sekret", idempotency_key="cap-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Treść, której nikt jeszcze nie opublikował.",
        idempotency_key="cap-draft",
    )

    response = client.get("/api/v1/sites/capabilities/")
    assert response.status_code == 200
    body = response.json()

    assert body["contract_version"] == CONTENT_CONTRACT_VERSION
    assert body["locales"]["default"] in body["locales"]["supported"]
    block_types = {item["block_type"] for item in body["block_schemas"]}
    assert "core.hero" in block_types
    hero = next(item for item in body["block_schemas"] if item["block_type"] == "core.hero")
    assert hero["latest_version"] == max(hero["versions"])
    assert "article" in body["content_types"]["page_types"]
    assert "platform_blog" in body["content_types"]["site_purposes"]
    assert {item["key"] for item in body["quotas"]} == {"storage.bytes", "sites.max"}
    listed = next(
        item for item in body["sites"] if item["site_id"] == str(site.data["id"])
    )
    assert listed["purpose"] == "customer"
    assert listed["published"] is False

    # The unpublished text must appear nowhere in the reply, at any depth.
    assert "Treść, której nikt jeszcze nie opublikował." not in response.content.decode()
    assert "sekret" not in response.content.decode()


def test_capabilities_never_reach_across_the_tenant_boundary() -> None:
    first_client, _, _ = sites_client(slug="cap-first", role_key="owner")
    first_site = create_site(first_client)
    second_client, _, _ = sites_client(slug="cap-second", role_key="owner")
    second_site = create_site(second_client)

    body = second_client.get("/api/v1/sites/capabilities/").json()
    listed = {item["site_id"] for item in body["sites"]}
    assert str(second_site.data["id"]) in listed
    assert str(first_site.data["id"]) not in listed


def test_the_label_changes_nothing_about_how_a_page_is_published() -> None:
    """A platform article is rendered by exactly the code that renders a
    customer's; the day one of them branches on the label is the day the two
    surfaces start drifting apart."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from saas_core.modules.shared.sites.models import Page, PageType, Site, SitePurpose

    client, _, _ = sites_client(slug="label-neutral", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(
        client, collection.data["id"], slug="artykul", idempotency_key="label-entry"
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Ta sama treść niezależnie od etykiety.",
        idempotency_key="label-draft",
    )
    publish(client, entry.data["id"], idempotency_key="label-publish")
    platform = _verified_platform_domain(site.data["id"])

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        as_customer = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/artykul/"},
            HTTP_HOST=platform.hostname,
        )

    # Relabel both the site and its pages, publish nothing new, ask again.
    Site.all_objects.filter(pk=site.data["id"]).update(
        purpose=SitePurpose.PLATFORM_BLOG
    )
    Page.all_objects.filter(site_id=site.data["id"]).update(
        page_type=PageType.ARTICLE
    )
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        as_platform = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/artykul/"},
            HTTP_HOST=platform.hostname,
        )

    assert as_customer.status_code == as_platform.status_code == 200
    assert as_customer.json() == as_platform.json()


def test_a_customer_cannot_label_their_site_as_the_platform() -> None:
    """The label is what inventory reasons about, so claiming to be us in it
    would be claiming to be us everywhere that reads it."""
    client, _, _ = sites_client(slug="label-guard", role_key="owner")
    site = create_site(client)

    refused = client.put(
        f"/api/v1/sites/{site.data['id']}/purpose/",
        {"purpose": "platform_marketing"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert refused.status_code == 403
    assert refused.data["code"] == "site_purpose_mismatch"

    # Its own purpose is fine and is a no-op it may repeat.
    allowed = client.put(
        f"/api/v1/sites/{site.data['id']}/purpose/",
        {"purpose": "customer"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert allowed.status_code == 200
    assert allowed.data["purpose"] == "customer"


def test_a_credential_cannot_relabel_the_surface_it_writes() -> None:
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.services import (
        PageAutomationForbidden,
        set_site_purpose,
    )
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="label-key", role_key="owner")
    site = create_site(client)

    with (
        activate_tenant_context(automation_context(organization.id, user.id)),
        pytest.raises(PageAutomationForbidden),
    ):
        set_site_purpose(site_id=site.data["id"], purpose="platform_blog")


def test_page_type_is_a_person_s_call_and_reaches_the_listing() -> None:
    """An optimiser told the contact page is a landing page will rewrite it
    like one, so the type has to be settable — and only by a person."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.services import (
        PageAutomationForbidden,
        set_page_type,
    )
    from test_sites_api import automation_context, create_page

    client, organization, user = sites_client(slug="page-type", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"])

    changed = client.put(
        f"/api/v1/sites/pages/{page.data['id']}/type/",
        {"page_type": "contact"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert changed.status_code == 200
    assert changed.data["page_type"] == "contact"

    listed = client.get(f"/api/v1/sites/{site.data['id']}/pages/")
    assert listed.json()["items"][0]["page_type"] == "contact"

    unknown = client.put(
        f"/api/v1/sites/pages/{page.data['id']}/type/",
        {"page_type": "nieznany"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert unknown.status_code == 400

    with (
        activate_tenant_context(automation_context(organization.id, user.id)),
        pytest.raises(PageAutomationForbidden),
    ):
        set_page_type(page_id=page.data["id"], page_type="article")


def _publishable_page(client, site_id: str, *, key: str, slug: str, title: str):
    from test_sites_api import create_page, save_draft, save_translation

    page = create_page(client, site_id, key=key, idempotency_key=f"w963-{key}")
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key=f"w963-{key}-draft",
        heading=title,
    )
    save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug=slug,
        title=title,
        description=f"Opis strony {title}",
        idempotency_key=f"w963-{key}-pl",
    )
    return page


def test_reordering_the_menu_never_moves_a_page_s_address() -> None:
    """The whole point of a hierarchy is that rearranging it is cheap. It stops
    being cheap the moment a reorder costs every page its URL."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from test_sites_api import navigation_request, publish_site_request

    client, _, _ = sites_client(slug="w963-reorder", role_key="owner")
    site = create_site(client)
    home = _publishable_page(client, site.data["id"], key="home", slug="start", title="Start")
    offer = _publishable_page(
        client, site.data["id"], key="oferta", slug="oferta", title="Oferta"
    )
    navigation_request(
        client,
        site.data["id"],
        expected_version=0,
        items=[
            {"page_id": home.data["id"], "parent_page_id": None, "visible": True},
            {"page_id": offer.data["id"], "parent_page_id": None, "visible": True},
        ],
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-publish-1")
    platform = _verified_platform_domain(site.data["id"])

    # Reorder and nest, publish again, and ask for the same address.
    navigation_request(
        client,
        site.data["id"],
        expected_version=1,
        items=[
            {"page_id": offer.data["id"], "parent_page_id": None, "visible": True},
            {
                "page_id": home.data["id"],
                "parent_page_id": offer.data["id"],
                "visible": True,
            },
        ],
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-publish-2")

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        served = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/start/"},
            HTTP_HOST=platform.hostname,
        )
    assert served.status_code == 200
    assert served.json()["canonical_url"].endswith("/start/")
    # The trail follows the tree, so nesting is visible without the URL moving.
    assert [item["path"] for item in served.json()["breadcrumbs"]] == [
        "/oferta/",
        "/start/",
    ]


def test_changing_a_published_url_leaves_a_redirect_and_an_audit_entry() -> None:
    """Every link, bookmark and search result points at the published address,
    so moving it without a redirect is how a site loses its ranking."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    from saas_core.modules.core.organizations.models import OrganizationAuditEntry
    from test_sites_api import publish_site_request

    client, _, _ = sites_client(slug="w963-url", role_key="owner")
    site = create_site(client)
    page = _publishable_page(
        client, site.data["id"], key="oferta", slug="oferta", title="Oferta"
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-url-publish")
    platform = _verified_platform_domain(site.data["id"])

    # The slug locks on publication; this is the one door past it.
    refused = client.put(
        f"/api/v1/sites/pages/{page.data['id']}/url/",
        {"locale": "pl", "slug": "uslugi", "reason": ""},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert refused.status_code == 400

    moved = client.put(
        f"/api/v1/sites/pages/{page.data['id']}/url/",
        {"locale": "pl", "slug": "uslugi", "reason": "Nowa nazwa działu."},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert moved.status_code == 200
    assert moved.data["from_path"] == "/oferta/"
    assert moved.data["to_path"] == "/uslugi/"
    assert OrganizationAuditEntry.objects.filter(action="sites.page.url_changed").exists()

    listed = client.get(f"/api/v1/sites/{site.data['id']}/redirects/")
    assert [item["from_path"] for item in listed.json()] == ["/oferta/"]

    # Until the site is published again the old address still serves the page:
    # a redirect a visitor gets has to come from the snapshot, not the draft.
    publish_site_request(client, site.data["id"], idempotency_key="w963-url-publish-2")

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        old = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/oferta/"},
            HTTP_HOST=platform.hostname,
        )
        new = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/uslugi/"},
            HTTP_HOST=platform.hostname,
        )
    assert old.status_code == 308
    assert old["Location"].endswith("/uslugi/")
    assert new.status_code == 200


def test_moving_a_page_twice_does_not_build_a_redirect_chain() -> None:
    """Two hops lose a little of whatever the first was carrying, and search
    engines stop following long chains."""
    from saas_core.modules.shared.sites.models import SiteRedirect
    from test_sites_api import publish_site_request

    client, _, _ = sites_client(slug="w963-chain", role_key="owner")
    site = create_site(client)
    page = _publishable_page(
        client, site.data["id"], key="oferta", slug="pierwszy", title="Oferta"
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-chain-publish")

    for slug in ("drugi", "trzeci"):
        assert (
            client.put(
                f"/api/v1/sites/pages/{page.data['id']}/url/",
                {"locale": "pl", "slug": slug, "reason": f"Zmiana na {slug}."},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_value(client),
            ).status_code
            == 200
        )

    targets = dict(
        SiteRedirect.all_objects.filter(site_id=site.data["id"]).values_list(
            "from_path", "to_path"
        )
    )
    assert targets == {"/pierwszy/": "/trzeci/", "/drugi/": "/trzeci/"}


def test_rolling_navigation_back_keeps_newer_page_drafts() -> None:
    """A rollback restores what was published, and a draft written since is not
    that — losing it would make rollback something nobody dares press."""
    from test_sites_api import navigation_request, publish_site_request, save_draft

    client, _, _ = sites_client(slug="w963-rollback", role_key="owner")
    site = create_site(client)
    home = _publishable_page(client, site.data["id"], key="home", slug="start", title="Start")
    navigation_request(
        client,
        site.data["id"],
        expected_version=0,
        items=[{"page_id": home.data["id"], "parent_page_id": None, "visible": True}],
    )
    first = publish_site_request(
        client, site.data["id"], idempotency_key="w963-rb-publish-1"
    )
    assert first.status_code == 201

    navigation_request(
        client,
        site.data["id"],
        expected_version=1,
        items=[{"page_id": home.data["id"], "parent_page_id": None, "visible": False}],
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-rb-publish-2")

    # A newer draft, written after both publications.
    save_draft(
        client,
        home.data["id"],
        expected_version=1,
        idempotency_key="w963-rb-newer-draft",
        heading="Treść napisana po publikacji",
    )
    draft_before = client.get(f"/api/v1/sites/pages/{home.data['id']}/draft/").json()

    rollback = client.post(
        f"/api/v1/sites/{site.data['id']}/publications/{first.data['id']}/rollback/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="w963-rb-rollback",
    )
    assert rollback.status_code == 201

    draft_after = client.get(f"/api/v1/sites/pages/{home.data['id']}/draft/").json()
    assert draft_after["version"] == draft_before["version"]
    assert draft_after["blocks"] == draft_before["blocks"]


def test_a_credential_cannot_move_a_published_url() -> None:
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.services import (
        PageAutomationForbidden,
        change_page_url,
    )
    from test_sites_api import automation_context, publish_site_request

    client, organization, user = sites_client(slug="w963-url-key", role_key="owner")
    site = create_site(client)
    page = _publishable_page(
        client, site.data["id"], key="oferta", slug="oferta", title="Oferta"
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-key-publish")

    # Moving a URL costs whatever ranking it had, and whether that trade is
    # worth it is not an optimiser's decision to make for its customer.
    with (
        activate_tenant_context(automation_context(organization.id, user.id)),
        pytest.raises(PageAutomationForbidden),
    ):
        change_page_url(
            page_id=page.data["id"],
            locale="pl",
            slug="przejete",
            reason="Automatyczna zmiana.",
        )


def test_moving_a_page_back_to_an_address_it_used_to_have() -> None:
    """Somebody renames a page, decides against it, and renames it back. The
    address that answers directly must not also redirect away from itself."""
    from saas_core.modules.shared.sites.models import SiteRedirect
    from test_sites_api import publish_site_request

    client, _, _ = sites_client(slug="w963-back", role_key="owner")
    site = create_site(client)
    page = _publishable_page(
        client, site.data["id"], key="oferta", slug="oferta", title="Oferta"
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-back-publish")

    for slug, reason in (("uslugi", "Nowa nazwa."), ("oferta", "Jednak stara.")):
        assert (
            client.put(
                f"/api/v1/sites/pages/{page.data['id']}/url/",
                {"locale": "pl", "slug": slug, "reason": reason},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_value(client),
            ).status_code
            == 200
        )

    targets = dict(
        SiteRedirect.all_objects.filter(site_id=site.data["id"]).values_list(
            "from_path", "to_path"
        )
    )
    assert targets == {"/uslugi/": "/oferta/"}


def test_a_redirect_can_be_removed_and_the_removal_is_audited() -> None:
    """A mistyped slug otherwise leaves a permanent redirect from an address
    nobody ever linked to, and nothing in the product could remove it."""
    from saas_core.modules.core.organizations.models import OrganizationAuditEntry
    from saas_core.modules.shared.sites.models import SiteRedirect
    from test_sites_api import publish_site_request

    client, _, _ = sites_client(slug="w963-drop", role_key="owner")
    site = create_site(client)
    page = _publishable_page(
        client, site.data["id"], key="oferta", slug="oferta", title="Oferta"
    )
    publish_site_request(client, site.data["id"], idempotency_key="w963-drop-publish")
    moved = client.put(
        f"/api/v1/sites/pages/{page.data['id']}/url/",
        {"locale": "pl", "slug": "ofreta", "reason": "Literówka."},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert moved.status_code == 200

    dropped = client.delete(
        f"/api/v1/sites/redirects/{moved.data['id']}/",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert dropped.status_code == 204
    assert not SiteRedirect.all_objects.filter(site_id=site.data["id"]).exists()
    assert OrganizationAuditEntry.objects.filter(
        action="sites.redirect.deleted"
    ).exists()
    assert (
        client.delete(
            f"/api/v1/sites/redirects/{moved.data['id']}/",
            HTTP_X_CSRFTOKEN=csrf_value(client),
        ).status_code
        == 404
    )


def test_a_translation_does_not_shadow_the_article_it_was_made_from() -> None:
    """Both languages once claimed the same address and which one a visitor got
    depended on row order."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="entry-locale", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    platform = _verified_platform_domain(site.data["id"])

    source = create_entry(
        client, collection.data["id"], slug="wpis", idempotency_key="locale-source"
    )
    save_entry_draft(
        client,
        source.data["id"],
        expected_version=0,
        text="Treść po polsku.",
        idempotency_key="locale-source-draft",
    )
    publish(client, source.data["id"], idempotency_key="locale-source-publish")

    # Deliberately the same slug: an editor translating an article usually
    # keeps the address, and nothing in the model stops them.
    translation = client.post(
        f"/api/v1/sites/entries/{source.data['id']}/translations/",
        {"locale": "en", "slug": "wpis", "title": "Entry"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="locale-translation",
    )
    assert translation.status_code == 201
    save_entry_draft(
        client,
        translation.data["id"],
        expected_version=0,
        text="Text in English.",
        idempotency_key="locale-translation-draft",
    )
    publish(client, translation.data["id"], idempotency_key="locale-translation-publish")

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        polish = PublicClient().get(
            "/api/v1/public/site/", {"path": "/blog/wpis/"}, HTTP_HOST=platform.hostname
        )
        english = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/en/blog/wpis/"},
            HTTP_HOST=platform.hostname,
        )
    assert polish.status_code == 200
    assert english.status_code == 200
    assert polish.json()["blocks"][0]["data"]["text"] == "Treść po polsku."
    assert english.json()["blocks"][0]["data"]["text"] == "Text in English."
    # And each names the other, so a search engine sees one article in two
    # languages rather than two competing for one address.
    assert set(polish.json()["hreflang"]) == {"pl", "en"}
    assert polish.json()["hreflang"]["en"].endswith("/en/blog/wpis/")


def _bulk_published_entries(collection_id: str, site_id: str, count: int) -> None:
    """Writes `count` published entries straight to the database.

    Going through the API `count` times would test the API, not the archive,
    and would take minutes. What is under test here is what happens to reading
    and publishing once the archive is large.
    """
    from django.utils import timezone

    from saas_core.modules.shared.sites.models import (
        ContentCollection,
        ContentEntryPublication,
        ContentEntryState,
        ContentEntryVersion,
    )

    collection = ContentCollection.all_objects.select_related("site").get(
        pk=collection_id
    )
    organization_id = collection.organization_id
    actor_id = collection.created_by_id
    now = timezone.now()
    entries = [
        ContentEntry(
            organization_id=organization_id,
            collection=collection,
            site_id=site_id,
            slug=f"archiwum-{number:05d}",
            locale="pl",
            title=f"Archiwalny wpis {number}",
            excerpt="Zajawka.",
            author_name="Redakcja",
            state=ContentEntryState.PUBLISHED,
            version=1,
            published_at=now - timedelta(minutes=number),
            created_by_id=actor_id,
            idempotency_key=f"bulk-{number}",
            request_hash="0" * 64,
        )
        for number in range(count)
    ]
    ContentEntry.all_objects.bulk_create(entries, batch_size=500)

    versions = [
        ContentEntryVersion(
            organization_id=organization_id,
            entry=entry,
            number=1,
            blocks=[
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Treść archiwalna."},
                }
            ],
            created_by_id=actor_id,
            idempotency_key=f"bulk-version-{entry.slug}",
            request_hash="0" * 64,
        )
        for entry in entries
    ]
    ContentEntryVersion.all_objects.bulk_create(versions, batch_size=500)

    publications = [
        ContentEntryPublication(
            organization_id=organization_id,
            entry=entry,
            sequence=1,
            snapshot={
                "schema_version": 1,
                "entry_id": str(entry.id),
                "collection_key": collection.key,
                "base_path": collection.base_path,
                "locale": entry.locale,
                "slug": entry.slug,
                "path": f"/{collection.base_path}/{entry.slug}/",
                "title": entry.title,
                "excerpt": entry.excerpt,
                "author_name": entry.author_name,
                "noindex": False,
                "version": 1,
                "blocks": version.blocks,
                "media_asset_ids": [],
            },
            snapshot_hash="0" * 64,
            created_by_id=actor_id,
            idempotency_key=f"bulk-publication-{entry.slug}",
        )
        for entry, version in zip(entries, versions, strict=True)
    ]
    ContentEntryPublication.all_objects.bulk_create(publications, batch_size=500)
    for entry, version, publication in zip(
        entries, versions, publications, strict=True
    ):
        entry.current_draft = version
        entry.current_publication = publication
    ContentEntry.all_objects.bulk_update(
        entries, ["current_draft", "current_publication"], batch_size=500
    )


def test_a_large_archive_paginates_instead_of_answering_with_one_huge_page() -> None:
    """A thousand articles on one page is slow to render, slow to read, and
    crawled as a single enormous document."""
    from django.test import override_settings
    from rest_framework.test import APIClient as PublicClient

    client, _, _ = sites_client(slug="archive", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    platform = _verified_platform_domain(site.data["id"])
    _bulk_published_entries(collection.data["id"], site.data["id"], 1000)

    with override_settings(PUBLIC_SITE_SCHEME="https"):
        first = PublicClient().get(
            "/api/v1/public/site/", {"path": "/blog/"}, HTTP_HOST=platform.hostname
        )
        second = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/strona/2/"},
            HTTP_HOST=platform.hostname,
        )
        past_the_end = PublicClient().get(
            "/api/v1/public/site/",
            {"path": "/blog/strona/500/"},
            HTTP_HOST=platform.hostname,
        )

    assert first.status_code == 200
    listed = first.json()["blocks"][0]["data"]["items"]
    assert len(listed) == 10
    # Newest first, and the newest is the one published most recently.
    assert listed[0]["title"] == "Archiwalny wpis 0"
    assert first.json()["pagination"]["pages"] == 100
    assert first.json()["pagination"]["previous_path"] is None
    assert first.json()["pagination"]["next_path"] == "/blog/strona/2/"

    assert second.status_code == 200
    assert second.json()["blocks"][0]["data"]["items"][0]["title"] == (
        "Archiwalny wpis 10"
    )
    # Page two is canonical to itself: pointing it at page one would tell a
    # search engine that ninety of the hundred pages do not exist.
    assert second.json()["canonical_url"].endswith("/blog/strona/2/")
    assert second.json()["pagination"]["previous_path"] == "/blog/"

    # A page past the end is a wrong address, not an empty one. Answering 200
    # would put an unbounded number of thin duplicates into the index.
    assert past_the_end.status_code == 404


def test_publishing_one_article_costs_the_same_whatever_the_archive_holds() -> None:
    """The promise collections exist to keep (ADR-035 §1), measured rather than
    assumed: the same work for the first article and the thousand-and-first."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client, _, _ = sites_client(slug="archive-cost", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    collection_id = collection.data["id"]

    def publish_one(marker: str) -> int:
        entry = create_entry(
            client, collection_id, slug=f"wpis-{marker}", idempotency_key=f"c-{marker}"
        )
        save_entry_draft(
            client,
            entry.data["id"],
            expected_version=0,
            text="Treść.",
            idempotency_key=f"c-draft-{marker}",
        )
        with CaptureQueriesContext(connection) as captured:
            response = publish(
                client, entry.data["id"], idempotency_key=f"c-publish-{marker}"
            )
        assert response.status_code == 201
        return len(captured.captured_queries)

    empty_archive = publish_one("pierwszy")
    _bulk_published_entries(collection_id, site.data["id"], 1000)
    full_archive = publish_one("po-tysiacu")

    # Not "roughly the same": the statements a publication runs must not depend
    # on the archive at all, or the thousandth article is the one that stops
    # working.
    assert full_archive == empty_archive
