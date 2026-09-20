from typing import Any

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .template_media import materialize_template_photo


class TemplatePhotoSerializer(serializers.Serializer[dict[str, Any]]):
    asset_id = serializers.UUIDField()


@method_decorator(csrf_protect, name="dispatch")
class TemplatePhotoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_template_photo_materialize",
        tags=["sites"],
        request=None,
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
        responses={
            200: TemplatePhotoSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, photo_id: str) -> Response:
        asset_id = materialize_template_photo(
            photo_id=photo_id, idempotency_key=request.headers.get("Idempotency-Key", "")
        )
        return Response({"asset_id": asset_id})
