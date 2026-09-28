"""An organization's own templates (F4-B): saved with their content, for the
whole organization, versioned, and never changing a page built from them."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.billing.models import EntitlementSnapshot, QuotaDefinition
from saas_core.modules.shared.sites.models import PageVersion, SiteTemplateVersion
from test_sites_api import create_page, create_site, csrf_value, sites_client

pytestmark = pytest.mark.django_db

TEMPLATES_URL = "/api/v1/sites/templates/"
HERO = {"block_type": "core.hero", "schema_version": 6, "data": {"title": "Nasza oferta"}}
FAQ = {
    "block_type": "core.faq",
    "schema_version": 3,
    "data": {"items": [{"question": "Jak zacząć?", "answer": "Napisz do nas."}]},
}


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def post(client: APIClient, url: str, body: dict[str, Any], key: str = "k") -> Any:
    return client.post(
        url,
        body,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def create(client: APIClient, key: str = "t1", **overrides: Any) -> Any:
    body = {"kind": "section", "name": "Oferta firmowa", "blocks": [HERO], **overrides}
    return post(client, TEMPLATES_URL, body, key)


def test_a_section_template_is_saved_with_its_content_once_per_request() -> None:
    client, organization, user = sites_client(slug="own-templates-create")
    created = create(client)
    replay = create(client)
    changed = create(client, name="Inna nazwa")
    same_name = create(client, key="t2")
    two_blocks = create(client, key="t3", name="Dwie", blocks=[HERO, FAQ])
    page_look_on_a_section = create(
        client,
        key="t4",
        name="Z wyglądem",
        page_presentation={"schemaVersion": 2, "style": "premium"},
    )

    assert created.status_code == 201, created.data
    assert created.data["kind"] == "section"
    assert created.data["version"]["number"] == 1
    assert created.data["version"]["blocks"][0]["data"] == {"title": "Nasza oferta"}
    assert created.data["created_by"]["email"] == user.email
    assert replay.status_code == 200
    assert replay.data["id"] == created.data["id"]
    assert changed.status_code == 409
    assert changed.data["code"] == "sites_idempotency_conflict"
    assert same_name.status_code == 409
    assert same_name.data["code"] == "site_template_name_taken"
    assert two_blocks.status_code == 400
    assert two_blocks.data["code"] == "site_template_invalid"
    assert page_look_on_a_section.status_code == 400
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=organization, action="sites.template.created"
        ).count()
        == 1
    )

    listed = client.get(TEMPLATES_URL, {"kind": "section"})
    assert listed.status_code == 200
    assert [item["name"] for item in listed.data["items"]] == ["Oferta firmowa"]
    assert listed.data["limit"] is None


def test_editing_saves_the_next_version_and_older_ones_stay() -> None:
    client, organization, _ = sites_client(slug="own-templates-versions")
    template_id = create(client, kind="page", name="Strona usługi", blocks=[HERO]).data["id"]
    url = f"{TEMPLATES_URL}{template_id}/versions/"
    second = post(client, url, {"expected_version": 1, "blocks": [HERO, FAQ]}, "v2")
    stale = post(client, url, {"expected_version": 1, "blocks": [FAQ]}, "v2-stale")

    assert second.status_code == 201
    assert second.data["version"]["number"] == 2
    assert len(second.data["version"]["blocks"]) == 2
    assert stale.status_code == 409
    assert stale.data["code"] == "site_template_version_conflict"
    versions = SiteTemplateVersion.all_objects.filter(organization=organization).order_by(
        "number"
    )
    assert [len(version.blocks) for version in versions] == [1, 2]
    # Versions are append-only in the database as well.
    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_organization_id(organization.id)
        SiteTemplateVersion.all_objects.filter(pk=versions[0].pk).update(blocks=[])

    renamed = client.patch(
        f"{TEMPLATES_URL}{template_id}/",
        {"name": "Usługa — wersja firmowa", "description": "Do nowych usług"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert renamed.status_code == 200
    assert renamed.data["name"] == "Usługa — wersja firmowa"
    assert renamed.data["version"]["number"] == 2


def test_a_page_template_becomes_the_pages_next_draft_and_later_versions_leave_it() -> None:
    client, _, _ = sites_client(slug="own-templates-import")
    page_id = create_page(client, create_site(client).data["id"]).data["id"]
    template = create(
        client,
        kind="page",
        name="Strona firmowa",
        blocks=[HERO, FAQ],
        page_presentation={"schemaVersion": 2, "style": "expert"},
    ).data
    imported = post(
        client,
        f"/api/v1/sites/pages/{page_id}/own-template-import/",
        {"expected_version": 0, "template_id": template["id"], "template_version": 1},
        "import-1",
    )
    assert imported.status_code == 201
    assert [block["block_type"] for block in imported.data["blocks"]] == [
        "core.hero",
        "core.faq",
    ]
    assert imported.data["page_presentation"] == {"schemaVersion": 2, "style": "expert"}
    version = PageVersion.all_objects.get(pk=imported.data["draft_id"])
    assert (version.origin, version.origin_ref) == ("own_template", "Strona firmowa@1")

    # A new template version does not reach the page built from the first.
    post(
        client,
        f"{TEMPLATES_URL}{template['id']}/versions/",
        {"expected_version": 1, "blocks": [FAQ]},
        "v2",
    )
    draft = client.get(f"/api/v1/sites/pages/{page_id}/draft/")
    assert len(draft.data["blocks"]) == 2

    section = create(client, key="s1", name="Sama sekcja").data
    not_a_page = post(
        client,
        f"/api/v1/sites/pages/{page_id}/own-template-import/",
        {"expected_version": 1, "template_id": section["id"], "template_version": 1},
        "import-2",
    )
    assert not_a_page.status_code == 404
    assert not_a_page.data["code"] == "site_template_not_found"


def test_archiving_takes_a_template_out_of_the_library_and_frees_the_plans_place() -> None:
    client, organization, _ = sites_client(slug="own-templates-limit")
    QuotaDefinition.objects.update_or_create(
        key="sites.templates.max",
        defaults={"name": "Szablony firmy", "unit": "count", "period": "lifetime"},
    )
    with transaction.atomic():
        set_local_organization_id(organization.id)
        snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
        snapshot.quotas = {**snapshot.quotas, "sites.templates.max": 1}
        snapshot.sources = {**snapshot.sources, "sites.templates.max": {"kind": "plan"}}
        snapshot.save(update_fields=["quotas", "sources"])
    first = create(client)
    second = create(client, key="t2", name="Druga")
    assert first.status_code == 201
    assert second.status_code == 403
    assert second.data["code"] == "site_template_limit_reached"
    assert client.get(TEMPLATES_URL).data["limit"] == 1

    archived = client.post(
        f"{TEMPLATES_URL}{first.data['id']}/archive/",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert archived.status_code == 204
    assert client.get(TEMPLATES_URL).data["items"] == []
    assert create(client, key="t3", name="Druga").status_code == 201


def test_templates_belong_to_their_organization_and_need_a_person_with_csrf() -> None:
    client, _, _ = sites_client(slug="own-templates-owner")
    foreign, _, _ = sites_client(slug="own-templates-foreign")
    template_id = create(client).data["id"]

    assert foreign.get(TEMPLATES_URL).data["items"] == []
    assert (
        post(
            foreign,
            f"{TEMPLATES_URL}{template_id}/versions/",
            {"expected_version": 1, "blocks": [HERO]},
        ).status_code
        == 404
    )
    assert (
        foreign.post(
            f"{TEMPLATES_URL}{template_id}/archive/", HTTP_X_CSRFTOKEN=csrf_value(foreign)
        ).status_code
        == 404
    )
    no_csrf = client.post(
        TEMPLATES_URL,
        {"kind": "section", "name": "Bez tokenu", "blocks": [HERO]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="x",
    )
    assert no_csrf.status_code == 403
