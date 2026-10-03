"""Where search engines and language models read the company's sites (TL19).

One read for the panel's „Widoczność w wyszukiwarkach i AI”: per site its
sitemap and `robots.txt`, and per language the site answers in now its home
and its `llms.txt`. The addresses come from the same rules the public routes
answer by (`public_feeds.search_addresses`), so nothing listed here gives 404.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .models import Domain, DomainStatus, Site
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .public_feeds import search_addresses


def _native_name(code: str) -> str:
    entry = settings.LOCALE_REGISTRY.get(code)
    return entry.native_name if entry is not None else code


def read_search_visibility() -> dict[str, Any]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    organization = Organization.objects.only("id", "public_locales").get(pk=context.organization_id)
    languages = tuple(organization_content_locales(organization))
    canonical = dict(
        Domain.all_objects.filter(
            organization_id=context.organization_id,
            status=DomainStatus.VERIFIED,
            is_canonical=True,
        ).values_list("site_id", "hostname")
    )
    sites = []
    for site in (
        Site.all_objects.select_related("current_publication")
        .filter(organization_id=context.organization_id)
        .order_by("created_at", "id")
    ):
        hostname = canonical.get(site.id)
        origin = f"{settings.PUBLIC_SITE_SCHEME}://{hostname}" if hostname else None
        addresses = (
            search_addresses(site=site, origin=origin, languages=languages)
            if origin
            else {"sitemap_url": None, "robots_url": None, "languages": []}
        )
        sites.append({
            "site_id": site.id,
            "name": site.name,
            "origin": origin if site.current_publication_id else None,
            "sitemap_url": addresses["sitemap_url"],
            "robots_url": addresses["robots_url"],
            "languages": [
                {**language, "name": _native_name(language["locale"])}
                for language in addresses["languages"]
            ],
        })
    return {"sites": sites}
