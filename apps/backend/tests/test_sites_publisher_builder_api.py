"""The site builder's operations stay open to the platform's own workspace.

ADR-079 pkt 29 (the paragraph added with package PW1): no host serves the
workspace's builder site and its panel has no screen for one — but the API
behind those screens is left as it is. Closing it would put a check of the
workspace's kind into every operation on pages, the menu, the site's
publication and its domains, to stop something nobody can see anyway, and it
would strand the rows a workspace already has.

This pins the decision from both sides: the operations answer a platform
workspace exactly as they answer a company, and what they make is still
served at no host. Whoever closes them, or makes the site answer, changes it
here — and in the ADR.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import Membership, Organization, WorkspaceKind
from saas_core.modules.core.organizations.platform_workspace import platform_workspace_slug
from saas_core.modules.shared.sites.domain_services import list_domains
from saas_core.modules.shared.sites.models import Page, Site
from saas_core.modules.shared.sites.services import (
    create_page,
    list_pages,
    list_site_publications,
    publish_site,
)
from test_site_language_publication import _site

pytestmark = pytest.mark.django_db


def _served(host: str) -> int:
    with override_settings(PUBLIC_SITE_SCHEME="https"):
        return int(
            APIClient().get("/api/v1/public/site/", {"path": "/"}, HTTP_HOST=host).status_code
        )


def test_the_builders_operations_answer_the_platforms_workspace_and_stay_unserved() -> None:
    # Two pages ready to go out, made while this was still a company:
    # entering the platform's workspace over HTTP takes an operator's second
    # factor, so what follows calls the operations the endpoints call.
    _client, made_site, home, offer, host = _site("builder-open")
    site_id = UUID(str(made_site))
    assert _served(host) == 404  # nothing published yet

    organization = Organization.objects.get(slug="builder-open")
    Organization.objects.filter(pk=organization.pk).update(
        workspace_kind=WorkspaceKind.PLATFORM, slug=platform_workspace_slug()
    )
    membership = Membership.objects.get(organization=organization)

    with activate_tenant_context(context_from_membership(membership)):
        # Pages are listed.
        listed, _cursor = list_pages(site_id=site_id, cursor=None, limit=10)
        assert {str(page.id) for page in listed} == {home, offer}
        # The site's own publication, and its history.
        published = publish_site(site_id=site_id, idempotency_key="out")
        publication = published.publication
        assert published.created
        assert Site.all_objects.get(pk=site_id).current_publication_id == publication.id
        history, _older = list_site_publications(site_id=site_id, cursor=None, limit=10)
        assert [item.id for item in history] == [publication.id]
        # A new page is made.
        made = create_page(site_id=site_id, name="Kontakt", key="kontakt", idempotency_key="third")
        assert made.created and made.value.key == "kontakt"
        # Its addresses.
        assert [domain.hostname for domain in list_domains(site_id=site_id)] == [host]

    assert Page.all_objects.filter(site_id=site_id, deleted_at__isnull=True).count() == 3
    # Published — and served at no host, as before the publication.
    assert _served(host) == 404
    # The same rows are a company's site the moment the workspace is one.
    Organization.objects.filter(pk=organization.pk).update(
        workspace_kind=WorkspaceKind.BUSINESS, slug="builder-open"
    )
    assert _served(host) == 200
