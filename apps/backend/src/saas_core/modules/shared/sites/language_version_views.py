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
    LocaleBodyRestoreSerializer,
    LocaleBodySaveSerializer,
    LocaleBodySerializer,
    LocaleBodyVersionListSerializer,
    LocaleBodyVersionPreviewSerializer,
)
from .language_versions import (
    LocaleBody,
    copy_source_into_locale_body,
    get_locale_body,
    list_locale_body_versions,
    locale_body_version_blocks,
    restore_locale_body_version,
    save_locale_body,
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
        "source version. 422 `locale_unit_invalid` names every unit that does not fit "
        "(`errors[].field` = `units.<key>`, `errors[].code`). The page's own version does not "
        "move.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodySaveSerializer,
        responses={
            200: LocaleBodySerializer,
            201: LocaleBodySerializer,
            422: ProblemDetailsSerializer,
            **PROBLEMS,
        },
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
        description="The body as the save would leave it, or the same 409 and 422 the save "
        "would answer. Nothing is written.",
        tags=["sites"],
        request=LocaleBodySaveSerializer,
        responses={200: LocaleBodySerializer, 422: ProblemDetailsSerializer, **PROBLEMS},
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
