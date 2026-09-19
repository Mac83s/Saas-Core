from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import HttpRequest
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.identity.sessions import rotate_managed_session

from .audit import record_audit
from .authorization import authorize
from .context import set_local_organization_id
from .middleware import ACTIVE_ORGANIZATION_SESSION_KEY
from .models import (
    BillingProfile,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
    OrganizationStatus,
    Role,
    WorkspaceKind,
)
from .permissions import ORGANIZATION_ARCHIVE, SETTINGS_MANAGE
from .platform_workspace import PlatformWorkspaceForbidden
from .pre_tenant import PRE_TENANT_DB


class OrganizationNotFound(NotFound):
    default_detail = "Organizacja nie istnieje."
    default_code = "organization_not_found"


class OrganizationSlugConflict(APIException):
    status_code = 409
    default_detail = "Ten slug organizacji jest już zajęty."
    default_code = "organization_slug_conflict"


class OrganizationVersionConflict(APIException):
    status_code = 409
    default_detail = "Organizacja została zmieniona. Odśwież dane i spróbuj ponownie."
    default_code = "organization_version_conflict"


@dataclass(frozen=True, slots=True)
class OrganizationAccess:
    organization: Organization
    membership: Membership
    active: bool


def list_organizations(*, request: HttpRequest) -> list[OrganizationAccess]:
    user = cast(User, request.user)
    active_id = request.session.get(ACTIVE_ORGANIZATION_SESSION_KEY)
    # ADR-041: the switcher asks which companies this account belongs to, which
    # is the question that has to be answered before a tenant exists.
    memberships = Membership.objects.using(PRE_TENANT_DB).select_related(
        "organization", "role"
    ).filter(
        user=user,
        status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED],
        organization__status__in=[
            OrganizationStatus.ONBOARDING,
            OrganizationStatus.ACTIVE,
            OrganizationStatus.SUSPENDED,
        ],
    )
    accesses = [
        OrganizationAccess(
            organization=membership.organization,
            membership=membership,
            active=(
                str(membership.organization_id) == active_id
                and membership.status == MembershipStatus.ACTIVE
                and membership.organization.status
                in {OrganizationStatus.ONBOARDING, OrganizationStatus.ACTIVE}
            ),
        )
        for membership in memberships
    ]
    if active_id and not any(access.active for access in accesses):
        request.session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
    return accesses


@transaction.atomic
def create_organization(
    *,
    request: HttpRequest,
    name: str,
    slug: str,
    workspace_kind: str,
    default_locale: str,
    timezone: str,
    currency: str,
    organization_type: str,
) -> OrganizationAccess:
    user = cast(User, request.user)
    if workspace_kind == WorkspaceKind.PLATFORM:
        # The serializer does not offer it either; this is the second lock, on
        # the service every channel goes through.
        raise PlatformWorkspaceForbidden
    organization = Organization(
        name=name,
        slug=slug,
        workspace_kind=workspace_kind,
        organization_type=organization_type,
        default_locale=default_locale,
        timezone=timezone,
        currency=currency,
    )
    _validate_model(organization, validate_uniqueness=False)
    # The identifier exists before the row does, so the tenant can be set first
    # and everything below — the organization, its billing profile, the owner's
    # membership, the audit entry — is written under the policy that guards it.
    set_local_organization_id(organization.id)
    try:
        organization.save()
    except IntegrityError as error:
        raise OrganizationSlugConflict from error
    BillingProfile.objects.create(organization=organization)
    owner_role = Role.objects.select_for_update().get(key="owner", organization=None)
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=owner_role,
    )
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.ORGANIZATION_CREATED,
        actor=user,
        target_type="organization",
        target_id=organization.id,
    )
    request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(organization.id)
    rotate_managed_session(request=request)
    return OrganizationAccess(organization, membership, active=True)


@transaction.atomic
def set_active_organization(
    *,
    request: HttpRequest,
    organization_id: UUID,
) -> OrganizationAccess:
    user = cast(User, request.user)
    membership_id = (
        Membership.objects.using(PRE_TENANT_DB)
        .filter(
            organization_id=organization_id,
            user=user,
            status=MembershipStatus.ACTIVE,
            organization__status__in=[
                OrganizationStatus.ONBOARDING,
                OrganizationStatus.ACTIVE,
            ],
        )
        .filter(Q(role__organization__isnull=True) | Q(role__organization_id=F("organization_id")))
        .values_list("id", flat=True)
        .first()
    )
    if membership_id is None:
        raise OrganizationNotFound
    set_local_organization_id(organization_id)
    membership = (
        Membership.objects.select_for_update()
        .select_related("organization", "role")
        .filter(
            pk=membership_id,
            organization_id=organization_id,
            user=user,
            status=MembershipStatus.ACTIVE,
            organization__status__in=[
                OrganizationStatus.ONBOARDING,
                OrganizationStatus.ACTIVE,
            ],
        )
        .filter(Q(role__organization__isnull=True) | Q(role__organization_id=F("organization_id")))
        .first()
    )
    if membership is None:
        raise OrganizationNotFound
    request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(membership.organization_id)
    rotate_managed_session(request=request)
    return OrganizationAccess(membership.organization, membership, active=True)


@transaction.atomic
def update_current_organization(*, changes: dict[str, Any]) -> OrganizationAccess:
    context = authorize(SETTINGS_MANAGE)
    expected_version = changes.pop("version")
    changed_fields = sorted(changes)
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    if organization.version != expected_version:
        raise OrganizationVersionConflict
    for field, value in changes.items():
        setattr(organization, field, value)
    organization.version += 1
    _validate_model(organization)
    organization.save()
    membership = Membership.objects.select_related("role").get(pk=context.membership_id)
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.ORGANIZATION_UPDATED,
        actor=membership.user,
        target_type="organization",
        target_id=organization.id,
        metadata={"fields": changed_fields},
    )
    return OrganizationAccess(organization, membership, active=True)


@transaction.atomic
def archive_current_organization(*, request: HttpRequest) -> None:
    context = authorize(ORGANIZATION_ARCHIVE, owner_only=True)
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    organization.archive()
    actor = cast(User, request.user)
    record_audit(
        organization=organization,
        action=OrganizationAuditAction.ORGANIZATION_ARCHIVED,
        actor=actor,
        target_type="organization",
        target_id=organization.id,
    )
    request.session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
    rotate_managed_session(request=request)


def _validate_model(
    instance: Organization,
    *,
    validate_uniqueness: bool = True,
) -> None:
    try:
        instance.full_clean(
            validate_unique=validate_uniqueness,
            validate_constraints=validate_uniqueness,
        )
    except DjangoValidationError as error:
        raise ValidationError(error.message_dict) from error
