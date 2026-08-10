from typing import cast

from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .authorization import authorize
from .models import Membership, Organization
from .permissions import ORGANIZATION_READ
from .serializers import (
    ActiveOrganizationResultSerializer,
    ActiveOrganizationSerializer,
    OrganizationArchivedSerializer,
    OrganizationCreateSerializer,
    OrganizationSummarySerializer,
    OrganizationUpdateSerializer,
)
from .services import (
    OrganizationAccess,
    archive_current_organization,
    create_organization,
    list_organizations,
    set_active_organization,
    update_current_organization,
)


class ProtectedOrganizationView(APIView):
    permission_classes = [IsAuthenticated]


@method_decorator(csrf_protect, name="dispatch")
class OrganizationListCreateView(ProtectedOrganizationView):
    @extend_schema(
        responses={
            200: OrganizationSummarySerializer(many=True),
            403: ProblemDetailsSerializer,
        }
    )
    def get(self, request: Request) -> Response:
        accesses = list_organizations(request=cast(HttpRequest, request))
        return Response([_organization_summary(access) for access in accesses])

    @extend_schema(
        request=OrganizationCreateSerializer,
        responses={
            201: OrganizationSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = OrganizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access = create_organization(
            request=cast(HttpRequest, request),
            **serializer.validated_data,
        )
        return Response(
            _organization_summary(access),
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class CurrentOrganizationView(ProtectedOrganizationView):
    @extend_schema(
        responses={
            200: OrganizationSummarySerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        }
    )
    def get(self, _request: Request) -> Response:
        context = authorize(ORGANIZATION_READ)
        organization = Organization.objects.get(pk=context.organization_id)
        membership = Membership.objects.select_related("role").get(pk=context.membership_id)
        return Response(
            _organization_summary(OrganizationAccess(organization, membership, active=True))
        )

    @extend_schema(
        request=OrganizationUpdateSerializer,
        responses={
            200: OrganizationSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def patch(self, request: Request) -> Response:
        serializer = OrganizationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access = update_current_organization(changes=serializer.validated_data)
        return Response(_organization_summary(access))

    @extend_schema(
        request=None,
        responses={
            200: OrganizationArchivedSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def delete(self, request: Request) -> Response:
        archive_current_organization(request=cast(HttpRequest, request))
        return Response({"status": "archived"})


@method_decorator(csrf_protect, name="dispatch")
class ActiveOrganizationView(ProtectedOrganizationView):
    @extend_schema(
        request=ActiveOrganizationSerializer,
        responses={
            200: ActiveOrganizationResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request) -> Response:
        serializer = ActiveOrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access = set_active_organization(
            request=cast(HttpRequest, request),
            **serializer.validated_data,
        )
        return Response({"organization": _organization_summary(access)})


def _organization_summary(access: OrganizationAccess) -> dict[str, object]:
    organization = access.organization
    membership = access.membership
    return {
        "id": str(organization.id),
        "name": organization.name,
        "slug": organization.slug,
        "workspace_kind": organization.workspace_kind,
        "status": organization.status,
        "default_locale": organization.default_locale,
        "timezone": organization.timezone,
        "currency": organization.currency,
        "version": organization.version,
        "membership_status": membership.status,
        "role": membership.role.key,
        "active": access.active,
    }
