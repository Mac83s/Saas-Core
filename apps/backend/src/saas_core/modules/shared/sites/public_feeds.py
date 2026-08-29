from __future__ import annotations

from datetime import UTC
from typing import Any
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from saas_core.modules.core.organizations.models import OrganizationStatus

from .domains import InvalidHostname, normalize_hostname
from .localization import collection_index_path
from .models import ContentCollection, Domain, DomainStatus
from .publication_routing import (
    TAG_INDEX_THRESHOLD,
    PublicSiteNotFound,
    index_page_path,
    one_per_article,
    published_entries,
    tag_archive_path,
)

#: How many articles a feed carries. A reader wants what is new; handing it
#: ten thousand items makes a slow response nobody reads to the end.
FEED_LIMIT = 50


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
    )[:FEED_LIMIT]
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
        if entry["author_name"]:
            # `dc:creator` rather than RSS's own `author`, which is specified as
            # an email address: publishing a person's address to satisfy a
            # schema is not a trade worth making.
            parts.append(
                "<dc:creator>" + escape(entry["author_name"]) + "</dc:creator>"
            )
        if entry["published_at"] is not None:
            parts.append(
                "<pubDate>"
                + escape(_rfc822(entry["published_at"]))
                + "</pubDate>"
            )
        items.append("<item>" + "".join(parts) + "</item>")

    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<channel>"
        "<title>" + escape(domain.site.name) + "</title>"
        "<link>" + escape(origin + "/") + "</link>"
        "<description>" + escape(domain.site.name) + "</description>"
        + "".join(items)
        + "</channel></rss>"
    )
    return HttpResponse(document, content_type="application/rss+xml; charset=utf-8")


def render_site_atom(*, host: str) -> HttpResponse:
    """The same articles as the RSS feed, in the format some readers insist on.

    Atom is not a nicer RSS: it fixes two things this content actually needs.
    Dates are RFC 3339, so a reader never has to guess at a locale-dependent
    month name, and an entry carries an author element that is a name rather
    than an email address.
    """
    domain, origin = _resolve_site(host)
    entries = published_entries(
        organization_id=domain.organization_id, site_id=domain.site_id
    )[:FEED_LIMIT]
    # The feed's own `updated` is the newest article's, and "now" when there is
    # none: a feed that claims to change every time it is fetched teaches a
    # reader to stop trusting the field.
    stamps = [
        entry["updated_at"] for entry in entries if entry["updated_at"] is not None
    ]
    updated = max(stamps) if stamps else timezone.now()

    items = []
    for entry in entries:
        address = origin + entry["path"]
        parts = [
            "<id>" + escape(address) + "</id>",
            "<title>" + escape(entry["title"]) + "</title>",
            '<link rel="alternate" href="' + escape(address) + '"/>',
            "<updated>" + escape(_rfc3339(entry["updated_at"] or updated)) + "</updated>",
        ]
        if entry["published_at"] is not None:
            parts.append(
                "<published>" + escape(_rfc3339(entry["published_at"])) + "</published>"
            )
        if entry["author_name"]:
            parts.append(
                "<author><name>" + escape(entry["author_name"]) + "</name></author>"
            )
        if entry["excerpt"]:
            parts.append(
                '<summary type="text">' + escape(entry["excerpt"]) + "</summary>"
            )
        items.append("<entry>" + "".join(parts) + "</entry>")

    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<id>" + escape(origin + "/atom.xml") + "</id>"
        "<title>" + escape(domain.site.name) + "</title>"
        "<updated>" + escape(_rfc3339(updated)) + "</updated>"
        '<link rel="self" href="' + escape(origin + "/atom.xml") + '"/>'
        '<link rel="alternate" href="' + escape(origin + "/") + '"/>'
        + "".join(items)
        + "</feed>"
    )
    return HttpResponse(document, content_type="application/atom+xml; charset=utf-8")


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
    entries = published_entries(
        organization_id=domain.organization_id, site_id=domain.site_id
    )
    site_locale = domain.site.default_locale
    for collection in ContentCollection.all_objects.filter(
        organization_id=domain.organization_id, site_id=domain.site_id
    ):
        first = collection_index_path(
            default_locale=site_locale,
            locale=site_locale,
            base_path=collection.base_path,
        )
        locations.append(origin + first)
        # Every page of the index, not just the first. An article that has
        # scrolled off page one is otherwise reachable by no link a crawler
        # follows, which on a blog is most of the archive.
        listed = one_per_article(
            [item for item in entries if item["collection_id"] == str(collection.id)],
            site_locale,
        )
        pages = max(1, -(-len(listed) // settings.SITES_ENTRY_INDEX_PAGE_SIZE))
        for number in range(2, pages + 1):
            locations.append(origin + index_page_path(first, site_locale, number))
        # One address per subject that has enough articles to be worth
        # indexing. Below that the archive exists for readers but asks not to
        # be indexed, so listing it would contradict the page itself.
        counts: dict[str, int] = {}
        for item in listed:
            for tag in item["tags"]:
                slug = str(tag.get("slug", ""))
                if slug:
                    counts[slug] = counts.get(slug, 0) + 1
        for slug, count in sorted(counts.items()):
            if count >= TAG_INDEX_THRESHOLD:
                locations.append(
                    origin + tag_archive_path(index_path=first, slug=slug)
                )
    for entry in entries:
        locations.append(origin + entry["path"])
    last_changed = {
        origin + entry["path"]: entry["updated_at"]
        for entry in entries
        if entry["updated_at"] is not None
    }

    seen: set[str] = set()
    urls = []
    for location in locations:
        if location in seen:
            continue
        seen.add(location)
        changed = last_changed.get(location)
        stamp = (
            "<lastmod>" + escape(changed.date().isoformat()) + "</lastmod>"
            if changed is not None
            else ""
        )
        urls.append("<url><loc>" + escape(location) + "</loc>" + stamp + "</url>")
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


def _rfc3339(value: Any) -> str:
    """Atom's date format, which is ISO 8601 with a timezone that is present.

    Built from an aware UTC value rather than whatever the row carried, so the
    offset is always `+00:00` and never the server's accidental local zone.
    """
    return str(value.astimezone(UTC).isoformat())


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

