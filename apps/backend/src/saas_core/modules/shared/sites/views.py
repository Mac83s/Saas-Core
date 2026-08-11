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

from .localization import LocaleResolution, SiteLocalizationReport
from .models import Page, PageBlock, PageTranslation, Site
from .serializers import (
    CursorQuerySerializer,
    DraftSaveSerializer,
    PageCreateSerializer,
    PageDraftSerializer,
    PageListSerializer,
    PageSummarySerializer,
    PageTranslationListSerializer,
    PageTranslationSaveSerializer,
    PageTranslationSerializer,
    SiteCreateSerializer,
    SiteListSerializer,
    SiteLocalizationReportSerializer,
    SiteSummarySerializer,
)
from .services import (
    create_page,
    create_site,
    get_draft,
    get_site_localization_report,
    list_page_translations,
    list_pages,
    list_sites,
    save_draft,
    save_page_translation,
)

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


class PageTranslationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_translations_list",
        tags=["sites"],
        responses={
            200: PageTranslationListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, page_id: UUID) -> Response:
        translations = list_page_translations(page_id=page_id)
        return Response(
            {
                "page_id": translations.page.id,
                "default_locale": translations.page.site.default_locale,
                "supported_locales": list(translations.supported_locales),
                "items": [
                    _translation_summary(translation)
                    for translation in translations.translations
                ],
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class PageTranslationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_translation_save",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=PageTranslationSaveSerializer,
        responses={
            200: PageTranslationSerializer,
            201: PageTranslationSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = PageTranslationSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_page_translation(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _translation_summary(result.value),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


class SiteLocalizationReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_localization_report_retrieve",
        tags=["sites"],
        responses={
            200: SiteLocalizationReportSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, site_id: UUID) -> Response:
        return Response(
            _localization_report(get_site_localization_report(site_id=site_id))
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


def _translation_summary(translation: PageTranslation) -> dict[str, Any]:
    return {
        "id": translation.id,
        "page_id": translation.page_id,
        "site_id": translation.site_id,
        "locale": translation.locale,
        "slug": translation.slug,
        "title": translation.title,
        "description": translation.description,
        "social_title": translation.social_title,
        "social_description": translation.social_description,
        "allow_title_fallback": translation.allow_title_fallback,
        "allow_description_fallback": translation.allow_description_fallback,
        "allow_social_title_fallback": translation.allow_social_title_fallback,
        "allow_social_description_fallback": (
            translation.allow_social_description_fallback
        ),
        "version": translation.version,
        "slug_locked": translation.slug_locked_at is not None,
        "created_at": translation.created_at,
        "updated_at": translation.updated_at,
    }


def _localization_report(report: SiteLocalizationReport) -> dict[str, Any]:
    return {
        "site_id": report.site.id,
        "default_locale": report.site.default_locale,
        "supported_locales": list(report.supported_locales),
        "ready_to_publish": report.ready_to_publish,
        "pages": [
            {
                "page_id": page.page.id,
                "page_key": page.page.key,
                "page_name": page.page.name,
                "locales": [_locale_resolution(locale) for locale in page.locales],
                "hreflang": page.hreflang,
                "x_default": page.x_default,
            }
            for page in report.pages
        ],
    }


def _locale_resolution(locale: LocaleResolution) -> dict[str, Any]:
    return {
        "locale": locale.locale,
        "translation_id": locale.translation_id,
        "version": locale.version,
        "slug": locale.slug,
        "path": locale.path,
        "canonical_path": locale.canonical_path,
        "title": locale.title,
        "description": locale.description,
        "social_title": locale.social_title,
        "social_description": locale.social_description,
        "fallback_fields": list(locale.fallback_fields),
        "missing_fields": list(locale.missing_fields),
        "complete": locale.complete,
        "slug_locked": locale.slug_locked,
    }
