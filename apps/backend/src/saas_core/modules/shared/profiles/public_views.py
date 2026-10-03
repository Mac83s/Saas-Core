"""Everything the public catalogue reads, in one file on purpose.

ADR-039 allows a read without a tenant only on a module's explicitly public
paths, and ADR-053 §4 puts all of this module's here. Two rules hold the file
together:

- only `profiles_catalogentry` is read without a tenant. It is declared in
  `publicTables` and contains company entries only — never people;
- the slug is the tenant declaration, exactly as a hostname is for the site
  renderer. Anything beyond the catalogue row is read *inside* the tenant the
  slug named, under policy, and never through the pre-tenant connection.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Case, FloatField, QuerySet, Value, When
from drf_spectacular.utils import OpenApiParameter, extend_schema
from prometheus_client import Counter
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization

from .card_languages import card_in_language
from .catalog_contract import categories, cities, cities_within
from .models import (
    CatalogEntry,
    ProfileSubjectKind,
    PublicProfile,
    PublicProfileTranslation,
)
from .search_engine import SearchEngineUnavailable
from .search_index import search_ids, similar_ids
from .serializers import (
    CatalogDictionarySerializer,
    CatalogPageSerializer,
    CatalogProfileSerializer,
    CatalogSitemapPageSerializer,
)

logger = logging.getLogger(__name__)

#: One screen of results. Small enough that the join to the site tables stays
#: cheap, large enough that a small town fits on one page.
PAGE_SIZE = 20
#: "Może też" under the entries that contain the words.
SIMILAR_BELOW = 6
#: "Near me" without a radius; the form's slider starts here too.
DEFAULT_RADIUS_KM = 25.0
MAX_RADIUS_KM = 200.0
#: Entries per page of the sitemap feed; well under the 50 000 URLs a sitemap
#: file may hold, even with every entry in five languages.
SITEMAP_PAGE_SIZE = 5000

CATALOG_SEARCHES = Counter(
    "saas_core_catalog_searches_total",
    "Text searches of the public catalogue by the path that answered them.",
    ["engine"],
)


class CatalogEntryNotFound(NotFound):
    default_detail = "Nie ma takiej wizytówki w katalogu."
    default_code = "catalog_entry_not_found"


def site_url(entry: CatalogEntry) -> str | None:
    """The published address of the entry's site, when it has a reachable one.

    ADR-053 §5: not stored on the row. `sites_domain` and `sites_publication`
    are already public tables, so this is a join rather than a copy — a copied
    address goes stale on the next domain change, and a join cannot. A site
    without a publication or without a verified domain answers None, and the
    entry then behaves like one with no site at all rather than leading into
    nothing.
    """
    if entry.site_id is None or "shared.sites" not in settings.ACTIVE_MODULES:
        return None
    from saas_core.modules.shared.sites.models import Domain, DomainStatus, Site

    site = Site.all_objects.filter(pk=entry.site_id).first()
    if site is None or site.current_publication_id is None:
        return None
    domains = list(Domain.all_objects.filter(site_id=entry.site_id, status=DomainStatus.VERIFIED))
    if not domains:
        return None
    canonical = next((domain for domain in domains if domain.is_canonical), domains[0])
    return f"https://{canonical.hostname}/"


def speaks(entry: CatalogEntry, locale: str | None) -> bool:
    """The card is whole in this language: its own, or a complete translation."""
    return bool(locale) and (
        locale == entry.source_locale or locale in (entry.translated_locales or ())
    )


def _entry_payload(
    entry: CatalogEntry, distance_km: float | None = None, locale: str | None = None
) -> dict[str, Any]:
    external = site_url(entry)
    translated = locale if speaks(entry, locale) and locale != entry.source_locale else None
    return {
        "slug": entry.slug,
        "city_slug": entry.city_slug,
        "city": entry.city,
        "category": entry.category,
        "display_name": entry.display_name,
        "headline": (entry.headline_by_locale or {}).get(translated, entry.headline)
        if translated
        else entry.headline,
        # The language the card's texts in this answer are in, the card's own,
        # and every language it is whole in besides (TL20).
        "locale": translated or entry.source_locale,
        "source_locale": entry.source_locale,
        "translated_locales": list(entry.translated_locales or ()),
        "photo_id": str(entry.photo_id) if entry.photo_id else None,
        # What the listing links to. The catalogue page is always a valid
        # target, so the client never has to decide what to do with a null.
        "url": external or f"/katalog/{entry.city_slug}/{entry.slug}/",
        "is_external": external is not None,
        # Town centre to town centre (ADR-064): an entry has a town, not an address.
        "distance_km": None if distance_km is None else round(distance_km, 1),
    }


def _database_page(
    entries: QuerySet[CatalogEntry],
    *,
    query: str,
    distances: dict[str, float] | None,
    page: int,
) -> tuple[list[CatalogEntry], int]:
    """The search PostgreSQL can do: prefix words, then town distance or name order.

    Every search went this way before the engine (ADR-053 §8); now it answers a
    listing without words, and any search while the engine does not answer.
    """
    from django.contrib.postgres.search import SearchQuery

    if query.strip():
        # Prefix matching, so "fryzjer" reaches "fryzjerstwo" without a Polish
        # stemmer. See the ceiling noted in `catalog._refresh_search`.
        terms = " & ".join(f"{term}:*" for term in query.split()[:6] if term.isalnum())
        if terms:
            entries = entries.filter(search=SearchQuery(terms, config="simple", search_type="raw"))
    if distances:
        entries = entries.annotate(
            distance=Case(
                *(When(city_slug=slug, then=Value(km)) for slug, km in distances.items()),
                output_field=FloatField(),
            )
        ).order_by("distance", "display_name", "id")
    start = (page - 1) * PAGE_SIZE
    return list(entries[start : start + PAGE_SIZE]), entries.count()


def _rows(entries: QuerySet[CatalogEntry], ids: list[UUID]) -> list[CatalogEntry]:
    """The table's rows for the engine's ids, in the engine's order.

    An id without a row — withdrawn a second ago — is dropped: the table has
    the last word on who is in the catalogue.
    """
    rows = {entry.organization_id: entry for entry in entries.filter(organization_id__in=ids)}
    return [rows[organization_id] for organization_id in ids if organization_id in rows]


def _similar(
    entries: QuerySet[CatalogEntry],
    query: str,
    city_slugs: list[str] | None,
    category: str,
    found: list[CatalogEntry],
) -> list[CatalogEntry]:
    try:
        ids = similar_ids(
            query=query,
            city_slugs=city_slugs,
            category=category,
            exclude={entry.organization_id for entry in found},
            limit=SIMILAR_BELOW if found else PAGE_SIZE,
        )
    except SearchEngineUnavailable:
        return []
    return _rows(entries, ids)


def search_catalog(
    *,
    city_slug: str = "",
    category: str = "",
    query: str = "",
    page: int = 1,
    point: tuple[float, float] | None = None,
    radius_km: float | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    """One page of the listing; with `locale`, headlines in that language
    where the card is whole in it (TL20), the card's own elsewhere.

    Words go to the search engine (ADR-064) and come back as organization ids;
    the rows themselves are read here, so the table stays the truth and an entry
    withdrawn a second ago is not shown even if the engine still has it.

    Distance: a point (the visitor's, or the chosen town's centre when a radius
    is asked for) turns into the list of dictionary towns within the radius, and
    both paths filter by that list — so they agree on what "within 25 km" means.
    """
    page = max(page, 1)
    distances: dict[str, float] | None = None
    city_slugs: list[str] | None = [city_slug] if city_slug else None
    if point is None and city_slug and radius_km is not None:
        city = cities()[city_slug]
        point = (city.lat, city.lng)
    if point is not None:
        distances = cities_within(point[0], point[1], radius_km or DEFAULT_RADIUS_KM)
        city_slugs = sorted(distances)

    entries = CatalogEntry.all_objects.select_related("site", "photo")
    if city_slugs is not None:
        entries = entries.filter(city_slug__in=city_slugs)
    if category:
        entries = entries.filter(category=category)

    found: list[CatalogEntry] | None = None
    similar: list[CatalogEntry] = []
    total = 0
    if query.strip() and city_slugs != []:
        try:
            ids, total = search_ids(
                query=query,
                city_slugs=city_slugs,
                category=category,
                page=page,
                page_size=PAGE_SIZE,
            )
        except SearchEngineUnavailable as error:
            # No query text in the log: in some products a search says
            # something about the visitor's health.
            logger.warning("catalog_search_fallback", extra={"reason": str(error)})
        else:
            CATALOG_SEARCHES.labels(engine="search").inc()
            found = _rows(entries, ids)
            if page == 1:
                similar = _similar(entries, query, city_slugs, category, found)
    if found is None:
        if query.strip():
            CATALOG_SEARCHES.labels(engine="database").inc()
        found, total = _database_page(entries, query=query, distances=distances, page=page)

    return {
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "items": [
            _entry_payload(
                entry, None if distances is None else distances.get(entry.city_slug), locale
            )
            for entry in found
        ],
        # What fits the words by meaning without containing them (ADR-064 §8):
        # "Podobne" when `items` is empty, "Może też" below them otherwise.
        "similar": [
            _entry_payload(
                entry, None if distances is None else distances.get(entry.city_slug), locale
            )
            for entry in similar
        ],
        # Whether any card in the whole catalogue is whole in `locale`: a listing
        # in a language nobody speaks yet is `noindex` and stays out of the
        # sitemap (TL20). Null without `locale`.
        "locale_has_entries": _locale_has_entries(locale) if locale else None,
    }


def _locale_has_entries(locale: str) -> bool:
    return (
        CatalogEntry.all_objects.filter(source_locale=locale).exists()
        or CatalogEntry.all_objects.filter(translated_locales__contains=[locale]).exists()
    )


def catalog_sitemap(*, page: int) -> dict[str, Any]:
    """Every entry's address and languages, for the platform's sitemap (TL20).

    One table, no tenant: the languages are the row's copy, so a sitemap of
    the whole catalogue is a page of rows, not a page of tenants."""
    page = max(page, 1)
    entries = CatalogEntry.all_objects.order_by("city_slug", "slug")
    start = (page - 1) * SITEMAP_PAGE_SIZE
    rows = entries.values("city_slug", "slug", "source_locale", "translated_locales", "updated_at")[
        start : start + SITEMAP_PAGE_SIZE
    ]
    return {
        "page": page,
        "page_size": SITEMAP_PAGE_SIZE,
        "total": entries.count(),
        "items": [{**row, "translated_locales": list(row["translated_locales"])} for row in rows],
    }


def resolve_catalog_profile(
    *, city_slug: str, slug: str, locale: str | None = None
) -> dict[str, Any]:
    """One catalogue page: the row names the tenant, the tenant answers for itself.

    With `locale` the card comes in that language when it is whole in it —
    every text translated, the language one the company serves (TL20) — and in
    its own language otherwise; never a mix. `fallback` is therefore empty
    unless the row's copy of the languages lags a write."""
    entry = (
        CatalogEntry.all_objects.select_related("site", "photo")
        .filter(city_slug=city_slug, slug=slug)
        .first()
    )
    if entry is None:
        raise CatalogEntryNotFound

    with transaction.atomic():
        # The slug named the tenant; from here on the row is read inside it and
        # the policy is what separates it. `all_objects` plus an explicit
        # organization filter is the same shape `serve_public_media` uses: the
        # tenant manager wants a full `TenantContext`, which a public request
        # does not have, and the filter is belt to the policy's braces.
        set_local_organization_id(entry.organization_id)
        profile = (
            PublicProfile.all_objects.filter(
                pk=entry.profile_id,
                organization_id=entry.organization_id,
                subject_kind=ProfileSubjectKind.ORGANIZATION,
            )
            .select_related("photo")
            .first()
        )
        # Policy answered "no rows" — the tenant was archived or removed while
        # its catalogue row lived on. Treat it as gone rather than as an error,
        # and let withdrawal or erasure clean the row up.
        if profile is None:
            raise CatalogEntryNotFound
        organization = Organization.objects.get(pk=entry.organization_id)
        asked = (
            locale
            if locale
            and locale != profile.locale
            and locale in (entry.translated_locales or ())
            and locale in organization_content_locales(organization)
            else None
        )
        translation = PublicProfileTranslation.all_objects.filter(
            organization_id=entry.organization_id, profile=profile, locale=asked or profile.locale
        ).first()

    city = cities().get(entry.city_slug)
    payload = {
        **_entry_payload(entry, locale=asked),
        "layout": profile.layout,
        "voivodeship": city.voivodeship if city else "",
        "bio": (translation.bio if translation and translation.bio else profile.bio),
        "contact_email": profile.contact_email,
        "contact_phone": profile.contact_phone,
        "contact_address": profile.contact_address,
        "links": profile.links,
        "languages": profile.languages,
        "specializations": profile.specializations,
        "locale": profile.locale,
        "fallback": [],
    }
    if asked is None or translation is None:
        return payload
    return {**payload, **card_in_language(profile, translation)}


def _locale_param(raw: str | None) -> str | None:
    """A registry language code, or None; anything else is no language at all."""
    return raw if raw and raw in settings.LOCALE_REGISTRY else None


def _coordinate(raw: str | None, limit: float) -> float | None:
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value is not None and -limit <= value <= limit else None


class PublicCatalogListView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    # A public text field in front of a paid embedding API (ADR-064).
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "catalog_search"

    @extend_schema(
        operation_id="catalog_list",
        summary="The public catalogue's listing",
        description="One page of the catalogue's companies, filtered by city, category, words "
        "or distance. With `locale` each card's headline comes in that language where the card "
        "is whole in it, and `locale_has_entries` says whether any card is.",
        extensions={
            "x-quality-exempt": {
                "error-400": "Filters outside the dictionary are dropped, never refused.",
            }
        },
        parameters=[
            OpenApiParameter("city", str, description="Slug miasta ze słownika katalogu."),
            OpenApiParameter("category", str, description="Klucz kategorii ze słownika."),
            OpenApiParameter(
                "q", str, description="Szukaj po nazwie, usługach, opisie, kategorii."
            ),
            OpenApiParameter("page", int, description="Strona wyników, od 1."),
            OpenApiParameter(
                "radius_km",
                float,
                description="Promień w km od środka miasta albo od punktu lat/lng.",
            ),
            OpenApiParameter("lat", float, description="Szerokość punktu „Blisko mnie”."),
            OpenApiParameter("lng", float, description="Długość punktu „Blisko mnie”."),
            OpenApiParameter(
                "locale",
                str,
                description="Język strony katalogu (kod z rejestru, np. de): nagłówki w nim, "
                "gdzie wizytówka jest w nim cała, i `locale_has_entries`.",
            ),
        ],
        responses={200: CatalogPageSerializer},
    )
    def get(self, request: Request) -> Response:
        # Only dictionary values are accepted as filters (ADR-053 §7): the
        # catalogue is a public surface, and a filter that takes arbitrary text
        # is a scan somebody else pays for.
        params = request.query_params
        city_slug = params.get("city", "")
        category = params.get("category", "")
        organization_type = settings.DEFAULT_ORGANIZATION_TYPE
        if city_slug and city_slug not in cities():
            city_slug = ""
        if category and category not in categories(organization_type):
            category = ""
        try:
            page = int(params.get("page", "1"))
        except ValueError:
            page = 1
        radius_km = _coordinate(params.get("radius_km"), MAX_RADIUS_KM)
        if radius_km is not None and radius_km <= 0:
            radius_km = None
        lat, lng = _coordinate(params.get("lat"), 90), _coordinate(params.get("lng"), 180)
        # The visitor's point is used for this answer and nowhere else: not
        # stored, not logged.
        point = (lat, lng) if lat is not None and lng is not None else None
        return Response(
            search_catalog(
                city_slug=city_slug,
                category=category,
                query=params.get("q", "")[:120],
                page=page,
                point=point,
                radius_km=radius_km,
                locale=_locale_param(params.get("locale")),
            )
        )


class PublicCatalogDetailView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="catalog_profile",
        summary="One company's catalogue page",
        description="The company's public card in the catalogue. With `locale` the headline, "
        "bio and link labels come in that language of the company when the card has them; "
        "`locale` in the answer says which language was served and `fallback` lists what "
        "stayed in the card's own language.",
        parameters=[
            OpenApiParameter(
                "locale",
                str,
                required=False,
                description="A language code of the registry, e.g. de. A language the company "
                "does not have is answered in the card's own.",
            )
        ],
        responses={200: CatalogProfileSerializer, 404: ProblemDetailsSerializer},
        extensions={
            "x-quality-exempt": {
                "error-400": "An unknown language is served in the card's own, never refused.",
            }
        },
    )
    def get(self, request: Request, city_slug: str, slug: str) -> Response:
        locale = request.query_params.get("locale") or None
        return Response(resolve_catalog_profile(city_slug=city_slug, slug=slug, locale=locale))


class PublicCatalogSitemapView(APIView):
    """Every catalogue address with its languages, for the platform sitemap."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="catalog_sitemap",
        summary="The catalogue's addresses for the sitemap",
        description="One page of every catalogue entry: its city and slug, the language the "
        "card is written in, the languages it has a complete translation in, and when it last "
        "changed. Pages hold `page_size` entries in address order; the platform's sitemap "
        "lists the card in its own language and in each translated one.",
        parameters=[OpenApiParameter("page", int, description="Strona, od 1.")],
        responses={200: CatalogSitemapPageSerializer},
        extensions={
            "x-quality-exempt": {
                "error-400": "A page that is not a number is the first page, never refused.",
            }
        },
    )
    def get(self, request: Request) -> Response:
        try:
            page = int(request.query_params.get("page", "1"))
        except ValueError:
            page = 1
        return Response(catalog_sitemap(page=page))


class PublicCatalogDictionaryView(APIView):
    """The dictionary the catalogue filters by, for the search form to render."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(operation_id="catalog_dictionary", responses={200: CatalogDictionarySerializer})
    def get(self, request: Request) -> Response:
        organization_type = settings.DEFAULT_ORGANIZATION_TYPE
        return Response({
            "cities": [
                {"slug": city.slug, "name": city.name, "voivodeship": city.voivodeship}
                for city in cities().values()
            ],
            "categories": [
                {"key": category.key, "labels": category.label}
                for category in categories(organization_type).values()
            ],
        })
