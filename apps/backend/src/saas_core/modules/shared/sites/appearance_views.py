from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .appearance import get_site_appearance, save_site_appearance, validate_appearance


class SiteAppearanceSerializer(serializers.Serializer[dict[str, Any]]):
    site_id = serializers.UUIDField()
    version = serializers.IntegerField()
    appearance = serializers.DictField()


class SiteAppearanceSaveSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(min_value=0)
    appearance = serializers.DictField()

    def validate_appearance(self, value: dict[str, Any]) -> dict[str, Any]:
        return validate_appearance(value)


@method_decorator(csrf_protect, name="dispatch")
class SiteAppearanceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_appearance_get",
        tags=["sites"],
        responses={
            200: SiteAppearanceSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        return Response(get_site_appearance(site_id=site_id))

    @extend_schema(
        operation_id="sites_appearance_save",
        tags=["sites"],
        request=SiteAppearanceSaveSerializer,
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
        responses={
            200: SiteAppearanceSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, site_id: UUID) -> Response:
        serializer = SiteAppearanceSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            save_site_appearance(
                site_id=site_id,
                **serializer.validated_data,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        )
