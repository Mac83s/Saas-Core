"""Who manages billing (34a) and whether the company requires 2FA (35a), on
the settings registry (ADR-078)."""

from __future__ import annotations

from typing import Any

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

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
from saas_core.modules.core.organizations.settings_service import (
    Resolved,
    change_settings,
    read_group,
    resolve,
)
from saas_core.modules.shared.billing.billing_settings import billing_manager
from test_booking import membership, tenant
from test_organization_api import PASSWORD, csrf_value, login

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


def _preview(group: str, **changes: Any) -> Any:
    return change_settings(
        group, changes=changes, expected_version=read_group(group).version, preview=True
    )


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
        # Without 2FA of their own the owner would shut themselves out.
        with pytest.raises(ValidationError) as refused:
            _change("organization.security", "k-0", mfa_required="managers")
        assert [e.code for e in refused.value.detail["mfa_required"]] == ["mfa_required_self"]
    UserMfaMethod.objects.create(
        user_id=owner.user_id, secret_ciphertext="x", confirmed_at=timezone.now()
    )
    with tenant(owner):
        # The preview says who loses access: the manager now, the staff with "all".
        effects = _preview("organization.security", mfa_required="managers").effects
        assert [e.summary["pl"] for e in effects] == [
            "1 osoba w firmie straci dostęp, dopóki nie włączy 2FA."
        ]
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


def test_a_product_s_2fa_default_is_where_a_new_company_starts_never_an_older_one(
    settings: Any,
) -> None:
    older = membership("mfa-older")
    user = older.user
    user.set_password(PASSWORD)
    user.save()
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, user).status_code == 200
    settings.SETTINGS_DEFAULTS = {MFA_REQUIRED: "managers"}

    created = client.post(
        "/api/v1/organizations/",
        {
            "name": "Nowy gabinet",
            "slug": "mfa-newer",
            "organization_type": settings.DEFAULT_ORGANIZATION_TYPE,
            "workspace_kind": "business",
            "default_locale": "pl",
            "timezone": "Europe/Warsaw",
            "currency": "PLN",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert created.status_code == 201
    newer = Membership.objects.select_related("role").get(organization__slug="mfa-newer", user=user)

    # The older company keeps what it had: the product's value is not read live.
    with tenant(older):
        assert resolve(MFA_REQUIRED) == Resolved("none", "code")
        assert membership_requires_mfa(older) is False
    # The new one starts there, as its own choice it may change.
    with tenant(newer):
        assert resolve(MFA_REQUIRED) == Resolved("managers", "organization")
        assert membership_requires_mfa(newer) is True
