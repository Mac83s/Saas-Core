"""Supervision: what an operator can see about integrations, and stop (W9.6.8).

The panel is only as good as what it can show. These are about the read behind
it — scope, activity, the reasoning behind a proposal — and about the emergency
stop being reachable in one call.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.utils import timezone

from test_sites_api import create_page, create_site, csrf_value, sites_client
from test_sites_collections import create_collection

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def _grant(organization: Any, user: Any, site_id: Any, **fields: Any) -> Any:
    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    return ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=fields.pop("credential_id", uuid7()),
        site_id=site_id,
        mode=fields.pop("mode", "draft_write"),
        created_by=user,
        **fields,
    )


def test_the_panel_sees_scope_bounds_and_when_a_credential_last_acted() -> None:
    """An operator who cannot see the integrations cannot supervise them."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.models import Page, PageAutomationPolicy
    from saas_core.modules.shared.sites.services import save_draft
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="conn-list", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="conn-page")
    credential_id = uuid7()
    _grant(
        organization,
        user,
        site.data["id"],
        credential_id=credential_id,
        expires_at=timezone.now() + timedelta(days=7),
        max_changes_per_day=25,
    )
    Page.all_objects.filter(pk=page.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )
    with activate_tenant_context(
        automation_context(organization.id, user.id, credential_id=credential_id)
    ):
        save_draft(
            page_id=page.data["id"],
            expected_version=0,
            blocks=[
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Propozycja."},
                }
            ],
            media_asset_ids=[],
            idempotency_key="conn-automation-draft",
        )

    listed = client.get("/api/v1/sites/connections/")
    assert listed.status_code == 200
    row = next(
        item for item in listed.json() if item["credential_id"] == str(credential_id)
    )
    assert row["mode"] == "draft_write"
    assert row["scope"] == {
        "kind": "site",
        "id": str(site.data["id"]),
        "name": "main-site",
    }
    assert row["max_changes_per_day"] == 25
    assert row["active"] is True
    # Read from the drafts the credential actually authored, not from a counter
    # somebody has to remember to increment.
    assert row["last_activity_at"] is not None


def test_a_revoked_grant_stays_on_the_list_and_stops_being_active() -> None:
    """"Who had access last month" is a question the panel has to answer, and a
    list that silently drops revoked rows answers it wrongly."""
    client, organization, user = sites_client(slug="conn-revoke", role_key="owner")
    site = create_site(client)
    grant = _grant(organization, user, site.data["id"])

    refused = client.post(
        f"/api/v1/sites/connections/{grant.id}/revoke/",
        {"reason": ""},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    # An emergency stop nobody wrote a reason for is one nobody can explain.
    assert refused.status_code == 400

    revoked = client.post(
        f"/api/v1/sites/connections/{grant.id}/revoke/",
        {"reason": "Podejrzana aktywność w nocy."},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert revoked.status_code == 200
    row = next(
        item for item in revoked.json() if item["grant_id"] == str(grant.id)
    )
    assert row["active"] is False
    assert row["revoked_at"] is not None


def test_a_credential_cannot_read_the_list_of_credentials() -> None:
    """An integration able to enumerate the grants could map its own way to a
    wider one, so supervision is a screen for people only."""
    from django.contrib.auth.hashers import make_password
    from django.test import Client

    from saas_core.modules.shared.notifications.models import (
        ApiKey,
        ApiKeyCredentialRoute,
    )

    client, organization, user = sites_client(slug="conn-key", role_key="owner")
    site = create_site(client)
    _grant(organization, user, site.data["id"])

    raw = "sc_live_" + "c" * 32
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

    # A key that reads inventory perfectly well is still refused here.
    refused = Client().get(
        "/api/v1/sites/connections/", HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    assert refused.status_code in {401, 403}
    reachable = Client().get(
        "/api/v1/sites/inventory/", HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    assert reachable.status_code == 200

    revoke = Client().post(
        f"/api/v1/sites/connections/{uuid7()}/revoke/",
        data={"reason": "Sam siebie odwołuję."},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    assert revoke.status_code in {401, 403}


def test_a_proposal_keeps_the_reasoning_a_person_needs_to_judge_it() -> None:
    """Without it the queue offers "an integration changed this" and a diff,
    which is not enough for anybody to say yes or no honestly."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.change_sets import apply_change_set
    from saas_core.modules.shared.sites.models import Page, PageAutomationPolicy
    from test_sites_api import automation_context
    from test_sites_api import save_draft as save_draft_request

    client, organization, user = sites_client(slug="conn-proposal", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="prop-page")
    save_draft_request(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="prop-draft",
        heading="Stary nagłówek",
    )
    credential_id = uuid7()
    _grant(organization, user, site.data["id"], credential_id=credential_id)
    Page.all_objects.filter(pk=page.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )

    document = {
        "contract_version": 1,
        "idempotency_key": f"prop-{uuid7()}",
        "target": {
            "kind": "site_page",
            "site_id": str(site.data["id"]),
            "page_id": str(page.data["id"]),
            "locale": "pl",
        },
        "base": {
            "version": 1,
            "snapshot_hash": "sha256:" + "c3" * 32,
            "observed_at": "2026-08-30T09:00:00Z",
        },
        "rationale": {
            "summary": "Strona nie odpowiada na intencję frazy, po której ma ruch.",
            "risk": "medium",
            "expected_outcome": "Zgodność treści z intencją wyszukiwania.",
            "sources": [
                {
                    "kind": "search_console",
                    "reference": "query=fizjoterapia;position=14.2",
                    "observed_at": "2026-08-29T22:00:00Z",
                }
            ],
        },
        "commands": [
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Nowa treść."},
                },
            }
        ],
    }
    context = automation_context(
        organization.id, user.id, credential_id=credential_id
    )
    with activate_tenant_context(context):
        apply_change_set(document, context, idempotency_key="prop-apply")

    queued = client.get("/api/v1/sites/proposals/")
    assert queued.status_code == 200
    proposal = next(
        item for item in queued.json() if item["resource_id"] == str(page.data["id"])
    )
    assert proposal["risk"] == "medium"
    assert proposal["commands"] == ["block.replace"]
    # Verbatim, so the panel shows what SeoContentRank claimed rather than our
    # paraphrase of it.
    assert proposal["sources"][0]["kind"] == "search_console"
    assert "position=14.2" in proposal["sources"][0]["reference"]


def test_rejecting_a_proposal_puts_the_draft_back_to_what_it_was() -> None:
    """Rejecting has to mean something, and the only honest meaning available
    is "undo what the automation wrote"."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.change_sets import apply_change_set
    from saas_core.modules.shared.sites.models import (
        Page,
        PageAutomationPolicy,
        PageVersion,
    )
    from test_sites_api import automation_context
    from test_sites_api import save_draft as save_draft_request

    client, organization, user = sites_client(slug="conn-reject", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="rej-page")
    save_draft_request(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="rej-draft",
        heading="Tekst, ktory napisal czlowiek",
    )
    credential_id = uuid7()
    _grant(organization, user, site.data["id"], credential_id=credential_id)
    Page.all_objects.filter(pk=page.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )

    document = {
        "contract_version": 1,
        "idempotency_key": f"rej-{uuid7()}",
        "target": {
            "kind": "site_page",
            "site_id": str(site.data["id"]),
            "page_id": str(page.data["id"]),
            "locale": "pl",
        },
        "base": {
            "version": 1,
            "snapshot_hash": "sha256:" + "d4" * 32,
            "observed_at": "2026-08-30T09:00:00Z",
        },
        "rationale": {
            "summary": "Propozycja do odrzucenia.",
            "risk": "high",
            "sources": [
                {
                    "kind": "editorial",
                    "reference": "brief/2026-08",
                    "observed_at": "2026-08-29T10:00:00Z",
                }
            ],
        },
        "commands": [
            {
                "command": "block.replace",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Tekst od automatyzacji."},
                },
            }
        ],
    }
    context = automation_context(organization.id, user.id, credential_id=credential_id)
    with activate_tenant_context(context):
        apply_change_set(document, context, idempotency_key="rej-apply")

    queued = client.get("/api/v1/sites/proposals/").json()
    proposal = next(
        item for item in queued if item["resource_id"] == str(page.data["id"])
    )
    versions_before = PageVersion.all_objects.filter(page_id=page.data["id"]).count()

    discarded = client.post(
        f"/api/v1/sites/proposals/{proposal['proposal_id']}/discard/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert discarded.status_code == 200
    assert discarded.json()["restored_version"] == 1

    draft = client.get(f"/api/v1/sites/pages/{page.data['id']}/draft/").json()
    assert draft["version"] == 1
    assert draft["blocks"][0]["data"]["heading"] == "Tekst, ktory napisal czlowiek"
    # Nothing is deleted: the rejected text stays on record, so a rejection can
    # be looked at afterwards.
    assert (
        PageVersion.all_objects.filter(page_id=page.data["id"]).count()
        == versions_before
    )
    assert client.get("/api/v1/sites/proposals/").json() == []


def test_capabilities_answers_the_handshake_a_connector_needs() -> None:
    """SeoContentRank refuses to act on a target that has not told it the mode,
    the commands and the contract versions. Without them it cannot start."""
    from saas_core.modules.shared.sites.capabilities import supported_commands

    client, _, _ = sites_client(slug="handshake", role_key="owner")
    create_site(client)

    answer = client.get("/api/v1/sites/capabilities/")
    assert answer.status_code == 200
    body = answer.json()
    assert body["contract_versions"] == ["1"]
    # Derived from the frozen schema, so the answer cannot disagree with the
    # contract it describes.
    assert body["commands"] == supported_commands()
    assert "block.replace" in body["commands"]
    # A person is not a credential, so there is no grant to describe.
    assert body["grant"] is None


def test_a_credential_learns_the_narrowest_mode_it_holds() -> None:
    """A connector that keeps one mode per connection must not be able to
    escalate by reading this field, so the summary reports the least of them."""
    from datetime import timedelta

    from django.contrib.auth.hashers import make_password
    from django.test import Client
    from django.utils import timezone

    from saas_core.modules.shared.notifications.models import (
        ApiKey,
        ApiKeyCredentialRoute,
    )
    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    client, organization, user = sites_client(slug="handshake-key", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])

    raw = "sc_live_" + "h" * 32
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
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=api_key.id,
        collection_id=collection.data["id"],
        mode="draft_write",
        expires_at=timezone.now() + timedelta(days=7),
        created_by=user,
    )
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=api_key.id,
        site_id=site.data["id"],
        mode="suggest_only",
        created_by=user,
    )

    answered = Client().get(
        "/api/v1/sites/capabilities/", HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    assert answered.status_code == 200
    grant = answered.json()["grant"]
    # Two grants, two modes. The headline is the narrower one; the exact answer
    # per resource is in `scopes`, for a connector that reads it.
    assert grant["mode"] == "suggest_only"
    assert sorted(scope["mode"] for scope in grant["scopes"]) == [
        "draft_write",
        "suggest_only",
    ]


def test_a_credential_hired_for_nothing_is_told_so_plainly() -> None:
    from django.contrib.auth.hashers import make_password
    from django.test import Client

    from saas_core.modules.shared.notifications.models import (
        ApiKey,
        ApiKeyCredentialRoute,
    )

    client, organization, user = sites_client(slug="handshake-bare", role_key="owner")
    create_site(client)

    raw = "sc_live_" + "n" * 32
    api_key = ApiKey.all_objects.create(
        organization=organization,
        name="SeoContentRank",
        prefix=raw[:18],
        secret_hash=make_password(raw),
        scopes=["content:read"],
        created_by=user,
    )
    ApiKeyCredentialRoute.objects.create(
        prefix=raw[:18],
        api_key_id=api_key.id,
        organization_id=organization.id,
        secret_hash=api_key.secret_hash,
        scopes=["content:read"],
    )

    answered = Client().get(
        "/api/v1/sites/capabilities/", HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    # Authenticated and hired for nothing. Saying so at handshake is kinder
    # than letting the connector find out one refusal at a time.
    assert answered.json()["grant"] == {"mode": None, "scopes": []}


def test_a_proposal_diff_is_rebuilt_from_what_is_stored() -> None:
    """An operator deciding should be looking at what a visitor would get, not
    at the sender's description of what it asked for."""
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.change_sets import apply_change_set
    from saas_core.modules.shared.sites.models import Page, PageAutomationPolicy
    from test_sites_api import automation_context
    from test_sites_api import save_draft as save_draft_request

    client, organization, user = sites_client(slug="conn-diff", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="diff-page")
    save_draft_request(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="diff-draft",
        heading="Naglowek sprzed propozycji",
    )
    credential_id = uuid7()
    _grant(organization, user, site.data["id"], credential_id=credential_id)
    Page.all_objects.filter(pk=page.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )

    document = {
        "contract_version": 1,
        "idempotency_key": f"diff-{uuid7()}",
        "target": {
            "kind": "site_page",
            "site_id": str(site.data["id"]),
            "page_id": str(page.data["id"]),
            "locale": "pl",
        },
        "base": {
            "version": 1,
            "snapshot_hash": "sha256:" + "e5" * 32,
            "observed_at": "2026-08-30T09:00:00Z",
        },
        "rationale": {
            "summary": "Zajawka nie odpowiada na intencje frazy.",
            "risk": "low",
            "sources": [
                {
                    "kind": "search_console",
                    "reference": "query=fizjoterapia",
                    "observed_at": "2026-08-29T22:00:00Z",
                }
            ],
        },
        "commands": [
            {
                "command": "block.insert",
                "position": 0,
                "block": {
                    "type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Akapit dopisany przez optymalizator."},
                },
            }
        ],
    }
    context = automation_context(organization.id, user.id, credential_id=credential_id)
    with activate_tenant_context(context):
        apply_change_set(document, context, idempotency_key="diff-apply")

    listed = client.get("/api/v1/sites/proposals/").json()
    proposal_id = next(
        item["proposal_id"]
        for item in listed
        if item["resource_id"] == str(page.data["id"])
    )
    detail = client.get(f"/api/v1/sites/proposals/{proposal_id}/")
    assert detail.status_code == 200
    body = detail.json()

    # One block more after than before: the diff comes from the two stored
    # versions, so it says what a visitor would actually get.
    assert len(body["blocks_after"]) == len(body["blocks_before"]) + 1
    assert body["blocks_after"][0]["data"]["text"] == (
        "Akapit dopisany przez optymalizator."
    )
    assert body["sources"][0]["kind"] == "search_console"
    assert body["risk"] == "low"
