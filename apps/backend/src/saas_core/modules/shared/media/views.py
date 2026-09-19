from __future__ import annotations

from typing import Any
from uuid import UUID

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .models import MediaAsset
from .serializers import (
    MediaAssetSerializer,
    MediaDeletionSerializer,
    MediaUploadCreateSerializer,
    MediaUploadSerializer,
)
from .services import (
    complete_media_upload,
    initiate_media_upload,
    list_media_assets,
    read_media_preview,
    tombstone_media_asset,
)

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia inicjowania uploadu.",
)
DELETE_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia tombstone i cleanupu assetu.",
)


class MediaCursorQuerySerializer(serializers.Serializer[dict[str, Any]]):
    cursor = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class MediaAssetListSerializer(serializers.Serializer[dict[str, Any]]):
    items = MediaAssetSerializer(many=True)
    next_cursor = serializers.UUIDField(allow_null=True)


class MediaAssetListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="media_assets_list",
        tags=["media"],
        parameters=[
            OpenApiParameter("cursor", UUID, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: MediaAssetListSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = MediaCursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        assets, next_cursor = list_media_assets(
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response({
            "items": [_asset_payload(asset) for asset in assets],
            "next_cursor": next_cursor,
        })


class MediaAssetPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="media_asset_preview",
        tags=["media"],
        responses={
            (200, "image/webp"): OpenApiTypes.BINARY,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            503: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, asset_id: UUID) -> HttpResponse:
        return HttpResponse(read_media_preview(asset_id=asset_id), content_type="image/webp")

    def finalize_response(self, request: Request, response: Any, *args: Any, **kwargs: Any) -> Any:
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


@method_decorator(csrf_protect, name="dispatch")
class MediaAssetDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="media_assets_delete",
        tags=["media"],
        parameters=[DELETE_IDEMPOTENCY_PARAMETER],
        responses={
            202: MediaDeletionSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def delete(self, request: Request, asset_id: UUID) -> Response:
        deletion = tombstone_media_asset(
            asset_id=asset_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _deletion_payload(deletion.asset),
            status=status.HTTP_202_ACCEPTED,
        )


@method_decorator(csrf_protect, name="dispatch")
class MediaUploadCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="media_uploads_create",
        tags=["media"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=MediaUploadCreateSerializer,
        responses={
            200: MediaUploadSerializer,
            201: MediaUploadSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = MediaUploadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        intent = initiate_media_upload(
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            {
                "asset": _asset_payload(intent.asset),
                "upload_url": intent.upload.url,
                "upload_headers": intent.upload.headers,
            },
            status=(status.HTTP_201_CREATED if intent.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class MediaUploadCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="media_uploads_complete",
        tags=["media"],
        request=None,
        responses={
            200: MediaAssetSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, asset_id: UUID) -> Response:
        del request
        return Response(_asset_payload(complete_media_upload(asset_id=asset_id)))


def _asset_payload(asset: MediaAsset) -> dict[str, object]:
    return {
        "id": asset.id,
        "original_filename": asset.original_filename,
        "declared_mime": asset.declared_mime,
        "expected_size": asset.expected_size,
        "actual_size": asset.actual_size,
        "state": asset.state,
        "upload_expires_at": asset.upload_expires_at,
        "created_at": asset.created_at,
    }


def _deletion_payload(asset: MediaAsset) -> dict[str, object]:
    return {
        "id": asset.id,
        "deleted_at": asset.deleted_at,
        "cleanup_completed_at": asset.cleanup_completed_at,
    }
