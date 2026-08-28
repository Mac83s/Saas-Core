from __future__ import annotations

from datetime import UTC
from typing import Any
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse

from saas_core.modules.core.organizations.models import OrganizationStatus

from .domains import InvalidHostname, normalize_hostname
from .models import ContentCollection, Domain, DomainStatus
from .publication_routing import PublicSiteNotFound, published_entries


def _resolve_site(host: str) -> tuple[Any, str]:
    """The site behind a visitor's host, plus the address it calls its own.

    Every URL a feed or a sitemap emits has to be the canonical one: pointing a
    crawler at an alias teaches it the wrong address for the whole site.
    """
    try:
        hostname = normalize_hostname(host, allow_port=True)
    except InvalidHostname as error:
        raise PublicSiteNotFound from error
    domain = (
        Domain.all_objects.select_related("site", "organization")
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
    origin = settings.PUBLIC_SITE_SCHEME + "://" + canonical.hostname
    return domain, origin


def render_site_feed(*, host: str) -> HttpResponse:
    """RSS 2.0 over every published entry, newest first."""
    domain, origin = _resolve_site(host)
    entries = published_entries(
        organization_id=domain.organization_id, site_id=domain.site_id
    )
    items = []
    for entry in entries:
        parts = [
            "<title>" + escape(entry["title"]) + "</title>",
            "<link>" + escape(origin + entry["path"]) + "</link>",
            # The address is stable and unique per entry, which is exactly what
            # a GUID has to be; `isPermaLink` says so rather than leaving the
            # reader's client to guess.
            '<guid isPermaLink="true">' + escape(origin + entry["path"]) + "</guid>",
        ]
        if entry["excerpt"]:
            parts.append("<description>" + escape(entry["excerpt"]) + "</description>")
        if entry["published_at"] is not None:
            parts.append(
                "<pubDate>"
                + escape(_rfc822(entry["published_at"]))
                + "</pubDate>"
            )
        items.append("<item>" + "".join(parts) + "</item>")

    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0">'
        "<channel>"
        "<title>" + escape(domain.site.name) + "</title>"
        "<link>" + escape(origin + "/") + "</link>"
        "<description>" + escape(domain.site.name) + "</description>"
        + "".join(items)
        + "</channel></rss>"
    )
    return HttpResponse(document, content_type="application/rss+xml; charset=utf-8")


def render_site_sitemap(*, host: str) -> HttpResponse:
    """Published pages, collection indexes and entries, in one urlset.

    A crawler that only follows links never reaches an article the menu does
    not point at, which is every article on a blog older than its front page.
    """
    domain, origin = _resolve_site(host)
    locations: list[str] = []
    publication = domain.site.current_publication
    if publication is not None:
        for raw_page in publication.snapshot.get("pages", []):
            if not isinstance(raw_page, dict) or raw_page.get("noindex"):
                continue
            for raw_locale in raw_page.get("locales", []):
                if isinstance(raw_locale, dict) and raw_locale.get("path"):
                    locations.append(origin + str(raw_locale["path"]))
    for collection in ContentCollection.all_objects.filter(
        organization_id=domain.organization_id, site_id=domain.site_id
    ):
        locations.append(origin + "/" + collection.base_path + "/")
    for entry in published_entries(
        organization_id=domain.organization_id, site_id=domain.site_id
    ):
        locations.append(origin + entry["path"])

    seen: set[str] = set()
    urls = []
    for location in locations:
        if location in seen:
            continue
        seen.add(location)
        urls.append("<url><loc>" + escape(location) + "</loc></url>")
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(urls)
        + "</urlset>"
    )
    return HttpResponse(document, content_type="application/xml; charset=utf-8")


def render_site_robots(*, host: str) -> HttpResponse:
    """Points a crawler at the sitemap it would otherwise never look for.

    Without this line the sitemap is discoverable only by somebody submitting
    it by hand in a search console, which is not something a client of ours is
    going to do.
    """
    _domain, origin = _resolve_site(host)
    document = "User-agent: *\nAllow: /\nSitemap: " + origin + "/sitemap.xml\n"
    return HttpResponse(document, content_type="text/plain; charset=utf-8")


_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _rfc822(value: Any) -> str:
    """RSS dates are RFC 822, and readers reject anything else.

    Built by hand rather than with `strftime`, whose day and month names follow
    the server locale — a Polish locale would emit "pon" and break every feed
    reader that parses the field.
    """
    moment = value.astimezone(UTC)
    date = f"{_DAYS[moment.weekday()]}, {moment.day:02d}"
    month = f"{_MONTHS[moment.month - 1]} {moment.year:04d}"
    clock = f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"
    return f"{date} {month} {clock} +0000"

