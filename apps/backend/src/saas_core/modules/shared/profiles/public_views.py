"""Everything the public catalogue reads, in one file on purpose.

ADR-039 allows a read without a tenant only on a module's explicitly public
paths, and ADR-053 §4 puts all of this module's here. Two rules hold the file
together:

- only `profiles_catalogentry` is read without a tenant. It is declared in
  `publicTables` and contains company entries only — never people;
- the slug is the tenant declaration, exactly as a hostname is for the site
  renderer. Anything beyond the catalogue row is read *inside* the tenant the
  slug named, under policy, and never through `PRE_TENANT_DB`.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.context import set_local_organization_id

from .catalog_contract import categories, cities
from .models import (
    CatalogEntry,
    ProfileSubjectKind,
    PublicProfile,
    PublicProfileTranslation,
)
from .serializers import (
    CatalogDictionarySerializer,
    CatalogPageSerializer,
    CatalogProfileSerializer,
)

#: One screen of results. Small enough that the join to the site tables stays
#: cheap, large enough that a small town fits on one page.
PAGE_SIZE = 20


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


def _entry_payload(entry: CatalogEntry) -> dict[str, Any]:
    external = site_url(entry)
    return {
        "slug": entry.slug,
        "city_slug": entry.city_slug,
        "city": entry.city,
        "category": entry.category,
        "display_name": entry.display_name,
        "headline": entry.headline,
        "photo_id": str(entry.photo_id) if entry.photo_id else None,
        # What the listing links to. The catalogue page is always a valid
        # target, so the client never has to decide what to do with a null.
        "url": external or f"/katalog/{entry.city_slug}/{entry.slug}/",
        "is_external": external is not None,
    }


def search_catalog(
    *, city_slug: str = "", category: str = "", query: str = "", page: int = 1
) -> dict[str, Any]:
    from django.contrib.postgres.search import SearchQuery

    entries = CatalogEntry.all_objects.select_related("site", "photo")
    if city_slug:
        entries = entries.filter(city_slug=city_slug)
    if category:
        entries = entries.filter(category=category)
    if query.strip():
        # Prefix matching, so "fryzjer" reaches "fryzjerstwo" without a Polish
        # stemmer. See the ceiling noted in `catalog._refresh_search`.
        terms = " & ".join(f"{term}:*" for term in query.split()[:6] if term.isalnum())
        if terms:
            entries = entries.filter(search=SearchQuery(terms, config="simple", search_type="raw"))

    total = entries.count()
    start = max(page - 1, 0) * PAGE_SIZE
    return {
        "total": total,
        "page": max(page, 1),
        "page_size": PAGE_SIZE,
        "items": [_entry_payload(entry) for entry in entries[start : start + PAGE_SIZE]],
    }


def resolve_catalog_profile(*, city_slug: str, slug: str) -> dict[str, Any]:
    """One catalogue page: the row names the tenant, the tenant answers for itself."""
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
        translation = PublicProfileTranslation.all_objects.filter(
            organization_id=entry.organization_id, profile=profile, locale=profile.locale
        ).first()

    city = cities().get(entry.city_slug)
    return {
        **_entry_payload(entry),
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
    }


class PublicCatalogListView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(operation_id="catalog_list", responses={200: CatalogPageSerializer})
    def get(self, request: Request) -> Response:
        # Only dictionary values are accepted as filters (ADR-053 §7): the
        # catalogue is a public surface, and a filter that takes arbitrary text
        # is a scan somebody else pays for.
        city_slug = request.query_params.get("city", "")
        category = request.query_params.get("category", "")
        organization_type = settings.DEFAULT_ORGANIZATION_TYPE
        if city_slug and city_slug not in cities():
            city_slug = ""
        if category and category not in categories(organization_type):
            category = ""
        try:
            page = int(request.query_params.get("page", "1"))
        except ValueError:
            page = 1
        return Response(
            search_catalog(
                city_slug=city_slug,
                category=category,
                query=request.query_params.get("q", "")[:120],
                page=page,
            )
        )


class PublicCatalogDetailView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="catalog_profile",
        responses={200: CatalogProfileSerializer, 404: ProblemDetailsSerializer},
    )
    def get(self, request: Request, city_slug: str, slug: str) -> Response:
        return Response(resolve_catalog_profile(city_slug=city_slug, slug=slug))


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
