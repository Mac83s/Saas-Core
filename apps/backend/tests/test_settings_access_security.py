"""Who manages billing (34a) and whether the company requires 2FA (35a), on
the settings registry (ADR-078)."""

from __future__ import annotations

from typing import Any

import pytest
from django.utils import timezone

from saas_core.modules.core.identity.models import User, UserMfaMethod, UserStatus
from saas_core.modules.core.identity.step_up import StepUpMfaSetupRequired, activate_step_up
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.models import (
    Membership,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import (
    BILLING_MANAGE,
    MEMBERS_READ,
    ORGANIZATION_READ,
    SYSTEM_ROLE_PERMISSIONS,
)
from saas_core.modules.core.organizations.security_settings import (
    MFA_REQUIRED,
    membership_requires_mfa,
)
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.billing.billing_settings import billing_manager
from test_booking import membership, tenant

pytestmark = pytest.mark.django_db(transaction=True)


def _role(key: str, permissions: list[str], organization: Any = None) -> Role:
    role, _ = Role.objects.get_or_create(
        key=key,
        organization=organization,
        organization_type="",
        defaults={
            "name": key.title(),
            "scope": RoleScope.ORGANIZATION if organization else RoleScope.SYSTEM,
            "permissions": permissions,
            "is_immutable": organization is None,
        },
    )
    return role


def _member(owner: Membership, email: str, role: Role) -> Membership:
    user = User.objects.create_user(email=email)
    user.status = UserStatus.ACTIVE
    user.save()
    return Membership.objects.create(organization=owner.organization, user=user, role=role)


def _change(group: str, key: str, **changes: Any) -> Any:
    return change_settings(
        group, changes=changes, expected_version=read_group(group).version, idempotency_key=key
    )


def test_billing_is_the_owners_until_the_owner_lets_the_billing_role_in() -> None:
    owner = membership("billing-access")
    accountant = _member(
        owner,
        "ksiegowa@example.test",
        _role("ksiegowa", [ORGANIZATION_READ, BILLING_MANAGE], owner.organization),
    )

    with tenant(accountant), pytest.raises(OrganizationPermissionDenied):
        billing_manager()
    with tenant(accountant), pytest.raises(OrganizationPermissionDenied):
        # Only the owner turns the switch, and before any code is asked.
        _change("billing.access", "k-0", delegated=True)
    with tenant(owner), pytest.raises(StepUpMfaSetupRequired):
        # The switch is a billing change: a code from the authenticator app (31b).
        _change("billing.access", "k-1", delegated=True)
    with tenant(owner), activate_step_up(int(timezone.now().timestamp())):
        _change("billing.access", "k-2", delegated=True)
    with tenant(accountant):
        assert billing_manager().membership_id == accountant.id


def test_the_company_decides_whose_sign_in_needs_2fa() -> None:
    owner = membership("mfa-requirement")
    staff = _member(
        owner, "pracownik-mfa@example.test", _role("staff", list(SYSTEM_ROLE_PERMISSIONS["staff"]))
    )
    manager = _member(
        owner,
        "kierownik-mfa@example.test",
        _role(
            "team_lead",
            [ORGANIZATION_READ, MEMBERS_READ, "organization.members.manage_limited"],
            owner.organization,
        ),
    )
    for member in (owner, staff, manager):
        member.refresh_from_db()

    with tenant(owner):
        assert [membership_requires_mfa(m) for m in (owner, staff, manager)] == [False] * 3
        _change("organization.security", "k-1", mfa_required="managers")
        assert [membership_requires_mfa(m) for m in (owner, staff, manager)] == [
            True,
            False,
            True,
        ]
        _change("organization.security", "k-2", mfa_required="all")
        assert membership_requires_mfa(staff) is True
    assert MFA_REQUIRED == "organization.security.mfa_required"


def test_the_member_list_shows_who_has_2fa_to_who_manages_the_team() -> None:
    from saas_core.modules.core.organizations.lifecycle import list_memberships  # noqa: PLC0415
    from saas_core.modules.core.organizations.security_settings import mfa_status  # noqa: PLC0415

    owner = membership("mfa-list")
    staff = _member(
        owner,
        "pracownik-lista@example.test",
        _role("staff", list(SYSTEM_ROLE_PERMISSIONS["staff"])),
    )
    UserMfaMethod.objects.create(
        user_id=owner.user_id, secret_ciphertext="x", confirmed_at=timezone.now()
    )
    with tenant(owner):
        seen = mfa_status(list_memberships())
    with tenant(staff):
        hidden = mfa_status(list_memberships())
    assert seen == frozenset({owner.user_id})
    assert hidden is None
