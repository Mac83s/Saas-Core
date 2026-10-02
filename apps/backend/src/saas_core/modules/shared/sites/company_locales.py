"""What the sites module says about the company's languages (ADR-071 pkt 6, 9)."""

from __future__ import annotations

from uuid import UUID

from django.db.models import F

from saas_core.modules.core.organizations.api import LocaleRedirect

from .models import ContentCollection, PageTranslation, Site
from .publication_routing import published_entries, visible_snapshot

SITE_DEFAULT_NOT_REMOVABLE = "site_default_not_removable"
LOCALE_PATH_CONFLICT = "locale_path_conflict"


def site_locale_problems(
    organization_id: UUID, added: frozenset[str], removed: frozenset[str]
) -> dict[str, str]:
    """A site's source language answers without a prefix and its versions
    depend on it, so it stays on the company's list for as long as the site. A
    language whose `/xx/` prefix is already a page's or a blog's address in the
    source language cannot be added: one of them would stop answering. New
    addresses cannot take a two-letter segment (`slug_reserved`), so this only
    finds ones older than that rule."""
    problems = {
        code: SITE_DEFAULT_NOT_REMOVABLE
        for code in Site.all_objects.filter(
            organization_id=organization_id, default_locale__in=removed
        ).values_list("default_locale", flat=True)
    }
    if added:
        taken = set(
            PageTranslation.all_objects.filter(
                organization_id=organization_id,
                locale=F("page__site__default_locale"),
                slug__in=added,
                page__deleted_at__isnull=True,
            ).values_list("slug", flat=True)
        ) | set(
            ContentCollection.all_objects.filter(
                organization_id=organization_id, base_path__in=added
            ).values_list("base_path", flat=True)
        )
        problems.update({code: LOCALE_PATH_CONFLICT for code in taken})
    return problems


def removed_locale_redirects(
    organization_id: UUID, removed: frozenset[str]
) -> list[LocaleRedirect]:
    """The public addresses in the removed languages and where each leads from
    the moment the change is saved: the same page in the site's language, or —
    for an article with no version in it — nowhere."""
    redirects: list[LocaleRedirect] = []
    for site in Site.all_objects.select_related("current_publication").filter(
        organization_id=organization_id, current_publication__isnull=False
    ):
        assert site.current_publication is not None
        for page in visible_snapshot(site.current_publication)["pages"]:
            source = next(
                (item for item in page["locales"] if item.get("locale") == site.default_locale),
                None,
            )
            for item in page["locales"]:
                if item.get("locale") in removed and item.get("path"):
                    redirects.append(
                        LocaleRedirect(
                            locale=str(item["locale"]),
                            path=str(item["path"]),
                            target=str(source["path"]) if source else "",
                        )
                    )
        entries = published_entries(organization_id=organization_id, site_id=site.id)
        by_group = {
            item["translation_group"]: item["path"]
            for item in entries
            if item["locale"] == site.default_locale
        }
        redirects.extend(
            LocaleRedirect(
                locale=item["locale"],
                path=item["path"],
                target=by_group.get(item["translation_group"], ""),
            )
            for item in entries
            if item["locale"] in removed
        )
    return sorted(redirects, key=lambda redirect: (redirect.locale, redirect.path))
