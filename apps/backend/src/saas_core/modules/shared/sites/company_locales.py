"""What the sites module says about the company's languages (ADR-071 pkt 6)."""

from __future__ import annotations

from uuid import UUID

from .models import Site

SITE_DEFAULT_NOT_REMOVABLE = "site_default_not_removable"


def site_source_locales(organization_id: UUID, removed: frozenset[str]) -> dict[str, str]:
    """A site's source language answers without a prefix and its versions
    depend on it, so it stays on the company's list for as long as the site."""
    return {
        code: SITE_DEFAULT_NOT_REMOVABLE
        for code in Site.all_objects.filter(
            organization_id=organization_id, default_locale__in=removed
        ).values_list("default_locale", flat=True)
    }
