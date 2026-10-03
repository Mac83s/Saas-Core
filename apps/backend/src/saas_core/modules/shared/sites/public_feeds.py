from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from .domains import InvalidHostname, normalize_hostname
from .localization import collection_index_path
from .models import ContentCollection, Domain, DomainStatus
from .publication_routing import (
    TAG_INDEX_THRESHOLD,
    PublicSiteNotFound,
    entries_by_locale,
    feed_path,
    index_languages,
    index_page_path,
    language_home,
    navigation_links,
    parse_moment,
    published_entries,
    serving_locales,
    tag_archive_path,
    visible_snapshot,
)

#: How many articles a feed carries. A reader wants what is new; handing it
#: ten thousand items makes a slow response nobody reads to the end.
FEED_LIMIT = 50


def _resolve_site(host: str) -> tuple[Any, str, frozenset[str]]:
    """The site behind a visitor's host, the address it calls its own and the
    languages a visitor may read there now (ADR-071 pkt 8).

    Every URL a feed or a sitemap emits has to be the canonical one: pointing a
    crawler at an alias teaches it the wrong address for the whole site.
    """
    try:
        hostname = normalize_hostname(host, allow_port=True)
    except InvalidHostname as error:
        raise PublicSiteNotFound from error
    domain = (
        Domain.all_objects.select_related("site__current_publication")
        .defer("site__current_publication__snapshot")
        .filter(hostname=hostname, status=DomainStatus.VERIFIED)
        .first()
    )
    locales = serving_locales(domain.organization_id) if domain is not None else None
    if domain is None or locales is None:
        raise PublicSiteNotFound
    canonical = Domain.all_objects.filter(
        site_id=domain.site_id,
        status=DomainStatus.VERIFIED,
        is_canonical=True,
    ).first()
    if canonical is None:
        raise PublicSiteNotFound
    origin = settings.PUBLIC_SITE_SCHEME + "://" + canonical.hostname
    return domain, origin, locales | {domain.site.default_locale}


def _feed_language(domain: Any, locale: str | None, available: frozenset[str]) -> str:
    """The language a feed is in: the site's at `/rss.xml`, another at
    `/en/rss.xml` (TL14). The site's own language has one address only, and a
    language visitors may not read has none."""
    if not locale:
        return str(domain.site.default_locale)
    if locale == domain.site.default_locale or locale not in available:
        raise PublicSiteNotFound
    return locale


def _feed_entries(domain: Any, language: str, available: frozenset[str]) -> list[dict[str, Any]]:
    """The articles in one language: a reader subscribed to the Polish blog
    gets the Polish texts, not the same article twice under two titles."""
    return [
        entry
        for entry in published_entries(
            organization_id=domain.organization_id, site_id=domain.site_id, available=available
        )
        if entry["locale"] == language
    ][:FEED_LIMIT]


def render_site_feed(*, host: str, locale: str | None = None) -> HttpResponse:
    """RSS 2.0 over every published entry in one language, newest first."""
    domain, origin, available = _resolve_site(host)
    language = _feed_language(domain, locale, available)
    entries = _feed_entries(domain, language, available)
    default_locale = str(domain.site.default_locale)
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
            parts.append("<dc:creator>" + escape(entry["author_name"]) + "</dc:creator>")
        if entry["published_at"] is not None:
            parts.append("<pubDate>" + escape(_rfc822(entry["published_at"])) + "</pubDate>")
        items.append("<item>" + "".join(parts) + "</item>")

    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<channel>"
        "<title>" + escape(domain.site.name) + "</title>"
        "<link>" + escape(origin + language_home(default_locale, language)) + "</link>"
        "<description>" + escape(domain.site.name) + "</description>"
        "<language>" + escape(language) + "</language>" + "".join(items) + "</channel></rss>"
    )
    return HttpResponse(document, content_type="application/rss+xml; charset=utf-8")


def render_site_atom(*, host: str, locale: str | None = None) -> HttpResponse:
    """The same articles as the RSS feed, in the format some readers insist on.

    Atom is not a nicer RSS: it fixes two things this content actually needs.
    Dates are RFC 3339, so a reader never has to guess at a locale-dependent
    month name, and an entry carries an author element that is a name rather
    than an email address.
    """
    domain, origin, available = _resolve_site(host)
    language = _feed_language(domain, locale, available)
    entries = _feed_entries(domain, language, available)
    default_locale = str(domain.site.default_locale)
    own = origin + feed_path(default_locale, language, "atom.xml")
    # The feed's own `updated` is the newest article's, and "now" when there is
    # none: a feed that claims to change every time it is fetched teaches a
    # reader to stop trusting the field.
    stamps = [entry["updated_at"] for entry in entries if entry["updated_at"] is not None]
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
            parts.append("<published>" + escape(_rfc3339(entry["published_at"])) + "</published>")
        if entry["author_name"]:
            parts.append("<author><name>" + escape(entry["author_name"]) + "</name></author>")
        if entry["excerpt"]:
            parts.append('<summary type="text">' + escape(entry["excerpt"]) + "</summary>")
        items.append("<entry>" + "".join(parts) + "</entry>")

    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="' + escape(language) + '">'
        "<id>" + escape(own) + "</id>"
        "<title>" + escape(domain.site.name) + "</title>"
        "<updated>" + escape(_rfc3339(updated)) + "</updated>"
        '<link rel="self" href="' + escape(own) + '"/>'
        '<link rel="alternate" href="'
        + escape(origin + language_home(default_locale, language))
        + '"/>'
        + "".join(items)
        + "</feed>"
    )
    return HttpResponse(document, content_type="application/atom+xml; charset=utf-8")


@dataclass(frozen=True, slots=True)
class _Location:
    """One address in the sitemap, with its language versions (TL14)."""

    path: str
    changed: datetime | None = None
    #: Every language's version of this page, itself included, by locale —
    #: only versions that are public, so never a withheld or a switched-off one.
    versions: dict[str, str] = field(default_factory=dict)


def _latest(items: list[dict[str, Any]]) -> datetime | None:
    stamps = [item["changed_at"] for item in items if item.get("changed_at") is not None]
    return max(stamps) if stamps else None


def render_site_sitemap(*, host: str) -> HttpResponse:
    """Published pages, collection indexes and entries, in one urlset.

    A crawler that only follows links never reaches an article the menu does
    not point at, which is every article on a blog older than its front page.
    Each address names its versions in the other languages, with one x-default
    for the cluster, and `lastmod` is when that language's text last changed
    (ADR-071 pkt 15).
    """
    domain, origin, available = _resolve_site(host)
    site_locale = str(domain.site.default_locale)
    locations: list[_Location] = []
    publication = domain.site.current_publication
    if publication is not None:
        for raw_page in visible_snapshot(publication, available)["pages"]:
            if raw_page.get("noindex"):
                continue
            # Built by the visible snapshot from the versions visitors get:
            # never one withheld after its source changed a fact, nor one in a
            # language the company switched off (TL10c).
            versions = {str(code): str(path) for code, path in raw_page["hreflang"].items()}
            for raw_locale in raw_page.get("locales", []):
                if isinstance(raw_locale, dict) and raw_locale.get("path"):
                    locations.append(
                        _Location(
                            str(raw_locale["path"]),
                            parse_moment(raw_locale.get("changed_at")),
                            versions,
                        )
                    )
    entries = published_entries(
        organization_id=domain.organization_id, site_id=domain.site_id, available=available
    )
    page_size = settings.SITES_ENTRY_INDEX_PAGE_SIZE
    for collection in ContentCollection.all_objects.filter(
        organization_id=domain.organization_id, site_id=domain.site_id
    ):
        grouped = entries_by_locale(entries, str(collection.id))
        languages = index_languages(site_locale, grouped)
        firsts = {
            locale: collection_index_path(
                default_locale=site_locale, locale=locale, base_path=collection.base_path
            )
            for locale in languages
        }
        # Each language's index where it answers (TL14), with every page of
        # it, not just the first. An article that has scrolled off page one is
        # otherwise reachable by no link a crawler follows, which on a blog is
        # most of the archive. Only the first pages are one page in several
        # languages; page three lists different articles in each.
        for locale in languages:
            listed = grouped.get(locale, [])
            first = firsts[locale]
            locations.append(_Location(first, _latest(listed[:page_size]), firsts))
            pages = max(1, -(-len(listed) // page_size))
            for number in range(2, pages + 1):
                window = listed[(number - 1) * page_size : number * page_size]
                locations.append(_Location(index_page_path(first, locale, number), _latest(window)))
        # One address per subject that has enough articles to be worth
        # indexing. Below that the archive exists for readers but asks not to
        # be indexed, so listing it — or naming it as another's version —
        # would contradict the page itself.
        topics: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for locale in languages:
            for item in grouped.get(locale, []):
                for tag in item["tags"]:
                    slug = str(tag.get("slug", ""))
                    if slug:
                        topics.setdefault(slug, {}).setdefault(locale, []).append(item)
        for slug, by_locale in sorted(topics.items()):
            indexed = {
                locale: tag_archive_path(index_path=firsts[locale], slug=slug)
                for locale, items in by_locale.items()
                if len(items) >= TAG_INDEX_THRESHOLD
            }
            for locale, path in sorted(indexed.items()):
                locations.append(_Location(path, _latest(by_locale[locale]), indexed))
    # Each language of an article is its own entry; the group makes them one
    # article to a search engine.
    articles: dict[str, dict[str, str]] = {}
    for entry in entries:
        articles.setdefault(entry["translation_group"], {})[entry["locale"]] = entry["path"]
    for entry in entries:
        locations.append(
            _Location(entry["path"], entry["changed_at"], articles[entry["translation_group"]])
        )

    seen: set[str] = set()
    urls = []
    for location in locations:
        if location.path in seen:
            continue
        seen.add(location.path)
        parts = ["<loc>" + escape(origin + location.path) + "</loc>"]
        if location.changed is not None:
            parts.append("<lastmod>" + escape(location.changed.date().isoformat()) + "</lastmod>")
        parts.extend(_alternates(origin, location.versions, site_locale))
        urls.append("<url>" + "".join(parts) + "</url>")
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        ' xmlns:xhtml="http://www.w3.org/1999/xhtml">' + "".join(urls) + "</urlset>"
    )
    return HttpResponse(document, content_type="application/xml; charset=utf-8")


def _alternates(origin: str, versions: dict[str, str], site_locale: str) -> list[str]:
    """The `xhtml:link` of a page in several languages: each version, itself
    included, and one x-default for the whole cluster — the site's language
    when it has one, otherwise the first code, as for an article."""
    if len(versions) < 2:
        return []
    ordered = sorted(versions, key=lambda code: (code != site_locale, code))
    default = versions.get(site_locale) or versions[min(versions)]
    return [
        '<xhtml:link rel="alternate" hreflang="'
        + escape(code)
        + '" href="'
        + escape(origin + path)
        + '"/>'
        for code, path in [*((code, versions[code]) for code in ordered), ("x-default", default)]
    ]


#: Links an llms.txt carries. The file is a map for a model's first read, not
#: a sitemap: past fifty it stops being one (and the format's checkers say so).
LLMS_LINK_LIMIT = 50
_LLMS_SECTIONS = {
    "pages": {"pl": "Strony", "en": "Pages", "de": "Seiten", "es": "Páginas", "ru": "Страницы"},
    "articles": {
        "pl": "Najnowsze wpisy",
        "en": "Latest articles",
        "de": "Neueste Artikel",
        "es": "Últimos artículos",
        "ru": "Последние статьи",
    },
}


def _llms_text(value: Any) -> str:
    """One line of plain text: Markdown would read a bracket or a break as its own."""
    return " ".join(str(value or "").split()).replace("[", "(").replace("]", ")")


def llms_path(default_locale: str, locale: str) -> str:
    """`/llms.txt` in the site's language, `/en/llms.txt` in another (TL19)."""
    return feed_path(default_locale, locale, "llms.txt")


def _page_versions(snapshot: dict[str, Any], language: str) -> dict[str, dict[str, Any]]:
    """The versions of the site's pages a visitor gets in one language, by
    page; a page kept out of search engines is not offered to a model either."""
    versions: dict[str, dict[str, Any]] = {}
    for raw_page in snapshot["pages"]:
        if raw_page.get("noindex"):
            continue
        for raw_locale in raw_page.get("locales", []):
            if (
                isinstance(raw_locale, dict)
                and raw_locale.get("locale") == language
                and raw_locale.get("path")
            ):
                versions[str(raw_page.get("page_id"))] = raw_locale
    return versions


def search_addresses(*, site: Any, origin: str, languages: tuple[str, ...]) -> dict[str, Any]:
    """What a search engine and a language model are pointed at on one site
    (TL19): the sitemap, `robots.txt`, and per language the site answers in
    now its home and its `llms.txt` — by the rules those addresses themselves
    answer by, so the panel never lists one that gives 404.

    `languages`: the company's languages this deployment serves, in its order.
    """
    publication = site.current_publication
    default_locale = str(site.default_locale)
    if publication is None:
        return {"sitemap_url": None, "robots_url": None, "languages": []}
    available = frozenset(languages) | {default_locale}
    snapshot = visible_snapshot(publication, available)
    written = {
        str(entry["locale"])
        for entry in published_entries(
            organization_id=site.organization_id, site_id=site.id, available=available
        )
    }
    rows = []
    for language in dict.fromkeys((default_locale, *languages)):
        versions = _page_versions(snapshot, language)
        home = language_home(default_locale, language)
        has_home = any(version["path"] == home for version in versions.values())
        has_llms = bool(versions) or language in written
        if not has_home and not has_llms:
            continue
        rows.append({
            "locale": language,
            "home_url": origin + home if has_home else None,
            "llms_url": origin + llms_path(default_locale, language) if has_llms else None,
        })
    return {
        "sitemap_url": origin + "/sitemap.xml",
        "robots_url": origin + "/robots.txt",
        "languages": rows,
    }


def render_site_llms(*, host: str, locale: str | None = None) -> HttpResponse:
    """`/llms.txt` (llmstxt.org): what the site is and where its pages are, in
    one language, for a language model's first read (TL19).

    An H1 with the site's name, its tagline as the summary, the pages in the
    menu's order and the newest articles — only addresses a visitor gets now,
    in that language, and at most fifty of them. `/xx/llms.txt` is the same for
    another language the site is live in; the site's own language has the
    bare address only."""
    domain, origin, available = _resolve_site(host)
    language = _feed_language(domain, locale, available)
    site = domain.site
    default_locale = str(site.default_locale)
    publication = site.current_publication
    if publication is None:
        raise PublicSiteNotFound
    snapshot = visible_snapshot(publication, available)
    versions = _page_versions(snapshot, language)
    home = next(
        (
            version
            for version in versions.values()
            if version["path"] == language_home(default_locale, language)
        ),
        None,
    )
    entries = _feed_entries(domain, language, available)
    if not versions and not entries:
        # A language the company serves but this site is not written in.
        raise PublicSiteNotFound

    appearance = snapshot.get("appearance") or {}
    header = appearance.get("header") if isinstance(appearance, dict) else None
    header = header if isinstance(header, dict) else {}
    texts = (snapshot.get("site_texts") or {}).get(language) or {}
    name = _llms_text(header.get("brand") or site.name)
    # The tagline in this language; untranslated, the home page says it better
    # than another language's tagline would.
    tagline = header.get("tagline") if language == default_locale else texts.get("header/tagline")
    summary = _llms_text(tagline or (home or {}).get("description"))

    def line(title: Any, path: Any, description: Any) -> str:
        text = f"- [{_llms_text(title)}]({origin}{path})"
        described = _llms_text(description)
        return f"{text}: {described}" if described else text

    menu = navigation_links(
        snapshot,
        language,
        collections=frozenset(entry["collection_id"] for entry in entries),
    )
    pages: list[str] = []
    listed: set[str] = set()
    for link in menu:
        version = versions.get(str(link["page_id"]))
        path = str(version["path"] if version else link["path"])
        if not path or path in listed:
            continue
        listed.add(path)
        pages.append(line(link["title"], path, (version or {}).get("description")))
    for version in versions.values():
        # Pages the menu does not name still answer, and a model may be asked
        # about them.
        if version["path"] not in listed:
            listed.add(str(version["path"]))
            pages.append(line(version.get("title"), version["path"], version.get("description")))
    pages = pages[:LLMS_LINK_LIMIT]
    articles = [
        line(entry["title"], entry["path"], entry["excerpt"])
        for entry in entries[: LLMS_LINK_LIMIT - len(pages)]
    ]

    parts = [f"# {name}", ""]
    if summary:
        parts += [f"> {summary}", ""]
    for key, lines in (("pages", pages), ("articles", articles)):
        if lines:
            heading = _LLMS_SECTIONS[key].get(language) or _LLMS_SECTIONS[key]["en"]
            parts += [f"## {heading}", "", *lines, ""]
    return HttpResponse("\n".join(parts), content_type="text/plain; charset=utf-8")


def render_site_robots(*, host: str) -> HttpResponse:
    """Points a crawler at the sitemap it would otherwise never look for.

    Without this line the sitemap is discoverable only by somebody submitting
    it by hand in a search console, which is not something a client of ours is
    going to do.
    """
    _domain, origin, _available = _resolve_site(host)
    document = "User-agent: *\nAllow: /\nSitemap: " + origin + "/sitemap.xml\n"
    return HttpResponse(document, content_type="text/plain; charset=utf-8")


_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
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
