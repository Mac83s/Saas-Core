from __future__ import annotations

from typing import Any

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .domain_services import subdomain_availability
from .models import Site
from .onboarding import (
    SiteOnboardingState,
    complete_site_onboarding,
    get_site_onboarding,
    save_site_onboarding,
)
from .serializers import (
    SiteOnboardingSaveSerializer,
    SiteOnboardingSerializer,
    SiteSummarySerializer,
    SubdomainAvailabilityQuerySerializer,
    SubdomainAvailabilitySerializer,
)

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
)


class SubdomainAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sites_subdomain_availability"

    @extend_schema(
        operation_id="sites_subdomain_availability",
        tags=["sites"],
        parameters=[
            OpenApiParameter(
                name="label",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
            )
        ],
        responses={
            200: SubdomainAvailabilitySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            429: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = SubdomainAvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        result = subdomain_availability(query.validated_data["label"])
        return Response({
            "requested_label": result.requested_label,
            "normalized_label": result.normalized_label,
            "hostname": result.hostname,
            "available": result.available,
            "reason": result.reason,
            "suggestion": result.suggestion,
        })


@method_decorator(csrf_protect, name="dispatch")
class SiteOnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_onboarding_retrieve",
        tags=["sites"],
        responses={
            200: SiteOnboardingSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        del request
        return Response(_state_payload(get_site_onboarding()))

    @extend_schema(
        operation_id="sites_onboarding_save",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=SiteOnboardingSaveSerializer,
        responses={
            200: SiteOnboardingSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request) -> Response:
        serializer = SiteOnboardingSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_site_onboarding(
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(_state_payload(result))


@method_decorator(csrf_protect, name="dispatch")
class SiteOnboardingCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_onboarding_complete",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=None,
        responses={
            200: SiteSummarySerializer,
            201: SiteSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        result = complete_site_onboarding(
            idempotency_key=request.headers.get("Idempotency-Key", "")
        )
        return Response(
            _site_payload(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


def _state_payload(state: SiteOnboardingState) -> dict[str, Any]:
    return {
        "id": state.id,
        "version": state.version,
        "step": state.step,
        "name": state.name,
        "subdomain_label": state.subdomain_label,
        "default_locale": state.default_locale,
        "platform_domain": state.platform_domain,
        "hostname": state.hostname,
        "site_id": state.site_id,
        "updated_at": state.updated_at,
    }


def _site_payload(site: Site) -> dict[str, Any]:
    return {
        "id": site.id,
        "name": site.name,
        "slug": site.slug,
        "default_locale": site.default_locale,
        "current_publication_id": site.current_publication_id,
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }
