from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserSession, UserStatus
from saas_core.modules.core.identity.tokens import issue_bound_token
from saas_core.modules.core.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)
from saas_core.modules.core.organizations.tasks import send_organization_invitation

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
INVITATIONS_URL = "/api/v1/organizations/current/invitations/"
ACCEPT_URL = "/api/v1/invitations/accept/"
MEMBERS_URL = "/api/v1/organizations/current/members/"
LEAVE_URL = "/api/v1/organizations/current/members/me/leave/"
TRANSFER_URL = "/api/v1/organizations/current/ownership-transfer/"
PASSWORD = "Bezpieczne-Haslo-2026!"


@pytest.fixture(autouse=True)
def clear_state() -> None:
    cache.clear()
    mail.outbox.clear()


def active_user(email: str) -> User:
    user = User.objects.create_user(email=email, password=PASSWORD)
    user.status = UserStatus.ACTIVE
    user.save()
    return user


def organization_with_member(
    *,
    user: User,
    role_key: str,
    slug: str = "lifecycle",
    organization: Organization | None = None,
) -> Membership:
    tenant = organization or Organization.objects.create(
        name=slug.upper(),
        slug=slug,
        status=OrganizationStatus.ACTIVE,
    )
    return Membership.objects.create(
        organization=tenant,
        user=user,
        role=Role.objects.get(key=role_key, organization=None),
    )


def login(client: APIClient, user: User):
    csrf = client.get(CSRF_URL).data["csrf_token"]
    return client.post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )


def csrf_value(client: APIClient) -> str:
    return client.cookies["csrftoken"].value


def authenticated_member(
    *,
    email: str,
    role_key: str,
    organization: Organization | None = None,
    slug: str = "lifecycle",
) -> tuple[User, Membership, APIClient]:
    user = active_user(email)
    membership = organization_with_member(
        user=user,
        role_key=role_key,
        slug=slug,
        organization=organization,
    )
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    return user, membership, client


def invitation_token(invitation: Invitation) -> str:
    return issue_bound_token(
        purpose="organization-invitation",
        identifier=str(invitation.id),
    ).value


def create_invitation_through_api(
    client: APIClient,
    *,
    email: str,
    role: str = "staff",
) -> Invitation:
    response = client.post(
        INVITATIONS_URL,
        {"email": email, "role": role},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 201
    return Invitation.objects.get(pk=response.data["id"])


def test_invitation_for_existing_user_is_one_time_and_audited() -> None:
    _, owner_membership, owner_client = authenticated_member(
        email="owner@example.com",
        role_key="owner",
    )
    invitee = active_user("invitee@example.com")
    invitation = create_invitation_through_api(owner_client, email=invitee.email)
    token = invitation_token(invitation)
    invitee_client = APIClient(enforce_csrf_checks=True)
    assert login(invitee_client, invitee).status_code == 200

    accepted = invitee_client.post(
        ACCEPT_URL,
        {"token": token},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(invitee_client),
    )
    replay = invitee_client.post(
        ACCEPT_URL,
        {"token": token},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(invitee_client),
    )

    assert accepted.status_code == 200
    assert accepted.data["role"] == "staff"
    assert replay.status_code == 400
    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.ACCEPTED
    assert invitation.accepted_by == invitee
    assert Membership.objects.filter(
        organization=owner_membership.organization,
        user=invitee,
        status=MembershipStatus.ACTIVE,
    ).exists()
    assert OrganizationAuditEntry.objects.filter(
        organization=owner_membership.organization,
        action=OrganizationAuditAction.INVITATION_ACCEPTED,
        actor_user=invitee,
    ).exists()


def test_invitation_for_new_user_can_be_accepted_after_registration() -> None:
    _, membership, owner_client = authenticated_member(
        email="new-owner@example.com",
        role_key="owner",
        slug="new-user-flow",
    )
    invitation = create_invitation_through_api(
        owner_client,
        email="future@example.com",
        role="viewer",
    )
    future_user = active_user("future@example.com")
    future_client = APIClient(enforce_csrf_checks=True)
    assert login(future_client, future_user).status_code == 200

    response = future_client.post(
        ACCEPT_URL,
        {"token": invitation_token(invitation)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(future_client),
    )

    assert response.status_code == 200
    assert (
        Membership.objects.get(
            organization=membership.organization,
            user=future_user,
        ).role.key
        == "viewer"
    )


def test_invitation_accept_requires_authentication_and_csrf() -> None:
    _, _, owner_client = authenticated_member(
        email="accept-security-owner@example.com",
        role_key="owner",
        slug="accept-security",
    )
    invitee = active_user("accept-security-target@example.com")
    invitation = create_invitation_through_api(owner_client, email=invitee.email)
    payload = {"token": invitation_token(invitation)}

    anonymous = APIClient(enforce_csrf_checks=True).post(
        ACCEPT_URL,
        payload,
        format="json",
    )
    invitee_client = APIClient(enforce_csrf_checks=True)
    assert login(invitee_client, invitee).status_code == 200
    missing_csrf = invitee_client.post(ACCEPT_URL, payload, format="json")

    assert anonymous.status_code == 403
    assert missing_csrf.status_code == 403


def test_invitation_rejects_wrong_email_expiry_revocation_and_replay() -> None:
    _, _, owner_client = authenticated_member(
        email="guard-owner@example.com",
        role_key="owner",
        slug="invite-guards",
    )
    wrong_user = active_user("wrong@example.com")
    wrong_client = APIClient(enforce_csrf_checks=True)
    assert login(wrong_client, wrong_user).status_code == 200
    invitation = create_invitation_through_api(
        owner_client,
        email="right@example.com",
    )
    token = invitation_token(invitation)

    mismatch = wrong_client.post(
        ACCEPT_URL,
        {"token": token},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(wrong_client),
    )
    Invitation.objects.filter(pk=invitation.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    expired = wrong_client.post(
        ACCEPT_URL,
        {"token": token},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(wrong_client),
    )

    assert mismatch.status_code == 403
    assert expired.status_code == 400
    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.PENDING

    replacement = create_invitation_through_api(
        owner_client,
        email="right@example.com",
    )
    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.REVOKED
    revoked = owner_client.delete(
        f"{INVITATIONS_URL}{replacement.id}/",
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )
    assert revoked.status_code == 200
    replacement.refresh_from_db()
    assert replacement.status == InvitationStatus.REVOKED
    right_user = active_user("right@example.com")
    right_client = APIClient(enforce_csrf_checks=True)
    assert login(right_client, right_user).status_code == 200
    revoked_accept = right_client.post(
        ACCEPT_URL,
        {"token": invitation_token(replacement)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(right_client),
    )
    assert revoked_accept.status_code == 400


@pytest.mark.parametrize(
    ("actor_role", "target_role", "expected_status"),
    [
        ("manager", "viewer", 201),
        ("manager", "staff", 201),
        ("manager", "manager", 403),
        ("manager", "admin", 403),
        ("admin", "manager", 201),
        ("admin", "admin", 201),
        ("owner", "owner", 403),
    ],
)
def test_invitation_role_ceiling(
    actor_role: str,
    target_role: str,
    expected_status: int,
) -> None:
    _, _, client = authenticated_member(
        email=f"{actor_role}-{target_role}@example.com",
        role_key=actor_role,
        slug=f"invite-{actor_role}-{target_role}",
    )

    response = client.post(
        INVITATIONS_URL,
        {"email": f"target-{actor_role}-{target_role}@example.com", "role": target_role},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("role_key", "members_status", "invite_status"),
    [
        ("viewer", 403, 403),
        ("staff", 200, 403),
        ("manager", 200, 201),
        ("admin", 200, 201),
        ("owner", 200, 201),
    ],
)
def test_membership_read_and_invite_permission_matrix(
    role_key: str,
    members_status: int,
    invite_status: int,
) -> None:
    _, _, client = authenticated_member(
        email=f"matrix-{role_key}@example.com",
        role_key=role_key,
        slug=f"matrix-{role_key}",
    )

    members = client.get(MEMBERS_URL)
    invitation = client.post(
        INVITATIONS_URL,
        {"email": f"matrix-target-{role_key}@example.com", "role": "viewer"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert members.status_code == members_status
    assert invitation.status_code == invite_status


def test_invitation_email_task_reconstructs_token_without_storing_it(
    django_capture_on_commit_callbacks,
) -> None:
    _, owner_membership, owner_client = authenticated_member(
        email="mail-owner@example.com",
        role_key="owner",
        slug="invite-mail",
    )
    owner_membership.organization.default_locale = "en"
    owner_membership.organization.save(update_fields=["default_locale", "updated_at"])

    with django_capture_on_commit_callbacks(execute=True):
        invitation = create_invitation_through_api(
            owner_client,
            email="mail-target@example.com",
        )

    token = invitation_token(invitation)
    assert len(mail.outbox) == 1
    assert token in mail.outbox[0].body
    assert "/en/invitations/accept?" in mail.outbox[0].body
    assert token not in invitation.token_hash
    assert invitation.token_hash != token

    mail.outbox.clear()
    send_organization_invitation(str(invitation.id), "invalid-context")
    assert mail.outbox == []


def test_manager_can_suspend_staff_but_not_admin_and_sessions_are_revoked() -> None:
    manager, manager_membership, manager_client = authenticated_member(
        email="manager@example.com",
        role_key="manager",
        slug="membership-roles",
    )
    organization = manager_membership.organization
    staff, staff_membership, staff_client = authenticated_member(
        email="staff@example.com",
        role_key="staff",
        organization=organization,
    )
    _, admin_membership, _ = authenticated_member(
        email="admin@example.com",
        role_key="admin",
        organization=organization,
    )
    assert UserSession.objects.filter(user=staff, revoked_at__isnull=True).exists()

    suspended = manager_client.patch(
        f"{MEMBERS_URL}{staff_membership.id}/",
        {"status": "suspended"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(manager_client),
    )
    forbidden = manager_client.patch(
        f"{MEMBERS_URL}{admin_membership.id}/",
        {"status": "suspended"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(manager_client),
    )

    assert suspended.status_code == 200
    assert forbidden.status_code == 403
    staff_membership.refresh_from_db()
    assert staff_membership.status == MembershipStatus.SUSPENDED
    assert not UserSession.objects.filter(user=staff, revoked_at__isnull=True).exists()
    assert staff_client.get(MEMBERS_URL).status_code == 403
    assert manager.email == "manager@example.com"


def test_admin_can_change_role_and_revoke_non_owner_membership() -> None:
    _, admin_membership, admin_client = authenticated_member(
        email="lifecycle-admin@example.com",
        role_key="admin",
        slug="admin-lifecycle",
    )
    target = active_user("target@example.com")
    target_membership = organization_with_member(
        user=target,
        role_key="manager",
        organization=admin_membership.organization,
    )

    response = admin_client.patch(
        f"{MEMBERS_URL}{target_membership.id}/",
        {"role": "viewer", "status": "revoked"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(admin_client),
    )

    assert response.status_code == 200
    target_membership.refresh_from_db()
    assert target_membership.role.key == "viewer"
    assert target_membership.status == MembershipStatus.REVOKED
    assert target_membership.revoked_at is not None
    actions = set(
        OrganizationAuditEntry.objects.filter(target_id=target_membership.id).values_list(
            "action", flat=True
        )
    )
    assert actions == {
        OrganizationAuditAction.MEMBERSHIP_ROLE_CHANGED,
        OrganizationAuditAction.MEMBERSHIP_REVOKED,
    }


def test_member_can_leave_but_owner_must_transfer_first() -> None:
    _, owner_membership, owner_client = authenticated_member(
        email="leave-owner@example.com",
        role_key="owner",
        slug="leave-flow",
    )
    member, member_membership, member_client = authenticated_member(
        email="leave-member@example.com",
        role_key="staff",
        organization=owner_membership.organization,
    )

    owner_blocked = owner_client.post(
        LEAVE_URL,
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )
    left = member_client.post(
        LEAVE_URL,
        HTTP_X_CSRFTOKEN=csrf_value(member_client),
    )

    assert owner_blocked.status_code == 409
    assert left.status_code == 200
    member_membership.refresh_from_db()
    assert member_membership.status == MembershipStatus.LEFT
    assert not UserSession.objects.filter(user=member, revoked_at__isnull=True).exists()


def test_owner_can_transfer_ownership_and_both_sessions_are_revoked() -> None:
    owner, owner_membership, owner_client = authenticated_member(
        email="transfer-owner@example.com",
        role_key="owner",
        slug="transfer-flow",
    )
    target, target_membership, _ = authenticated_member(
        email="transfer-target@example.com",
        role_key="admin",
        organization=owner_membership.organization,
    )

    response = owner_client.post(
        TRANSFER_URL,
        {"membership_id": str(target_membership.id)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(owner_client),
    )

    assert response.status_code == 200
    owner_membership.refresh_from_db()
    target_membership.refresh_from_db()
    assert owner_membership.role.key == "admin"
    assert target_membership.role.key == "owner"
    assert not UserSession.objects.filter(
        user__in=[owner, target], revoked_at__isnull=True
    ).exists()
    assert OrganizationAuditEntry.objects.filter(
        organization=owner_membership.organization,
        action=OrganizationAuditAction.OWNERSHIP_TRANSFERRED,
        target_id=target_membership.id,
    ).exists()


def test_audit_is_append_only_in_model_and_database() -> None:
    user, membership, _ = authenticated_member(
        email="audit-owner@example.com",
        role_key="owner",
        slug="audit-append-only",
    )
    entry = OrganizationAuditEntry.objects.create(
        organization=membership.organization,
        actor_user=user,
        action=OrganizationAuditAction.ORGANIZATION_UPDATED,
    )
    entry.metadata = {"tampered": True}

    with pytest.raises(ValidationError):
        entry.save()
    with pytest.raises(ValidationError):
        entry.delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        OrganizationAuditEntry.objects.filter(pk=entry.pk).update(metadata={"tampered": True})
    with pytest.raises(DatabaseError), transaction.atomic():
        OrganizationAuditEntry.objects.filter(pk=entry.pk).delete()

    entry.refresh_from_db()
    assert entry.metadata == {}
