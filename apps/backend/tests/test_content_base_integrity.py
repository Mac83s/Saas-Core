"""A content operation binds the draft, locale and metadata it actually changes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import test_content_preview_authorization as preview_auth
from saas_core.modules.shared.sites.models import Page, PageTranslation, PageVersion
from test_content_operations_api import _apply, _preview
from test_content_preview_authorization import connector, grant_for

surface = preview_auth.surface

pytestmark = pytest.mark.django_db
BASE_URL = "/api/v1/sites/content-base/"


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def translation_for(surface: Any, locale: str = "pl") -> PageTranslation:
    _, organization, _, document = surface
    return PageTranslation.all_objects.create(
        organization=organization,
        site_id=document["target"]["site_id"],
        page_id=document["target"]["page_id"],
        locale=locale,
        slug="oferta",
        title="Original title",
        description="Original description",
    )


def rebase(surface: Any) -> dict[str, Any]:
    person, _, _, document = surface
    result = person.get(BASE_URL, document["target"])
    assert result.status_code == 200, result.content
    document["base"] = result.json()["base"]
    return document


def test_base_hash_stays_stable_between_reads_but_binds_locale_and_metadata(surface: Any) -> None:
    person, _, _, document = surface
    translation = translation_for(surface)
    first = rebase(surface)["base"]
    second = rebase(surface)["base"]
    assert first["snapshot_hash"] == second["snapshot_hash"]
    PageTranslation.all_objects.filter(pk=translation.pk).update(version=2)
    third = rebase(surface)["base"]
    assert third["version"] == first["version"] == 1
    assert third["snapshot_hash"] != first["snapshot_hash"]
    document["target"]["locale"] = "en"
    other = person.get(BASE_URL, document["target"])
    assert other.json()["base"]["snapshot_hash"] != third["snapshot_hash"]
    assert other["Cache-Control"] == "private, no-store"


def test_editing_only_metadata_invalidates_preview_and_apply(surface: Any) -> None:
    translation = translation_for(surface)
    document = rebase(surface)
    PageTranslation.all_objects.filter(pk=translation.pk).update(description="Human edit")
    assert _preview(surface[0], document).status_code == 409
    response = _apply(surface[0], document)
    assert response.status_code == 409
    assert response.json()["code"] == "change_set_stale"
    assert PageVersion.all_objects.filter(page_id=translation.page_id).count() == 1
    translation.refresh_from_db()
    assert translation.description == "Human edit"


def test_metadata_command_changes_real_translation_and_draft_atomically(surface: Any) -> None:
    translation = translation_for(surface)
    document = rebase(surface)
    preview = _preview(surface[0], document).json()
    response = _apply(
        surface[0],
        document,
        approval_digest=preview["approval_digest"],
        approval_token=preview["approval_token"],
    )
    assert response.status_code == 201, response.content
    translation.refresh_from_db()
    assert translation.description == "Proposed copy."
    assert translation.title == "Original title"
    assert translation.slug == "oferta"
    assert translation.version == 2
    assert Page.all_objects.get(pk=translation.page_id).version == 2
    assert response.json()["published"] is False


def test_missing_translation_rolls_back_the_draft_write(surface: Any) -> None:
    document = rebase(surface)
    response = _apply(surface[0], document)
    assert response.status_code == 404
    assert Page.all_objects.get(pk=document["target"]["page_id"]).version == 1
    assert PageVersion.all_objects.filter(page_id=document["target"]["page_id"]).count() == 1


@pytest.mark.parametrize("change", ["expired", "tampered", "missing", "locale"])
def test_approval_requires_signed_live_token_bound_to_locale(surface: Any, change: str) -> None:
    translation_for(surface)
    translation_for(surface, "en")
    document = rebase(surface)
    stamp = timezone.now().timestamp()
    with patch("django.core.signing.time.time", return_value=stamp):
        preview = _preview(surface[0], document).json()
    token = preview["approval_token"]
    if change == "tampered":
        token += "x"
    elif change == "missing":
        token = ""
    elif change == "locale":
        document["target"]["locale"] = "en"
        rebase(surface)
    now = stamp + 86_400 if change == "expired" else stamp
    with patch("django.core.signing.time.time", return_value=now):
        response = _apply(
            surface[0],
            document,
            approval_digest=preview["approval_digest"],
            **({"approval_token": token} if token else {}),
        )
    assert response.status_code == 409, response.content
    assert response.json()["code"] == "approval_digest_mismatch"
    assert Page.all_objects.get(pk=document["target"]["page_id"]).version == 1


@pytest.mark.parametrize(
    "command",
    [
        {"command": "page.create", "key": "new", "name": "New", "page_type": "landing"},
        {"command": "entry.create", "slug": "new", "title": "New"},
        {"command": "internal_link.add", "position": 0, "target_path": "/", "anchor_text": "Home"},
        {"command": "publication.schedule", "publish_at": "2027-01-01T10:00:00Z"},
    ],
)
def test_unexecuted_commands_are_refused_and_not_advertised_as_change_set_support(
    surface: Any,
    command: dict[str, Any],
) -> None:
    document = rebase(surface)
    document["commands"] = [command]
    response = _preview(surface[0], document)
    assert response.status_code == 422
    assert response.json()["code"] == "change_set_command_unsupported"
    assert (
        command["command"]
        not in surface[0].get("/api/v1/sites/capabilities/").json()["change_set_commands"]
    )


@pytest.mark.parametrize("bound", ["none", "revoked", "expired"])
def test_content_base_and_draft_reads_require_active_resource_grant(
    surface: Any, bound: str
) -> None:
    client, key = connector(surface)
    if bound != "none":
        grant_for(
            surface,
            key,
            **{
                "revoked_at" if bound == "revoked" else "expires_at": timezone.now()
                - timedelta(days=1),
            },
        )
    target = surface[3]["target"]
    for path, params in [
        (BASE_URL, target),
        (f"/api/v1/sites/pages/{target['page_id']}/draft/", {}),
    ]:
        with CaptureQueriesContext(connection) as queries:
            response = client.get(path, params)
        assert response.status_code == 403, response.content
        assert not any('FROM "sites_pageblock"' in row["sql"] for row in queries.captured_queries)


def test_content_base_read_grant_precedes_blocks_and_has_no_business_write(surface: Any) -> None:
    client, key = connector(surface)
    grant_for(surface, key)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(BASE_URL, surface[3]["target"])
    assert response.status_code == 200
    sql = [row["sql"] for row in queries.captured_queries]
    grant_index = next(
        i for i, query in enumerate(sql) if 'FROM "sites_contentautomationgrant"' in query
    )
    blocks_index = next(i for i, query in enumerate(sql) if 'FROM "sites_pageblock"' in query)
    assert grant_index < blocks_index
    assert not any(
        query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in sql
    )


def test_reorder_cannot_silently_drop_a_base_block(surface: Any) -> None:
    person, _, _, document = surface

    document = rebase(surface)
    document["commands"] = [{"command": "block.reorder", "order": [0]}]
    response = _preview(person, document)
    assert response.status_code == 422
    assert response.json()["code"] == "change_set_position_invalid"


def test_content_base_service_requires_context_without_queries(surface: Any) -> None:
    from saas_core.modules.core.organizations.authorization import ActiveOrganizationRequired
    from saas_core.modules.shared.sites.change_sets import read_content_base

    with CaptureQueriesContext(connection) as queries, pytest.raises(ActiveOrganizationRequired):
        read_content_base(surface[3]["target"])
    assert queries.captured_queries == []


@pytest.mark.parametrize("refusal", ["permission", "entitlement", "suspended", "foreign"])
def test_content_base_authorization_matrix(surface: Any, refusal: str) -> None:
    from saas_core.modules.core.organizations.models import Membership, OrganizationStatus, Role
    from saas_core.modules.shared.billing.models import EntitlementSnapshot
    from test_sites_api import create_page, create_site, sites_client

    person, organization, owner, document = surface
    target = document["target"].copy()
    expected_status = 403
    if refusal == "permission":
        Membership.objects.filter(organization=organization, user=owner).update(
            role=Role.objects.get(key="viewer", organization=None, organization_type=""),
        )
    elif refusal == "entitlement":
        EntitlementSnapshot.all_objects.filter(organization=organization).update(
            features={"sites.enabled": False},
        )
    elif refusal == "suspended":
        organization.status = OrganizationStatus.SUSPENDED
        organization.save(update_fields=["status"])
        expected_status = 409
    else:
        foreign, _, _ = sites_client(slug="base-foreign", role_key="owner")
        site = create_site(foreign).data["id"]
        page = create_page(foreign, site, idempotency_key="base-foreign-page").data["id"]
        target.update(site_id=str(site), page_id=str(page))
        expected_status = 404
    with CaptureQueriesContext(connection) as queries:
        response = person.get(BASE_URL, target)
    assert response.status_code == expected_status, response.content
    assert not any('FROM "sites_pageblock"' in row["sql"] for row in queries.captured_queries)
