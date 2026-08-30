"""What a subscriber is told, and what never leaves the tenant (W9.6.7).

The webhook machinery itself is ADR-029's and already tested; these are about
the sites side of the seam: which events exist, that each one can actually be
delivered, and that a draft's text is not among the things that travel.
"""

from __future__ import annotations

from uuid import uuid7

import pytest
from django.core.cache import cache

from saas_core.modules.shared.sites.models import SiteOutboxEvent
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_draft,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def _events(event_type: str) -> list[SiteOutboxEvent]:
    return list(SiteOutboxEvent.all_objects.filter(event_type=event_type))


def test_every_registered_event_type_has_a_payload_allowlist() -> None:
    """The two halves are edited in different files and neither fails loudly.

    An event type nobody registered is delivered nowhere at all; a registered
    one with no allowlist stops its own delivery. Both look like "the webhook
    just did not arrive", which is the hardest thing to debug from the far end.
    """
    from saas_core.modules.core.organizations.events import _handlers
    from saas_core.modules.shared.notifications.services import (
        _allowlisted_event_payload,
    )

    registered = {
        event_type
        for event_type, _version in _handlers
        if event_type.startswith("sites.")
    }
    assert registered, "no sites events are registered at all"
    for event_type in sorted(registered):
        # Raises when the type has no allowlist, which is exactly the failure
        # this test exists to catch before a deploy does.
        _allowlisted_event_payload(event_type, {})


def test_a_rollback_says_it_is_a_rollback() -> None:
    """It is a publication in mechanism and the opposite of one in meaning.

    Sent as `sites.site.published`, a subscriber could not tell that the change
    it made an hour ago had just been undone.
    """
    client, _, _ = sites_client(slug="events-rollback", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="ev-page")
    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="ev-draft",
        heading="Pierwsza",
    )
    save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug="start",
        title="Start",
        description="Opis strony startowej.",
        idempotency_key="ev-pl",
    )
    first = publish_site_request(client, site.data["id"], idempotency_key="ev-pub-1")
    assert first.status_code == 201
    save_draft(
        client,
        page.data["id"],
        expected_version=1,
        idempotency_key="ev-draft-2",
        heading="Druga",
    )
    publish_site_request(client, site.data["id"], idempotency_key="ev-pub-2")

    rollback = client.post(
        f"/api/v1/sites/{site.data['id']}/publications/{first.data['id']}/rollback/",
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="ev-rollback",
    )
    assert rollback.status_code == 201

    rolled_back = _events("sites.site.rolled_back")
    assert len(rolled_back) == 1
    # And it names the publication it went back to, which is the whole reason
    # a subscriber cares.
    assert rolled_back[0].payload["source_publication_id"] == str(first.data["id"])
    assert len(_events("sites.site.published")) == 2


def test_a_draft_written_by_an_automation_is_news_and_a_persons_own_save_is_not() -> None:
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.services import save_draft as save_draft_service
    from test_sites_api import automation_context, grant_for_site

    client, organization, user = sites_client(slug="events-draft", role_key="owner")
    site = create_site(client)
    page = create_page(client, site.data["id"], idempotency_key="ev-d-page")

    save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key="ev-d-human",
        heading="Napisane ręcznie",
    )
    # An operator does not need to be told about their own save, and an
    # operator's queue is meant to show what arrived while they were away.
    assert _events("sites.page.draft_saved") == []

    from saas_core.modules.shared.sites.models import Page, PageAutomationPolicy

    Page.all_objects.filter(pk=page.data["id"]).update(
        automation_policy=PageAutomationPolicy.AUTOMATED
    )
    credential_id = grant_for_site(organization, user, site.data["id"])
    with activate_tenant_context(
        automation_context(organization.id, user.id, credential_id=credential_id)
    ):
        save_draft_service(
            page_id=page.data["id"],
            expected_version=1,
            blocks=[
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Tekst propozycji, który nigdzie nie wyjeżdża."},
                }
            ],
            media_asset_ids=[],
            idempotency_key="ev-d-automation",
        )

    proposals = _events("sites.page.draft_saved")
    assert len(proposals) == 1
    assert proposals[0].payload["resource_id"] == str(page.data["id"])
    assert proposals[0].payload["credential_id"] == str(credential_id)


def test_a_draft_event_carries_no_draft_text_to_a_subscriber() -> None:
    """A customer's unpublished work is the last thing that should leave over
    an outbound HTTP request nobody is watching."""
    from saas_core.modules.shared.notifications.services import (
        _allowlisted_event_payload,
    )

    delivered = _allowlisted_event_payload(
        "sites.page.draft_saved",
        {
            "resource_type": "site_page",
            "resource_id": str(uuid7()),
            "version": 3,
            "credential_id": str(uuid7()),
            "blocks": [{"data": {"text": "Tajna treść klienta."}}],
        },
    )
    assert "blocks" not in delivered
    assert set(delivered) == {
        "credential_id",
        "resource_id",
        "resource_type",
        "version",
    }


def test_revoking_a_grant_stops_the_credential_and_tells_the_subscriber() -> None:
    """Emergency revoke: the connector learns it has been cut off rather than
    discovering it one 403 at a time."""
    from datetime import timedelta

    from django.utils import timezone

    from saas_core.modules.core.organizations.context import (
        activate_tenant_context,
        context_from_membership,
    )
    from saas_core.modules.core.organizations.models import Membership
    from saas_core.modules.shared.sites.models import ContentAutomationGrant
    from saas_core.modules.shared.sites.services import (
        AutomationGrantMissing,
        assert_within_grant,
        revoke_automation_grant,
    )
    from test_sites_api import automation_context

    client, organization, user = sites_client(slug="events-revoke", role_key="owner")
    site = create_site(client)
    credential_id = uuid7()
    grant = ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=credential_id,
        site_id=site.data["id"],
        mode="draft_write",
        expires_at=timezone.now() + timedelta(days=7),
        created_by=user,
    )

    membership = Membership.objects.select_related("organization", "role").get(
        organization_id=organization.id, user_id=user.id
    )
    with activate_tenant_context(context_from_membership(membership)):
        revoke_automation_grant(grant_id=grant.id, reason="Podejrzana aktywność.")

    grant.refresh_from_db()
    assert grant.revoked_at is not None
    # The row survives the incident that caused it, for the audit trail.
    assert ContentAutomationGrant.all_objects.filter(pk=grant.id).exists()

    automation = automation_context(
        organization.id, user.id, credential_id=credential_id
    )
    with activate_tenant_context(automation), pytest.raises(AutomationGrantMissing):
        assert_within_grant(automation, site_id=site.data["id"])

    revoked = _events("sites.automation_grant.revoked")
    assert len(revoked) == 1
    assert revoked[0].payload["credential_id"] == str(credential_id)
