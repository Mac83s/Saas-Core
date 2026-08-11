from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .models import Page, PageBlock, Site
from .serializers import (
    CursorQuerySerializer,
    DraftSaveSerializer,
    PageCreateSerializer,
    PageDraftSerializer,
    PageListSerializer,
    PageSummarySerializer,
    SiteCreateSerializer,
    SiteListSerializer,
    SiteSummarySerializer,
)
from .services import create_page, create_site, get_draft, list_pages, list_sites, save_draft

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia mutacji w zakresie organizacji i użytkownika.",
)
CURSOR_PARAMETER = OpenApiParameter(
    name="cursor",
    type=UUID,
    location=OpenApiParameter.QUERY,
    required=False,
)
LIMIT_PARAMETER = OpenApiParameter(
    name="limit",
    type=int,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Liczba elementów od 1 do 100; domyślnie 50.",
)


@method_decorator(csrf_protect, name="dispatch")
class SiteListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_list",
        tags=["sites"],
        parameters=[CURSOR_PARAMETER, LIMIT_PARAMETER],
        responses={
            200: SiteListSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = CursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items, next_cursor = list_sites(
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response(
            {
                "items": [_site_summary(site) for site in items],
                "next_cursor": next_cursor,
            }
        )

    @extend_schema(
        operation_id="sites_create",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=SiteCreateSerializer,
        responses={
            200: SiteSummarySerializer,
            201: SiteSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = SiteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_site(
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _site_summary(result.value),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class PageListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_pages_list",
        tags=["sites"],
        parameters=[CURSOR_PARAMETER, LIMIT_PARAMETER],
        responses={
            200: PageListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = CursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items, next_cursor = list_pages(
            site_id=site_id,
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response(
            {
                "items": [_page_summary(page) for page in items],
                "next_cursor": next_cursor,
            }
        )

    @extend_schema(
        operation_id="sites_pages_create",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=PageCreateSerializer,
        responses={
            200: PageSummarySerializer,
            201: PageSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        serializer = PageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_page(
            site_id=site_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _page_summary(result.value),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class PageDraftView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_draft_retrieve",
        tags=["sites"],
        responses={
            200: PageDraftSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, page_id: UUID) -> Response:
        return Response(_draft_summary(page_id))

    @extend_schema(
        operation_id="sites_page_draft_save",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=DraftSaveSerializer,
        responses={
            200: PageDraftSerializer,
            201: PageDraftSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID) -> Response:
        serializer = DraftSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_draft(
            page_id=page_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _draft_summary(page_id),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


def _site_summary(site: Site) -> dict[str, Any]:
    return {
        "id": site.id,
        "name": site.name,
        "slug": site.slug,
        "default_locale": site.default_locale,
        "current_publication_id": site.current_publication_id,
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }


def _page_summary(page: Page) -> dict[str, Any]:
    draft = page.current_draft
    return {
        "id": page.id,
        "site_id": page.site_id,
        "name": page.name,
        "key": page.key,
        "version": page.version,
        "current_draft_id": page.current_draft_id,
        "current_draft_hash": draft.content_hash if draft is not None else None,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }


def _draft_summary(page_id: UUID) -> dict[str, Any]:
    draft = get_draft(page_id=page_id)
    return {
        "page_id": draft.page.id,
        "version": draft.page.version,
        "draft_id": draft.version.id if draft.version is not None else None,
        "content_hash": draft.version.content_hash if draft.version is not None else None,
        "created_at": draft.version.created_at if draft.version is not None else None,
        "blocks": [_block_summary(block) for block in draft.blocks],
    }


def _block_summary(block: PageBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "position": block.position,
        "block_type": block.block_type,
        "schema_version": block.schema_version,
        "data": block.data,
    }
