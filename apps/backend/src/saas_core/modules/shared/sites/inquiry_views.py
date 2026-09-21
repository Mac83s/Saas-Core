from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .domains import InvalidHostname, normalize_hostname
from .inquiries import (
    get_site_inquiry,
    inquiry_payload,
    list_site_inquiries,
    mark_site_inquiry_read,
    submit_site_inquiry,
    validate_inquiry_origin,
)
from .inquiry_serializers import (
    SiteInquiryAcceptedSerializer,
    SiteInquiryListQuerySerializer,
    SiteInquiryListSerializer,
    SiteInquirySerializer,
    SiteInquirySubmitSerializer,
)

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class InquiryPayloadTooLarge(APIException):
    status_code = 413
    default_code = "site_inquiry_payload_too_large"
    default_detail = "Formularz jest zbyt duży."


class InquiryClientThrottle(SimpleRateThrottle):
    scope = "site_inquiry_client"
    rate = "6/min"

    def get_cache_key(self, request: Request, view: Any) -> str:
        # No raw visitor address is retained in the throttle key.
        digest = hashlib.sha256(self.get_ident(request).encode()).hexdigest()
        return f"site-inquiry-client:{digest}"


class InquiryHostThrottle(SimpleRateThrottle):
    scope = "site_inquiry_host"
    rate = "100/hour"

    def get_cache_key(self, request: Request, view: Any) -> str:
        try:
            hostname = normalize_hostname(request.META.get("HTTP_HOST", ""), allow_port=True)
        except InvalidHostname:
            hostname = "invalid-host"
        digest = hashlib.sha256(hostname.encode()).hexdigest()
        return f"site-inquiry-host:{digest}"


class PublicSiteInquiryView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [InquiryClientThrottle, InquiryHostThrottle]

    @extend_schema(
        operation_id="public_site_inquiry_submit",
        tags=["public-sites"],
        parameters=[IDEMPOTENCY],
        request=SiteInquirySubmitSerializer,
        responses={
            200: SiteInquiryAcceptedSerializer,
            201: SiteInquiryAcceptedSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            413: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        host = str(request.META.get("HTTP_HOST", ""))
        origin = request.headers.get("Origin", "")
        validate_inquiry_origin(host=host, origin=origin)
        if len(request.body) > 65_536:
            raise InquiryPayloadTooLarge
        serializer = SiteInquirySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry, created = submit_site_inquiry(
            host=host,
            origin=origin,
            payload=serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response({"accepted": True, "reference": inquiry.id}, status=201 if created else 200)


class SiteInquiryListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_inquiry_list",
        tags=["sites"],
        parameters=[SiteInquiryListQuerySerializer],
        responses={
            200: SiteInquiryListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = SiteInquiryListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(list_site_inquiries(site_id=site_id, **query.validated_data))


class SiteInquiryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_inquiry_retrieve",
        tags=["sites"],
        responses={
            200: SiteInquirySerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, inquiry_id: UUID) -> Response:
        return Response(inquiry_payload(get_site_inquiry(inquiry_id=inquiry_id)))


@method_decorator(csrf_protect, name="dispatch")
class SiteInquiryReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_inquiry_mark_read",
        tags=["sites"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={
            200: SiteInquirySerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, inquiry_id: UUID) -> Response:
        return Response(
            inquiry_payload(
                mark_site_inquiry_read(
                    inquiry_id=inquiry_id,
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                )
            )
        )
