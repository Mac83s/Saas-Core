"""Erasing an organization that used the site studio (ADR-042): its own
templates and a rolled-back publication go with it."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from saas_core.modules.core.organizations.erasure import erase_organization
from saas_core.modules.shared.sites.models import Publication, SiteTemplateVersion
from test_site_own_templates import FAQ, HERO, create, post
from test_sites_api import (
    create_page,
    create_site,
    publish_site_request,
    rollback_site_request,
    save_draft,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


def test_an_organization_with_a_rollback_and_own_templates_can_be_erased() -> None:
    client, organization, _ = sites_client(slug="sites-erasure", role_key="owner")
    site_id = create_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]
    save_draft(client, page_id, expected_version=0, idempotency_key="d1", heading="Pierwsza")
    save_translation(
        client,
        page_id,
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Opis",
        idempotency_key="t1",
    )
    first = publish_site_request(client, site_id, idempotency_key="p1")
    save_draft(client, page_id, expected_version=1, idempotency_key="d2", heading="Druga")
    second = publish_site_request(client, site_id, idempotency_key="p2")
    rollback = rollback_site_request(client, site_id, first.data["id"], idempotency_key="r1")
    # A rollback of the rollback: a chain, not only a pair.
    again = rollback_site_request(client, site_id, second.data["id"], idempotency_key="r2")
    chained = rollback_site_request(client, site_id, rollback.data["id"], idempotency_key="r3")
    assert {first.status_code, second.status_code} == {201}
    assert {rollback.status_code, again.status_code, chained.status_code} == {201}
    template = create(client, kind="page", name="Strona firmowa", blocks=[HERO]).data
    post(
        client,
        f"/api/v1/sites/templates/{template['id']}/versions/",
        {"expected_version": 1, "blocks": [HERO, FAQ]},
        "v2",
    )

    receipt = erase_organization(
        organization=organization, requested_by=None, reason="Synthetic test"
    )

    assert receipt.row_counts["sites.Publication"] == 5
    assert receipt.row_counts["sites.SiteTemplateVersion"] == 2
    assert not Publication.all_objects.filter(organization_id=organization.id).exists()
    assert not SiteTemplateVersion.all_objects.filter(organization_id=organization.id).exists()
