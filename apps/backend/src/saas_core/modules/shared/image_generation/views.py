from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .serializers import (
    ImageGenerationJobSerializer,
    ImageGenerationOfferSerializer,
    ImageGenerationRequestSerializer,
)
from .services import read_job, read_offer, request_generation

NO_STORE = {"Cache-Control": "private, no-store"}
IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia zlecenia w zakresie organizacji i użytkownika.",
)


class ImageGenerationOfferView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="image_generation_offer",
        tags=["image-generation"],
        responses={200: ImageGenerationOfferSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(read_offer(), headers=NO_STORE)


class ImageGenerationJobListView(APIView):
    permission_classes = [IsAuthenticated]

    @method_decorator(csrf_protect)
    @extend_schema(
        operation_id="image_generation_jobs_create",
        tags=["image-generation"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=ImageGenerationRequestSerializer,
        responses={
            200: ImageGenerationJobSerializer,
            202: ImageGenerationJobSerializer,
            **{code: ProblemDetailsSerializer for code in (400, 402, 403, 409, 429, 503)},
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ImageGenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job, created = request_generation(
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            ImageGenerationJobSerializer(job).data,
            status=202 if created else 200,
            headers=NO_STORE,
        )


class ImageGenerationJobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="image_generation_jobs_retrieve",
        tags=["image-generation"],
        responses={
            200: ImageGenerationJobSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, job_id: UUID) -> Response:
        return Response(
            ImageGenerationJobSerializer(read_job(job_id=job_id)).data, headers=NO_STORE
        )
