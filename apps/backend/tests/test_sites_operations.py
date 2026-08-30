"""Operation reconciliation after a caller loses a mutation response (W9.6.7)."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User
from saas_core.modules.shared.notifications.models import ApiKey, ApiKeyCredentialRoute
from saas_core.modules.shared.sites.models import (
    ContentEntryVersion,
    PageVersion,
    Publication,
)
from test_sites_api import create_page, create_site, save_draft, sites_client
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


def _status(client: Any, idempotency_key: str) -> Any:
    return client.get(f"/api/v1/sites/operations/{idempotency_key}/")


def _api_key_client(*, organization: Any, created_by: User, marker: str) -> Client:
    raw = "sc_live_" + marker * 32
    secret_hash = make_password(raw)
    api_key = ApiKey.all_objects.create(
        organization=organization,
        name=f"Status {marker}",
        prefix=raw[:18],
        secret_hash=secret_hash,
        scopes=["content:read"],
        created_by=created_by,
    )
    ApiKeyCredentialRoute.objects.create(
        prefix=raw[:18],
        api_key_id=api_key.id,
        organization_id=organization.id,
        secret_hash=secret_hash,
        scopes=["content:read"],
    )
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {raw}"
    return client


def test_status_identifies_every_supported_operation_resource() -> None:
    """A timed-out caller must learn the exact resource already created."""
    client, organization, user = sites_client(slug="operation-types", role_key="owner")
    site = create_site(client)
    page = create_page(
        client,
        site.data["id"],
        idempotency_key="operation-page",
    )
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="operation-page-version",
        heading="Status operacji",
    )
    page_version = PageVersion.all_objects.get(page_id=page.data["id"])
    site_publication = Publication.all_objects.create(
        organization=organization,
        site_id=site.data["id"],
        sequence=1,
        snapshot_schema_version=1,
        snapshot={},
        snapshot_hash="0" * 64,
        created_by=user,
        idempotency_key="operation-site-publication",
    )
    collection = create_collection(
        client,
        site.data["id"],
        idempotency_key="operation-collection",
    )
    entry = create_entry(
        client,
        collection.data["id"],
        slug="status-operacji",
        idempotency_key="operation-entry",
    )
    save_entry_draft(
        client,
        entry.data["id"],
        expected_version=0,
        text="Treść wpisu.",
        idempotency_key="operation-entry-version",
    )
    entry_version = ContentEntryVersion.all_objects.get(entry_id=entry.data["id"])
    published = publish(
        client,
        entry.data["id"],
        idempotency_key="operation-entry-publication",
    )

    expected = {
        "operation-page": ("page", page.data["id"]),
        "operation-page-version": ("page_version", page_version.id),
        "operation-site-publication": ("site_publication", site_publication.id),
        "operation-collection": ("content_collection", collection.data["id"]),
        "operation-entry": ("content_entry", entry.data["id"]),
        "operation-entry-version": ("content_entry_version", entry_version.id),
        "operation-entry-publication": (
            "content_entry_publication",
            published.data["id"],
        ),
    }
    for idempotency_key, (resource_type, resource_id) in expected.items():
        response = _status(client, idempotency_key)
        assert response.status_code == 200
        assert response.json() == {
            "idempotency_key": idempotency_key,
            "found": True,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "created_at": response.json()["created_at"],
        }
        assert response.json()["created_at"] is not None


def test_unknown_status_is_a_side_effect_free_success() -> None:
    """Absence is a definitive reconciliation result, not an ambiguous 404."""
    _, organization, owner = sites_client(slug="operation-missing", role_key="owner")
    client = _api_key_client(
        organization=organization,
        created_by=owner,
        marker="s",
    )
    with CaptureQueriesContext(connection) as captured:
        response = _status(client, "operation-not-recorded")

    assert response.status_code == 200
    assert response.json() == {
        "idempotency_key": "operation-not-recorded",
        "found": False,
        "resource_type": None,
        "resource_id": None,
        "created_at": None,
    }
    # Session bookkeeping writes `identity_usersession.last_seen_at` on every
    # authenticated request, so the assertion is about the tables this endpoint
    # could plausibly affect. Widening it back catches the middleware and says
    # nothing about the endpoint.
    writes = [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        and "sites_" in query["sql"]
    ]
    assert writes == []


def test_status_is_scoped_to_the_calling_tenant_and_actor() -> None:
    """A credential must not discover another actor's or tenant's operation."""
    client, organization, owner = sites_client(slug="operation-owner", role_key="owner")
    site = create_site(client)
    page = create_page(
        client,
        site.data["id"],
        idempotency_key="operation-private",
    )
    other_actor = User.objects.create_user(email="other-actor@example.test")
    owner_key = _api_key_client(
        organization=organization,
        created_by=owner,
        marker="o",
    )
    other_actor_key = _api_key_client(
        organization=organization,
        created_by=other_actor,
        marker="a",
    )
    _, foreign_organization, foreign_owner = sites_client(
        slug="operation-foreign",
        role_key="owner",
    )
    foreign_key = _api_key_client(
        organization=foreign_organization,
        created_by=foreign_owner,
        marker="f",
    )

    own = _status(owner_key, "operation-private")
    wrong_actor = _status(other_actor_key, "operation-private")
    wrong_tenant = _status(foreign_key, "operation-private")

    assert own.status_code == 200
    assert own.json()["resource_id"] == str(page.data["id"])
    assert wrong_actor.status_code == 200
    assert wrong_actor.json()["found"] is False
    assert wrong_tenant.status_code == 200
    assert wrong_tenant.json()["found"] is False


def test_status_requires_authentication_permission_and_read_entitlement() -> None:
    """Reconciliation reveals identifiers and remains protected like other reads."""
    anonymous = APIClient().get("/api/v1/sites/operations/operation-private/")
    disabled_client, _, _ = sites_client(
        slug="operation-disabled",
        role_key="owner",
        feature_enabled=False,
    )
    disabled = _status(disabled_client, "operation-private")

    assert anonymous.status_code == 403
    assert disabled.status_code == 403
    assert disabled.json()["code"] == "entitlement_required"
