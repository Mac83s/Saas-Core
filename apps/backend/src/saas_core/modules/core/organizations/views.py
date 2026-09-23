from typing import cast
from uuid import UUID

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
from .context import context_from_membership
from .custom_roles import create_role, delete_role, list_roles, update_role
from .history import history_item, list_history
from .lifecycle import (
    accept_invitation,
    create_invitation,
    leave_organization,
    list_invitations,
    list_memberships,
    revoke_invitation,
    transfer_ownership,
    update_membership,
)
from .models import Invitation, InvitationStatus, Membership, Organization, Role
from .permissions import ORGANIZATION_READ
from .serializers import (
    ActiveOrganizationResultSerializer,
    ActiveOrganizationSerializer,
    HistoryPageSerializer,
    HistoryQuerySerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationSummarySerializer,
    LifecycleResultSerializer,
    MembershipSummarySerializer,
    MembershipUpdateSerializer,
    OrganizationArchivedSerializer,
    OrganizationCreateSerializer,
    OrganizationSummarySerializer,
    OrganizationUpdateSerializer,
    OwnershipTransferSerializer,
    RoleCatalogSerializer,
    RoleCreateSerializer,
    RoleSummarySerializer,
    RoleUpdateSerializer,
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


@method_decorator(csrf_protect, name="dispatch")
class InvitationListCreateView(ProtectedOrganizationView):
    @extend_schema(
        responses={
            200: InvitationSummarySerializer(many=True),
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        }
    )
    def get(self, _request: Request) -> Response:
        return Response([_invitation_summary(item) for item in list_invitations()])

    @extend_schema(
        request=InvitationCreateSerializer,
        responses={
            201: InvitationSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = create_invitation(
            request=cast(HttpRequest, request),
            email=serializer.validated_data["email"],
            role_key=serializer.validated_data["role"],
        )
        return Response(
            _invitation_summary(invitation),
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class InvitationRevokeView(ProtectedOrganizationView):
    @extend_schema(
        request=None,
        responses={
            200: InvitationSummarySerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def delete(self, request: Request, invitation_id: UUID) -> Response:
        invitation = revoke_invitation(
            request=cast(HttpRequest, request),
            invitation_id=invitation_id,
        )
        return Response(_invitation_summary(invitation))


@method_decorator(csrf_protect, name="dispatch")
class InvitationAcceptView(ProtectedOrganizationView):
    @extend_schema(
        request=InvitationAcceptSerializer,
        responses={
            200: MembershipSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = accept_invitation(
            request=cast(HttpRequest, request),
            **serializer.validated_data,
        )
        return Response(_membership_summary(membership))


class MembershipListView(ProtectedOrganizationView):
    @extend_schema(
        responses={
            200: MembershipSummarySerializer(many=True),
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        }
    )
    def get(self, _request: Request) -> Response:
        return Response([_membership_summary(item) for item in list_memberships()])


@method_decorator(csrf_protect, name="dispatch")
class MembershipUpdateView(ProtectedOrganizationView):
    @extend_schema(
        request=MembershipUpdateSerializer,
        responses={
            200: MembershipSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def patch(self, request: Request, membership_id: UUID) -> Response:
        serializer = MembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change = update_membership(
            request=cast(HttpRequest, request),
            membership_id=membership_id,
            role_key=serializer.validated_data.get("role"),
            membership_status=serializer.validated_data.get("status"),
        )
        return Response(_membership_summary(change.membership))


@method_decorator(csrf_protect, name="dispatch")
class MembershipLeaveView(ProtectedOrganizationView):
    @extend_schema(
        request=None,
        responses={
            200: LifecycleResultSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        leave_organization(request=cast(HttpRequest, request))
        return Response({"status": "left"})


@method_decorator(csrf_protect, name="dispatch")
class OwnershipTransferView(ProtectedOrganizationView):
    @extend_schema(
        request=OwnershipTransferSerializer,
        responses={
            200: LifecycleResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = OwnershipTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer_ownership(
            request=cast(HttpRequest, request),
            **serializer.validated_data,
        )
        return Response({"status": "transferred"})


def _organization_summary(access: OrganizationAccess) -> dict[str, object]:
    organization = access.organization
    membership = access.membership
    return {
        "id": str(organization.id),
        "name": organization.name,
        "slug": organization.slug,
        "workspace_kind": organization.workspace_kind,
        "organization_type": organization.organization_type,
        "status": organization.status,
        "default_locale": organization.default_locale,
        "timezone": organization.timezone,
        "currency": organization.currency,
        "version": organization.version,
        "membership_status": membership.status,
        "role": membership.role.key,
        "permissions": sorted(context_from_membership(membership).permissions),
        "active": access.active,
    }


def _invitation_summary(invitation: Invitation) -> dict[str, object]:
    effective_status = invitation.status
    if invitation.status == InvitationStatus.PENDING and not invitation.is_usable():
        effective_status = "expired"
    return {
        "id": str(invitation.id),
        "email": invitation.email,
        "role": invitation.role.key,
        "status": effective_status,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
    }


def _membership_summary(membership: Membership) -> dict[str, object]:
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": membership.user.email,
        "first_name": membership.user.first_name,
        "last_name": membership.user.last_name,
        "role": membership.role.key,
        "status": membership.status,
        "joined_at": membership.joined_at,
    }


def _role_summary(role: Role, limited: frozenset[str]) -> dict[str, object]:
    return {
        "key": role.key,
        "name": role.name,
        "scope": role.scope,
        "permissions": list(role.permissions),
        "limited": role.organization_id is None and role.key in limited,
        "version": role.version,
    }


@method_decorator(csrf_protect, name="dispatch")
class RoleListCreateView(ProtectedOrganizationView):
    """The roles an organization can hand out: its type's and its own (ADR-050)."""

    @extend_schema(responses={200: RoleCatalogSerializer, 403: ProblemDetailsSerializer})
    def get(self, _request: Request) -> Response:
        catalog = list_roles()
        return Response(
            {
                "roles": [_role_summary(role, catalog.limited) for role in catalog.roles],
                "grantable_permissions": list(catalog.grantable),
            }
        )

    @extend_schema(
        request=RoleCreateSerializer,
        responses={
            201: RoleSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = RoleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = create_role(request=cast(HttpRequest, request), **serializer.validated_data)
        return Response(_role_summary(role, frozenset()), status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class RoleDetailView(ProtectedOrganizationView):
    @extend_schema(
        request=RoleUpdateSerializer,
        responses={
            200: RoleSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def patch(self, request: Request, role_key: str) -> Response:
        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = update_role(
            request=cast(HttpRequest, request), key=role_key, **serializer.validated_data
        )
        return Response(_role_summary(role, frozenset()))

    @extend_schema(
        responses={
            204: None,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        }
    )
    def delete(self, request: Request, role_key: str) -> Response:
        delete_role(request=cast(HttpRequest, request), key=role_key)
        return Response(status=status.HTTP_204_NO_CONTENT)


class HistoryView(ProtectedOrganizationView):
    """The organization's history of changes, newest first (owner, admin)."""

    @extend_schema(
        parameters=[HistoryQuerySerializer],
        responses={200: HistoryPageSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        query = HistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = list_history(
            page=query.validated_data["page"],
            page_size=query.validated_data["page_size"],
            action=query.validated_data["action"],
        )
        return Response({
            "total": page.total,
            "page": query.validated_data["page"],
            "page_size": query.validated_data["page_size"],
            "actions": page.actions,
            "items": [history_item(entry) for entry in page.entries],
        })
