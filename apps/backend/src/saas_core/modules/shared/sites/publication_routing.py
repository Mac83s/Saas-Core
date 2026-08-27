from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.models import OrganizationStatus

from .domains import InvalidHostname, normalize_hostname
from .models import (
    ContentEntry,
    ContentEntryState,
    Domain,
    DomainStatus,
    Publication,
)

DEFAULT_PUBLIC_DESIGN_TOKENS = {
    "schemaVersion": 1,
    "palette": "neutral",
    "typography": "sans",
    "radius": "medium",
    "spacing": "comfortable",
}


class PublicSiteNotFound(NotFound):
    default_detail = "Opublikowana strona nie istnieje dla tego hosta i ścieżki."
    default_code = "public_site_not_found"


@dataclass(frozen=True, slots=True)
class PublicPage:
    hostname: str
    canonical_hostname: str
    requested_path: str
    canonical_path: str
    locale: str
    publication: Publication
    page: dict[str, Any]

    @property
    def redirect_url(self) -> str | None:
        # Compared the same way the page was matched. A raw `==` treats
        # "/start" and "/start/" as different addresses and redirects the
        # visitor to the page they already asked for, forever.
        already_canonical = _comparable_path(self.requested_path) == _comparable_path(
            self.canonical_path
        )
        if self.hostname == self.canonical_hostname and already_canonical:
            return None
        return f"{settings.PUBLIC_SITE_SCHEME}://{self.canonical_hostname}{self.canonical_path}"


def resolve_public_page(*, host: str, path: str) -> PublicPage:
    try:
        hostname = normalize_hostname(host, allow_port=True)
    except InvalidHostname as error:
        raise PublicSiteNotFound from error
    normalized_path = _normalize_path(path)
    # A published entry is reachable even when the site itself has no
    # publication yet: entries publish independently, so requiring a site
    # snapshot would make the blog depend on something unrelated to it.
    domain = (
        Domain.all_objects.select_related("site__current_publication", "organization")
        .filter(
            hostname=hostname,
            status=DomainStatus.VERIFIED,
            organization__status=OrganizationStatus.ACTIVE,
        )
        .first()
    )
    if domain is None:
        raise PublicSiteNotFound
    canonical = Domain.all_objects.filter(
        site_id=domain.site_id,
        status=DomainStatus.VERIFIED,
        is_canonical=True,
    ).first()
    if canonical is None:
        raise PublicSiteNotFound
    publication: Any = domain.site.current_publication
    try:
        if publication is None:
            raise PublicSiteNotFound
        page, locale_document = _find_page(publication.snapshot, normalized_path)
    except PublicSiteNotFound:
        # Not a page, so it may be a collection entry. Entries publish on their
        # own (ADR-035 §1) and are therefore absent from the site snapshot; the
        # entry's own publication then stands in for the site's.
        page, locale_document, publication = _find_entry(
            organization_id=domain.organization_id,
            site_id=domain.site_id,
            requested_path=normalized_path,
        )
    canonical_path = str(locale_document["canonical_path"])
    return PublicPage(
        hostname=hostname,
        canonical_hostname=canonical.hostname,
        requested_path=normalized_path,
        canonical_path=canonical_path,
        locale=str(locale_document["locale"]),
        publication=publication,
        page={**page, "selected_locale": locale_document},
    )


def public_page_payload(page: PublicPage) -> dict[str, Any]:
    selected_locale = page.page["selected_locale"]
    publication_snapshot = page.publication.snapshot
    canonical_origin = f"{settings.PUBLIC_SITE_SCHEME}://{page.canonical_hostname}"
    hreflang = {
        locale: f"{canonical_origin}{path}"
        for locale, path in page.page.get("hreflang", {}).items()
    }
    return {
        "publication_id": str(page.publication.id),
        "snapshot_hash": page.publication.snapshot_hash,
        "locale": page.locale,
        "canonical_url": f"{canonical_origin}{page.canonical_path}",
        "hreflang": hreflang,
        "x_default": f"{canonical_origin}{page.page['x_default']}",
        "title": selected_locale["title"],
        "description": selected_locale["description"],
        "social_title": selected_locale["social_title"],
        "social_description": selected_locale["social_description"],
        # An entry's snapshot carries no theme of its own; it inherits the
        # site's, and falls back to the default when the site has never been
        # published.
        "design_tokens": publication_snapshot.get(
            "design_tokens", DEFAULT_PUBLIC_DESIGN_TOKENS
        ),
        "blocks": page.page["blocks"],
        "navigation": _navigation_links(publication_snapshot, page.locale),
    }


def _navigation_links(snapshot: dict[str, Any], locale: str) -> list[dict[str, Any]]:
    """Menu entries resolved for one locale, in publication order.

    The visible text is the page's own translated title, so it cannot drift
    from the page. An entry whose page has no translation in this locale is skipped:
    linking to it would send the visitor to an address that does not exist in
    the language they are reading."""
    pages_by_id = {
        str(raw_page.get("page_id")): raw_page
        for raw_page in snapshot.get("pages", [])
        if isinstance(raw_page, dict)
    }
    links: list[dict[str, Any]] = []
    for entry in snapshot.get("navigation", []):
        if not isinstance(entry, dict):
            continue
        raw_page = pages_by_id.get(str(entry.get("page_id")))
        if raw_page is None:
            continue
        localized = next(
            (
                candidate
                for candidate in raw_page.get("locales", [])
                if isinstance(candidate, dict) and candidate.get("locale") == locale
            ),
            None,
        )
        if localized is None:
            continue
        links.append({
            "page_id": str(entry.get("page_id")),
            "parent_page_id": entry.get("parent_page_id"),
            "title": localized["title"],
            "path": localized["path"],
        })
    return links


def _find_entry(
    *,
    organization_id: Any,
    site_id: Any,
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Resolves a published blog entry and shapes it like a page.

    Returning the page shape keeps one payload builder and one renderer for both
    surfaces — the reader should not be able to tell that an article is stored
    differently from a page.
    """
    wanted = _comparable_path(requested_path)
    entries = ContentEntry.all_objects.select_related("current_publication").filter(
        organization_id=organization_id,
        site_id=site_id,
        state=ContentEntryState.PUBLISHED,
        current_publication__isnull=False,
    )
    for entry in entries:
        publication = entry.current_publication
        if publication is None:
            continue
        snapshot = publication.snapshot
        if _comparable_path(str(snapshot.get("path", ""))) != wanted:
            continue
        locale_document = {
            "locale": snapshot["locale"],
            "translation_id": None,
            "version": snapshot.get("version", 1),
            "slug": snapshot["slug"],
            "path": snapshot["path"],
            "canonical_path": snapshot["path"],
            "title": snapshot["title"],
            "description": snapshot.get("excerpt", ""),
            "social_title": snapshot["title"],
            "social_description": snapshot.get("excerpt", ""),
            "fallback_fields": [],
        }
        return (
            {
                "page_id": snapshot["entry_id"],
                "key": snapshot["slug"],
                "blocks": snapshot["blocks"],
                "media_asset_ids": [],
                "locales": [locale_document],
                # A single-language article has no alternates to advertise;
                # claiming otherwise would point search engines at nothing.
                "hreflang": {snapshot["locale"]: snapshot["path"]},
                "x_default": snapshot["path"],
                "noindex": bool(snapshot.get("noindex", False)),
            },
            locale_document,
            publication,
        )
    raise PublicSiteNotFound


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValidationError({"path": ["Ścieżka musi zaczynać się od /. "]})
    if "\\" in value or "\x00" in value or "?" in value or "#" in value or "//" in value:
        raise ValidationError({"path": ["Ścieżka zawiera niedozwolone znaki."]})
    if len(value) > 2048:
        raise ValidationError({"path": ["Ścieżka jest za długa."]})
    return value


def _comparable_path(value: str) -> str:
    """One spelling for `/start`, `/start/` and `//start//`, so a visitor's URL
    and the snapshot's stored path compare equal whichever way either ends."""
    return value.rstrip("/") or "/"


def _find_page(
    snapshot: dict[str, Any],
    requested_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wanted = _comparable_path(requested_path)
    for raw_page in snapshot.get("pages", []):
        if not isinstance(raw_page, dict):
            continue
        for raw_locale in raw_page.get("locales", []):
            if not isinstance(raw_locale, dict):
                continue
            # The snapshot stores trailing-slash paths ("/start/"), so the
            # stored value needs the same treatment as the request. Comparing a
            # trimmed request against an untrimmed candidate never matched, and
            # every page except the home page answered 404.
            if _comparable_path(str(raw_locale.get("path", ""))) == wanted:
                return raw_page, raw_locale
    raise PublicSiteNotFound
