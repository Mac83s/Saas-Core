from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid7

from django.conf import settings
from django.contrib.auth import logout as django_logout
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User, UserSession
from saas_core.modules.core.identity.sessions import rotate_managed_session
from saas_core.modules.core.identity.tokens import digest_secret, issue_bound_token

from .audit import record_audit
from .authorization import OrganizationPermissionDenied, authorize
from .context import TenantContext
from .middleware import ACTIVE_ORGANIZATION_SESSION_KEY
from .models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
    OrganizationStatus,
    Role,
)
from .permissions import (
    MEMBERS_MANAGE,
    MEMBERS_MANAGE_LIMITED,
    MEMBERS_READ,
    ORGANIZATION_READ,
    OWNERSHIP_TRANSFER,
)
from .platform_workspace import assert_not_platform
from .tasks import issue_tenant_task_contract, send_organization_invitation

LIMITED_ROLE_KEYS = {"viewer", "staff"}


class InvitationConflict(APIException):
    status_code = 409
    default_detail = "Dla tego adresu istnieje już aktywne zaproszenie lub membership."
    default_code = "invitation_conflict"


class InvalidInvitationToken(APIException):
    status_code = 400
    default_detail = "Zaproszenie jest nieprawidłowe, wygasło albo zostało użyte."
    default_code = "invalid_invitation_token"


class InvitationEmailMismatch(APIException):
    status_code = 403
    default_detail = "Zaproszenie jest przypisane do innego konta."
    default_code = "invitation_email_mismatch"


class InvitationNotFound(NotFound):
    default_detail = "Zaproszenie nie istnieje."
    default_code = "invitation_not_found"


class MembershipNotFound(NotFound):
    default_detail = "Członkostwo nie istnieje."
    default_code = "membership_not_found"


class OwnerLifecycleConflict(APIException):
    status_code = 409
    default_detail = "Najpierw przenieś własność organizacji."
    default_code = "owner_lifecycle_conflict"


class SelfMembershipConflict(APIException):
    status_code = 409
    default_detail = "Własnym membership zarządzaj przez operację odejścia."
    default_code = "self_membership_conflict"


@dataclass(frozen=True, slots=True)
class MembershipChange:
    membership: Membership
    session_revoked: bool


def list_memberships() -> list[Membership]:
    context = authorize(MEMBERS_READ)
    return list(
        Membership.objects.select_related("user", "role")
        .filter(
            organization_id=context.organization_id,
            status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED],
        )
        .order_by("user__email")
    )


def list_invitations() -> list[Invitation]:
    context = authorize(MEMBERS_READ)
    return list(
        Invitation.objects.select_related("role")
        .filter(organization_id=context.organization_id)
        .order_by("-created_at")
    )


@transaction.atomic
def create_invitation(
    *,
    request: HttpRequest,
    email: str,
    role_key: str,
) -> Invitation:
    context = _authorize_member_management()
    # Nobody is invited into the platform's own workspace. Its members are put
    # there deliberately by an operator, which is also the only way the MFA
    # requirement below can be relied on.
    assert_not_platform(
        Organization.objects.get(pk=context.organization_id)
    )
    actor = cast(User, request.user)
    normalized_email = User.objects.normalize_email(email)
    role = _assignable_role(
        organization_id=context.organization_id,
        role_key=role_key,
        limited=not context.has_permission(MEMBERS_MANAGE),
    )
    if Membership.objects.filter(
        organization_id=context.organization_id,
        user__email=normalized_email,
        status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED],
    ).exists():
        raise InvitationConflict

    now = timezone.now()
    stale_invitations = list(
        Invitation.objects.select_for_update()
        .select_related("organization")
        .filter(
            organization_id=context.organization_id,
            email=normalized_email,
            status=InvitationStatus.PENDING,
            expires_at__lte=now,
        )
    )
    for stale in stale_invitations:
        stale.status = InvitationStatus.REVOKED
        stale.revoked_at = now
        stale.save(update_fields=["status", "revoked_at"])
        record_audit(
            organization=stale.organization,
            action=OrganizationAuditAction.INVITATION_REVOKED,
            actor=actor,
            target_type="invitation",
            target_id=stale.id,
            metadata={"reason": "expired"},
        )

    invitation_id = uuid7()
    issued = issue_bound_token(
        purpose="organization-invitation",
        identifier=str(invitation_id),
    )
    try:
        invitation = Invitation.objects.create(
            id=invitation_id,
            organization_id=context.organization_id,
            email=normalized_email,
            role=role,
            token_hash=issued.digest,
            invited_by=actor,
            expires_at=now + timedelta(seconds=settings.ORGANIZATION_INVITATION_TTL_SECONDS),
        )
    except IntegrityError as error:
        raise InvitationConflict from error
    record_audit(
        organization=invitation.organization,
        action=OrganizationAuditAction.INVITATION_CREATED,
        actor=actor,
        target_type="invitation",
        target_id=invitation.id,
        metadata={"role": role.key},
    )
    task_contract = issue_tenant_task_contract(causation_id=str(invitation.id))

    def enqueue() -> None:
        send_organization_invitation.delay(str(invitation.id), task_contract)

    transaction.on_commit(enqueue, robust=True)
    return invitation


@transaction.atomic
def accept_invitation(*, request: HttpRequest, token: str) -> Membership:
    user = cast(User, request.user)
    now = timezone.now()
    invitation = (
        Invitation.objects.select_for_update()
        .select_related("organization", "role")
        .filter(token_hash=digest_secret(token))
        .first()
    )
    if (
        invitation is None
        or not invitation.is_usable(at=now)
        or invitation.organization.status
        not in {OrganizationStatus.ONBOARDING, OrganizationStatus.ACTIVE}
        or invitation.role.key == "owner"
        or invitation.role.organization_id not in {None, invitation.organization_id}
    ):
        raise InvalidInvitationToken
    assert_not_platform(invitation.organization)
    if User.objects.normalize_email(user.email) != invitation.email:
        raise InvitationEmailMismatch
    if Membership.objects.filter(
        organization=invitation.organization,
        user=user,
        status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED],
    ).exists():
        raise InvitationConflict

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = now
    invitation.save(update_fields=["status", "accepted_by", "accepted_at"])
    membership = Membership.objects.create(
        organization=invitation.organization,
        user=user,
        role=invitation.role,
        invited_by=invitation.invited_by,
    )
    record_audit(
        organization=invitation.organization,
        action=OrganizationAuditAction.INVITATION_ACCEPTED,
        actor=user,
        target_type="membership",
        target_id=membership.id,
        metadata={"invitation_id": str(invitation.id), "role": invitation.role.key},
    )
    if not request.session.get(ACTIVE_ORGANIZATION_SESSION_KEY):
        request.session[ACTIVE_ORGANIZATION_SESSION_KEY] = str(invitation.organization_id)
        rotate_managed_session(request=request)
    return membership


@transaction.atomic
def revoke_invitation(*, request: HttpRequest, invitation_id: UUID) -> Invitation:
    context = _authorize_member_management()
    actor = cast(User, request.user)
    invitation = (
        Invitation.objects.select_for_update()
        .select_related("organization", "role")
        .filter(pk=invitation_id, organization_id=context.organization_id)
        .first()
    )
    if invitation is None:
        raise InvitationNotFound
    _ensure_limited_role_access(context.role_key, context.permissions, invitation.role.key)
    if invitation.status != InvitationStatus.PENDING:
        raise InvitationConflict
    invitation.status = InvitationStatus.REVOKED
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["status", "revoked_at"])
    record_audit(
        organization=invitation.organization,
        action=OrganizationAuditAction.INVITATION_REVOKED,
        actor=actor,
        target_type="invitation",
        target_id=invitation.id,
    )
    return invitation


@transaction.atomic
def update_membership(
    *,
    request: HttpRequest,
    membership_id: UUID,
    role_key: str | None = None,
    membership_status: str | None = None,
) -> MembershipChange:
    context = _authorize_member_management()
    actor = cast(User, request.user)
    membership = (
        Membership.objects.select_for_update()
        .select_related("organization", "role", "user")
        .filter(
            pk=membership_id,
            organization_id=context.organization_id,
            status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED],
        )
        .first()
    )
    if membership is None:
        raise MembershipNotFound
    if membership.id == context.membership_id:
        raise SelfMembershipConflict
    if membership.role.key == "owner":
        raise OwnerLifecycleConflict
    limited = not context.has_permission(MEMBERS_MANAGE)
    _ensure_limited_role_access(context.role_key, context.permissions, membership.role.key)

    changed = False
    if role_key is not None and role_key != membership.role.key:
        role = _assignable_role(
            organization_id=context.organization_id,
            role_key=role_key,
            limited=limited,
        )
        previous_role = membership.role.key
        membership.role = role
        changed = True
        record_audit(
            organization=membership.organization,
            action=OrganizationAuditAction.MEMBERSHIP_ROLE_CHANGED,
            actor=actor,
            target_type="membership",
            target_id=membership.id,
            metadata={"from": previous_role, "to": role.key},
        )

    if membership_status is not None and membership_status != membership.status:
        action = _membership_status_action(membership_status)
        membership.status = membership_status
        membership.revoked_at = (
            timezone.now() if membership_status == MembershipStatus.REVOKED else None
        )
        changed = True
        record_audit(
            organization=membership.organization,
            action=action,
            actor=actor,
            target_type="membership",
            target_id=membership.id,
        )

    if changed:
        membership.save(update_fields=["role", "status", "revoked_at", "updated_at"])
        revoked = _revoke_user_sessions(membership.user)
    else:
        revoked = False
    return MembershipChange(membership, revoked)


@transaction.atomic
def leave_organization(*, request: HttpRequest) -> None:
    context = authorize(ORGANIZATION_READ)
    if context.role_key == "owner":
        raise OwnerLifecycleConflict
    user = cast(User, request.user)
    membership = (
        Membership.objects.select_for_update()
        .select_related("organization")
        .get(pk=context.membership_id)
    )
    membership.status = MembershipStatus.LEFT
    membership.revoked_at = timezone.now()
    membership.save(update_fields=["status", "revoked_at", "updated_at"])
    record_audit(
        organization=membership.organization,
        action=OrganizationAuditAction.MEMBERSHIP_LEFT,
        actor=user,
        target_type="membership",
        target_id=membership.id,
    )
    _revoke_user_sessions(user)
    request.session.pop(ACTIVE_ORGANIZATION_SESSION_KEY, None)
    django_logout(request)


@transaction.atomic
def transfer_ownership(*, request: HttpRequest, membership_id: UUID) -> None:
    context = authorize(OWNERSHIP_TRANSFER, owner_only=True)
    actor = cast(User, request.user)
    current_owner = (
        Membership.objects.select_for_update()
        .select_related("organization", "user")
        .get(pk=context.membership_id)
    )
    target = (
        Membership.objects.select_for_update()
        .select_related("user", "role")
        .filter(
            pk=membership_id,
            organization_id=context.organization_id,
            status=MembershipStatus.ACTIVE,
        )
        .exclude(pk=current_owner.pk)
        .first()
    )
    if target is None:
        raise MembershipNotFound
    owner_role = Role.objects.get(key="owner", organization=None)
    admin_role = Role.objects.get(key="admin", organization=None)
    current_owner.role = admin_role
    target.role = owner_role
    current_owner.save(update_fields=["role", "updated_at"])
    target.save(update_fields=["role", "updated_at"])
    record_audit(
        organization=current_owner.organization,
        action=OrganizationAuditAction.OWNERSHIP_TRANSFERRED,
        actor=actor,
        target_type="membership",
        target_id=target.id,
        metadata={"previous_owner_membership_id": str(current_owner.id)},
    )
    _revoke_user_sessions(current_owner.user)
    _revoke_user_sessions(target.user)


def _authorize_member_management() -> TenantContext:
    try:
        return authorize(MEMBERS_MANAGE)
    except OrganizationPermissionDenied:
        return authorize(MEMBERS_MANAGE_LIMITED)


def _assignable_role(*, organization_id: UUID, role_key: str, limited: bool) -> Role:
    if role_key == "owner" or (limited and role_key not in LIMITED_ROLE_KEYS):
        raise OrganizationPermissionDenied
    role = (
        Role.objects.filter(key=role_key)
        .filter(Q(organization__isnull=True) | Q(organization_id=organization_id))
        .first()
    )
    if role is None:
        raise OrganizationPermissionDenied
    return role


def _ensure_limited_role_access(
    actor_role_key: str,
    actor_permissions: frozenset[str],
    target_role_key: str,
) -> None:
    if MEMBERS_MANAGE not in actor_permissions and target_role_key not in LIMITED_ROLE_KEYS:
        raise OrganizationPermissionDenied
    if actor_role_key == "manager" and target_role_key == "manager":
        raise OrganizationPermissionDenied


def _membership_status_action(status: str) -> OrganizationAuditAction:
    actions: dict[str, OrganizationAuditAction] = {
        MembershipStatus.ACTIVE: OrganizationAuditAction.MEMBERSHIP_RESUMED,
        MembershipStatus.SUSPENDED: OrganizationAuditAction.MEMBERSHIP_SUSPENDED,
        MembershipStatus.REVOKED: OrganizationAuditAction.MEMBERSHIP_REVOKED,
    }
    try:
        return actions[status]
    except KeyError as error:
        raise ValueError("Nieobsługiwany status membership.") from error


def _revoke_user_sessions(user: User) -> bool:
    return bool(
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    )
