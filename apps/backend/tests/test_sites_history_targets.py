"""The company's history says which site, page and file a row is about
(UX-055): „Zapisano szkic podstrony: Oferta”, not twenty identical rows."""

from __future__ import annotations

import pytest

from saas_core.modules.core.organizations.audit import record_audit
from test_sites_api import (
    create_media_asset,
    create_page,
    create_site,
    publish_site_request,
    save_draft,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db

HISTORY_URL = "/api/v1/organizations/current/history/"


def test_the_history_names_the_site_the_page_its_language_and_the_file() -> None:
    client, organization, user = sites_client(slug="historia-strony", role_key="owner")
    site = create_site(client).data
    page = create_page(client, site["id"]).data
    draft = save_draft(
        client, page["id"], expected_version=0, idempotency_key="draft", heading="Oferta"
    )
    assert draft.status_code == 201, draft.data
    translation = save_translation(
        client,
        page["id"],
        "pl",
        expected_version=0,
        slug="home",
        title="Home",
        description="Hello",
        idempotency_key="translation",
    )
    assert translation.status_code == 201, translation.data
    published = publish_site_request(client, site["id"], idempotency_key="publish")
    assert published.status_code == 201, published.data
    asset = create_media_asset(organization, user)
    record_audit(
        organization=organization,
        action="media.asset.ready",
        actor=user,
        target_type="media_asset",
        target_id=asset.id,
    )

    named = {item["action"]: item["target"] for item in client.get(HISTORY_URL).data["items"]}

    the_site = {"label": "Main Site", "href": f"/panel/sites?site={site['id']}", "at": None}
    the_page = {"label": "Home", "href": f"/panel/sites/pages/{page['id']}", "at": None}
    assert named["sites.site.created"] == the_site
    assert named["sites.site.published"] == the_site
    assert named["sites.page.created"] == the_page
    assert named["sites.page.draft_saved"] == the_page
    assert named["sites.page.translation_saved"] == {**the_page, "label": "Home (PL)"}
    assert named["media.asset.ready"] == {"label": "reference.jpg", "href": "", "at": None}
