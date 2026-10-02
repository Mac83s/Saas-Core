from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .language_version_serializers import (
    LocaleBodyCopySerializer,
    LocaleBodyRebaseSerializer,
    LocaleBodyRestoreSerializer,
    LocaleBodySaveSerializer,
    LocaleBodySerializer,
    LocaleBodyVersionListSerializer,
    LocaleBodyVersionPreviewSerializer,
    TranslationOverviewQuerySerializer,
    TranslationOverviewSerializer,
)
from .language_versions import (
    LocaleBody,
    copy_source_into_locale_body,
    get_locale_body,
    list_locale_body_versions,
    locale_body_version_blocks,
    rebase_locale_body,
    restore_locale_body_version,
    save_locale_body,
    site_translation_overview,
)
from .models import PageLocaleVersion
from .views import IDEMPOTENCY_PARAMETER

PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}


def _body(body: LocaleBody) -> dict[str, Any]:
    return {
        "page_id": body.page.id,
        "locale": body.translation.locale,
        "source_version_id": body.source_version.id,
        "source_version": body.source_version.number,
        "outdated": body.outdated,
        "body_version": body.translation.body_version,
        "version": body.version.number if body.version is not None else None,
        "untranslated": body.untranslated,
        "units": [
            {
                "key": state.unit.key,
                "kind": state.unit.kind,
                "source_text": state.unit.text,
                "text": state.text,
                "origin": state.origin,
                "translated": state.translated,
                "suggestion": state.suggestion,
                "data_class": state.unit.data_class,
                "placeholder": state.unit.placeholder,
                "max_length": state.unit.max_length,
                "required_text": state.unit.required,
            }
            for state in body.units
        ],
    }


def _version(version: PageLocaleVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "number": version.number,
        "source_version_id": version.source_version_id,
        "source_version": version.source_version.number,
        "origin": version.origin,
        "origin_ref": version.origin_ref,
        "created_at": version.created_at,
    }


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_retrieve",
        summary="Read a page body in another language",
        description="Every text unit of the source version this language follows, with this "
        "language's text, who wrote it and what is still untranslated (ADR-070).",
        tags=["sites"],
        responses={200: LocaleBodySerializer, **PROBLEMS},
    )
    def get(self, _request: Request, page_id: UUID, locale: str) -> Response:
        return Response(_body(get_locale_body(page_id=page_id, locale=locale)))

    @extend_schema(
        operation_id="sites_page_locale_body_save",
        summary="Save text units of a page body in another language",
        description="Writes the named units as a person's text; structure comes from the "
        "source version. 400 `locale_unit_invalid` names every unit that does not fit as a "
        "field error `units.<key>` with its code (unknown_unit, required, too_long, "
        "token_missing, token_unexpected, token_malformed, token_nesting, token_empty, "
        "block_invalid). The page's own version does not move.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodySaveSerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def put(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodySaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_preview",
        summary="Check a save of text units without saving",
        description="The body as the save would leave it, or the same 400 and 409 the save "
        "would answer. Nothing is written.",
        tags=["sites"],
        request=LocaleBodySaveSerializer,
        responses={200: LocaleBodySerializer, **PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodySaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key="",
            preview=True,
        )
        return Response(_body(result.value))


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyCopyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_copy",
        summary="Start a manual translation from the source text",
        description="Fills every unit with no text yet with the source text. A copy stays "
        "untranslated until somebody changes it or saves it as it is.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodyCopySerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodyCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = copy_source_into_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class PageLocaleBodyVersionListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_versions_list",
        summary="History of a page body in another language",
        description="Every version of this language's body, newest first, with the source "
        "version it follows and how it came to be (save, copy, restore, rebase, a job).",
        tags=["sites"],
        responses={200: LocaleBodyVersionListSerializer, **PROBLEMS},
    )
    def get(self, _request: Request, page_id: UUID, locale: str) -> Response:
        versions = list_locale_body_versions(page_id=page_id, locale=locale)
        return Response({"items": [_version(version) for version in versions]})


class PageLocaleBodyVersionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_version_retrieve",
        summary="A past version of a page body in another language, as blocks",
        description="The blocks a visitor would have got from that version, assembled from "
        "the source version it is bound to; for a read-only preview.",
        tags=["sites"],
        responses={200: LocaleBodyVersionPreviewSerializer, **PROBLEMS},
    )
    def get(self, _request: Request, page_id: UUID, locale: str, version_id: UUID) -> Response:
        version, blocks = locale_body_version_blocks(
            page_id=page_id, locale=locale, version_id=version_id
        )
        return Response({"version": _version(version), "blocks": blocks})


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_version_restore",
        summary="Make a past version of a page body in another language current again",
        description="A new version with the old text and the old binding; a version bound to "
        "an older source must be moved onto the current one before it can be published.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodyRestoreSerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str, version_id: UUID) -> Response:
        serializer = LocaleBodyRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = restore_locale_body_version(
            page_id=page_id,
            locale=locale,
            version_id=version_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyRebaseView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_rebase",
        summary="Move a page body in another language onto the current source version",
        description="Unchanged source text keeps its translation wherever it moved, a sentence "
        "translated on another page of the site is reused, a changed unit starts "
        "untranslated with a person's old text as a suggestion. Already current: 200 and "
        "nothing changes.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodyRebaseSerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodyRebaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = rebase_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyRebasePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_rebase_preview",
        summary="See what moving onto the current source version would keep",
        description="The body as the move would leave it: carried, reused, untranslated and "
        "suggested units. Nothing is written.",
        tags=["sites"],
        extensions={"x-dry-run": True},
        request=LocaleBodyRebaseSerializer,
        responses={200: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodyRebaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = rebase_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key="",
            preview=True,
        )
        return Response(_body(result.value))


class SiteTranslationOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_translation_overview",
        summary="Every page or article of a site against every other language",
        description="Pages: missing, pending, outdated, untranslated or complete per language, "
        "with the untranslated count. Articles: published, draft or missing per language. "
        "Filter by language and state; paginated by cursor.",
        tags=["sites"],
        parameters=[TranslationOverviewQuerySerializer],
        responses={200: TranslationOverviewSerializer, **PROBLEMS},
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = TranslationOverviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, next_cursor, locales = site_translation_overview(
            site_id=site_id, **query.validated_data
        )
        return Response({
            "locales": list(locales),
            "items": [
                {
                    "kind": row.kind,
                    "id": row.id,
                    "title": row.title,
                    "cells": [
                        {
                            "locale": cell.locale,
                            "state": cell.state,
                            "untranslated": cell.untranslated,
                            "metadata_complete": cell.metadata_complete,
                        }
                        for cell in row.cells
                    ],
                }
                for row in rows
            ],
            "next_cursor": next_cursor,
        })
