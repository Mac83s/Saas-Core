"""Purging synthetic tenants: what it removes, and what it must never touch.

The command exists because tenant rows protect their organization, so nothing
in the tree can be deleted in one call. The interesting part is not the
deletion but the guard: a real address, or an organization holding one, has to
survive a sweep aimed at test rubble.
"""

from __future__ import annotations

import pytest
from django.core.management import CommandError, call_command
from django.db import transaction

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db

REAL_EMAIL = "wlasciciel@condictor.pl"


def make_tenant(*, slug: str, email: str) -> tuple[Organization, User]:
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE
    )
    user = User.objects.create_user(email=email, password="Purge-Test-Password-1")
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.get(key="admin", organization=None),
    )
    # A row that protects the organization, so the command has to walk a
    # refusal instead of deleting in one call.
    with transaction.atomic():
        set_local_organization_id(organization.id)
        EntitlementSnapshot.all_objects.create(
            organization=organization,
            subscription_state=SubscriptionState.ACTIVE,
            access_mode=AccessMode.FULL,
            features={},
            quotas={},
            sources={},
        )
    return organization, user


def test_a_real_address_is_refused() -> None:
    _organization, user = make_tenant(slug="purge-real", email=REAL_EMAIL)

    with pytest.raises(CommandError):
        call_command("purge_test_tenants", "--email", REAL_EMAIL, "--apply")

    assert User.objects.filter(pk=user.pk).exists()


def test_dry_run_changes_nothing() -> None:
    organization, user = make_tenant(slug="purge-dry", email="purge-dry@example.test")

    call_command("purge_test_tenants", "--email", user.email)

    assert Organization.objects.filter(pk=organization.pk).exists()
    assert User.objects.filter(pk=user.pk).exists()


def test_apply_removes_the_tenant_with_its_protecting_rows() -> None:
    organization, user = make_tenant(slug="purge-apply", email="purge-apply@example.test")

    call_command("purge_test_tenants", "--email", user.email, "--apply")

    assert not Organization.objects.filter(pk=organization.pk).exists()
    assert not User.objects.filter(pk=user.pk).exists()
    assert not Membership.objects.filter(organization_id=organization.pk).exists()
    assert not EntitlementSnapshot.all_objects.filter(
        organization_id=organization.pk
    ).exists()
    # A role shared by every tenant is not tenant rubble.
    assert Role.objects.filter(key="admin", organization=None).exists()


def test_an_organization_holding_a_real_member_is_left_alone() -> None:
    organization, test_user = make_tenant(
        slug="purge-mixed", email="purge-mixed@example.test"
    )
    owner = User.objects.create_user(email=REAL_EMAIL, password="Purge-Test-Password-2")
    Membership.objects.create(
        organization=organization,
        user=owner,
        role=Role.objects.get(key="owner", organization=None),
    )

    call_command("purge_test_tenants", "--email", test_user.email, "--apply")

    assert Organization.objects.filter(pk=organization.pk).exists()
    assert User.objects.filter(pk=test_user.pk).exists()
    assert User.objects.filter(pk=owner.pk).exists()


def test_a_sweep_only_takes_reserved_domains() -> None:
    _rubble_org, rubble_user = make_tenant(
        slug="purge-sweep", email="purge-sweep@example.test"
    )
    kept_org, kept_user = make_tenant(slug="purge-kept", email=REAL_EMAIL)

    call_command("purge_test_tenants", "--all", "--apply")

    assert not User.objects.filter(pk=rubble_user.pk).exists()
    assert User.objects.filter(pk=kept_user.pk).exists()
    assert Organization.objects.filter(pk=kept_org.pk).exists()
