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
