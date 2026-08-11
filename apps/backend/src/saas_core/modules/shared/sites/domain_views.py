from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .domain_services import create_custom_domain, list_domains, mutate_domain
from .models import Domain
from .serializers import (
    DomainActionSerializer,
    DomainCreateSerializer,
    SiteDomainListSerializer,
    SiteDomainSerializer,
)

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
)


@method_decorator(csrf_protect, name="dispatch")
class SiteDomainListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_domains_list",
        tags=["domains"],
        responses={
            200: SiteDomainListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        del request
        return Response({
            "items": [
                _domain_payload(domain) for domain in list_domains(site_id=site_id)
            ]
        })

    @extend_schema(
        operation_id="sites_domains_create",
        tags=["domains"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=DomainCreateSerializer,
        responses={
            200: SiteDomainSerializer,
            201: SiteDomainSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        serializer = DomainCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_custom_domain(
            site_id=site_id,
            hostname=serializer.validated_data["hostname"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _domain_payload(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class SiteDomainActionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_domains_action",
        tags=["domains"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=DomainActionSerializer,
        responses={
            200: SiteDomainSerializer,
            202: SiteDomainSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, domain_id: UUID) -> Response:
        serializer = DomainActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        result = mutate_domain(
            domain_id=domain_id,
            action=action,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        response_status = status.HTTP_202_ACCEPTED if action == "verify" else status.HTTP_200_OK
        return Response(_domain_payload(result.value), status=response_status)


def _domain_payload(domain: Domain) -> dict[str, Any]:
    return {
        "id": domain.id,
        "site_id": domain.site_id,
        "hostname": domain.hostname,
        "kind": domain.kind,
        "status": domain.status,
        "tls_status": domain.tls_status,
        "is_canonical": domain.is_canonical,
        "verification_name": domain.verification_name,
        "verification_token": domain.verification_token,
        "dns_cname_target": settings.DOMAIN_DNS_CNAME_TARGET,
        "dns_expected_ipv4": list(settings.DOMAIN_DNS_EXPECTED_IPV4),
        "dns_expected_ipv6": list(settings.DOMAIN_DNS_EXPECTED_IPV6),
        "dns_error_code": domain.dns_error_code,
        "last_checked_at": domain.last_checked_at,
        "last_verified_at": domain.last_verified_at,
        "next_check_at": domain.next_check_at,
        "tls_last_requested_at": domain.tls_last_requested_at,
        "released_at": domain.released_at,
        "quarantine_until": domain.quarantine_until,
        "created_at": domain.created_at,
    }
