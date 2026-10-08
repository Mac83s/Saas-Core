"""`GET /api/v1/public/content/…` — the platform's published content for the
product's own pages (ADR-079 pkt 31).

Called by the product's pages on the server. Technically public — it answers
only what is published — and no product of its own: no CORS, no keys, no
promise to strangers. It takes **no host, site or tenant**: it always reads
the one platform workspace of the deployment (`content_reads`). The host gate
lets it answer on the platform's own hosts only (`http/hosts.py`): it is not
on the list a company's site is read through.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotFound
from django.views import View
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .content_read_serializers import (
    PublicContentEntryAnswerSerializer,
    PublicContentEntryQuerySerializer,
    PublicContentListAnswerSerializer,
    PublicContentListQuerySerializer,
    PublicContentLocaleQuerySerializer,
    PublicContentSitemapSerializer,
    PublicContentTermsSerializer,
    PublicContentTypeSerializer,
)
from .content_reads import (
    read_entries,
    read_entry,
    read_sitemap,
    read_terms,
    read_types,
    serve_content_media,
)

TAG = "public-content"
_PUBLISHED_ONLY = (
    " Reads the deployment's platform workspace and nothing else; takes no host, site or "
    "tenant. Only what is published: a draft, a withdrawn entry, a switched-off type and "
    "an address nobody has all answer the same 404."
)


class _PublicContentView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]


def _query(serializer: type[Any], request: Request) -> dict[str, Any]:
    parsed = serializer(data=request.query_params)
    parsed.is_valid(raise_exception=True)
    return dict(parsed.validated_data)


class PublicContentTypesView(_PublicContentView):
    @extend_schema(
        operation_id="public_content_types_list",
        summary="The platform's content types that have something published",
        description="Each type with its name and the name of its section per language it has "
        "a listed entry in. A type with nothing listed is not here." + _PUBLISHED_ONLY,
        tags=[TAG],
        responses={200: PublicContentTypeSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        try:
            return Response(read_types())
        except NotFound:
            # A deployment without a publisher has no types; that is no error.
            return Response([])


class PublicContentTermsView(_PublicContentView):
    @extend_schema(
        operation_id="public_content_terms_retrieve",
        summary="The terms of a content type in one language, with their counts",
        description="Counted and named from published entries that ask to be indexed, and "
        "from nothing else: a term only a draft or a hidden entry carries does not exist "
        "here." + _PUBLISHED_ONLY,
        tags=[TAG],
        parameters=[PublicContentLocaleQuerySerializer],
        responses={
            200: PublicContentTermsSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, type_key: str) -> Response:
        query = _query(PublicContentLocaleQuerySerializer, request)
        return Response(read_terms(type_key=type_key, locale=query["locale"]))


class PublicContentEntriesView(_PublicContentView):
    @extend_schema(
        operation_id="public_content_entries_list",
        summary="A page of a content type's published entries in one language",
        description="Newest first; all of the type, or those under one term (`taxonomy` and "
        "`term`). Entries that ask not to be indexed are on no list. `list.indexable` is "
        "the core's rule for thin term lists; the product applies it." + _PUBLISHED_ONLY,
        tags=[TAG],
        parameters=[PublicContentListQuerySerializer],
        responses={
            200: PublicContentListAnswerSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, type_key: str) -> Response:
        query = _query(PublicContentListQuerySerializer, request)
        return Response({
            "list": read_entries(
                type_key=type_key,
                locale=query["locale"],
                page=query["page"],
                page_size=query.get("page_size"),
                taxonomy=query["taxonomy"],
                term=query["term"],
            ),
            "moved": None,
        })


class PublicContentEntryView(_PublicContentView):
    @extend_schema(
        operation_id="public_content_entry_retrieve",
        summary="A published entry by type, language and slug",
        description="The entry as its current publication froze it: title, body as blocks, "
        "terms, its other language versions as (language, slug), and the facts the block "
        "renderers need beside the blocks. `moved` instead of `entry` when the address "
        "answers elsewhere now — the product answers one 308 from it. With `canonical_url` "
        "the entry's own JSON-LD nodes come too." + _PUBLISHED_ONLY,
        tags=[TAG],
        parameters=[
            OpenApiParameter(
                name="locale",
                type=str,
                location=OpenApiParameter.PATH,
                description="The entry's language: a two-letter code.",
            ),
            PublicContentEntryQuerySerializer,
        ],
        responses={
            200: PublicContentEntryAnswerSerializer,
            400: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, type_key: str, locale: str, slug: str) -> Response:
        query = _query(PublicContentEntryQuerySerializer, request)
        return Response(
            read_entry(
                type_key=type_key,
                locale=locale,
                slug=slug,
                canonical_url=query["canonical_url"] or None,
            )
        )


class PublicContentSitemapView(_PublicContentView):
    @extend_schema(
        operation_id="public_content_sitemap_retrieve",
        summary="Everything of the platform's content a sitemap lists, as address parts",
        description="Listed entries by group of language versions, each type's list per "
        "language, and the lists of terms worth indexing, each with when it last changed. "
        "The product writes the addresses from its own table." + _PUBLISHED_ONLY,
        tags=[TAG],
        responses={200: PublicContentSitemapSerializer},
    )
    def get(self, request: Request) -> Response:
        try:
            return Response(read_sitemap())
        except NotFound:
            return Response({"entries": [], "lists": [], "terms": []})


class PublicContentMediaView(View):
    """Plain Django, like the media of a company's site: the bytes are the
    response, and there is no renderer to negotiate."""

    def get(self, request: HttpRequest, asset_id: UUID, variant: str = "") -> HttpResponse:
        try:
            return serve_content_media(asset_id=asset_id, variant=variant)
        except (NotFound, Http404):
            # One answer for every refusal: also where the row says a picture
            # is ready and its bytes are not in storage (`media_response`).
            return HttpResponseNotFound()
