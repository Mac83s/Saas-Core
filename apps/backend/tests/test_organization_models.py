from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationStatus,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS

pytestmark = pytest.mark.django_db


def create_organization(*, slug: str = "acme") -> Organization:
    return Organization.objects.create(name="ACME", slug=slug)


def create_user(*, email: str = "owner@example.com") -> User:
    return User.objects.create_user(email=email)


def test_system_roles_are_seeded_with_stable_permissions() -> None:
    roles = {
        role.key: role
        for role in Role.objects.filter(scope=RoleScope.SYSTEM, organization_type="")
    }

    assert set(roles) == set(SYSTEM_ROLE_PERMISSIONS)
    for key, permissions in SYSTEM_ROLE_PERMISSIONS.items():
        assert roles[key].organization_id is None
        assert roles[key].is_immutable
        assert roles[key].permissions == list(permissions)


def test_system_roles_are_immutable_at_database_boundary() -> None:
    owner = Role.objects.get(key="owner", organization=None, organization_type="")

    with pytest.raises(DatabaseError), transaction.atomic():
        Role.objects.filter(pk=owner.pk).update(name="Tampered")
    with pytest.raises(DatabaseError), transaction.atomic():
        Role.objects.filter(pk=owner.pk).delete()

    owner.refresh_from_db()
    assert owner.name == "Owner"


def test_custom_roles_remain_mutable_and_deletable() -> None:
    organization = create_organization()
    role = Role.objects.create(
        organization=organization,
        key="editor",
        name="Editor",
        scope=RoleScope.ORGANIZATION,
        permissions=["organization.read"],
    )

    Role.objects.filter(pk=role.pk).update(name="Content editor")
    deleted, _ = Role.objects.filter(pk=role.pk).delete()

    assert deleted == 1
    assert not Role.objects.filter(pk=role.pk).exists()


def test_organization_normalizes_slug_and_currency_and_uses_uuidv7() -> None:
    organization = Organization.objects.create(
        name="ACME",
        slug="  ACME-PL  ",
        currency="eur",
    )

    assert organization.slug == "acme-pl"
    assert organization.currency == "EUR"
    assert organization.id.version == 7


def test_organization_rejects_unknown_timezone() -> None:
    organization = Organization(name="ACME", slug="acme", timezone="Mars/Olympus")

    with pytest.raises(ValidationError, match="Nieznana strefa czasowa"):
        organization.full_clean()


def test_archiving_keeps_status_timestamp_and_version_consistent() -> None:
    organization = create_organization()

    organization.archive()
    organization.refresh_from_db()

    assert organization.status == OrganizationStatus.ARCHIVED
    assert organization.archived_at is not None
    assert organization.version == 2


def test_only_one_current_membership_is_allowed_but_history_is_preserved() -> None:
    organization = create_organization()
    user = create_user()
    role = Role.objects.get(key="owner", organization=None, organization_type="")
    Membership.objects.create(organization=organization, user=user, role=role)

    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(
            organization=organization,
            user=user,
            role=role,
            status=MembershipStatus.SUSPENDED,
        )

    Membership.objects.filter(organization=organization, user=user).update(
        status=MembershipStatus.REVOKED,
        revoked_at=timezone.now(),
    )
    replacement = Membership.objects.create(
        organization=organization,
        user=user,
        role=role,
    )

    assert replacement.status == MembershipStatus.ACTIVE
    assert Membership.objects.filter(organization=organization, user=user).count() == 2


def test_membership_rejects_custom_role_from_another_organization() -> None:
    organization = create_organization()
    other = create_organization(slug="other")
    custom_role = Role.objects.create(
        organization=other,
        key="editor",
        name="Editor",
        scope=RoleScope.ORGANIZATION,
        permissions=["organization.read"],
    )
    membership = Membership(
        organization=organization,
        user=create_user(),
        role=custom_role,
    )

    with pytest.raises(ValidationError, match="innej organizacji"):
        membership.full_clean()


def test_revoked_membership_requires_revocation_timestamp() -> None:
    organization = create_organization()
    membership = Membership.objects.create(
        organization=organization,
        user=create_user(),
        role=Role.objects.get(key="viewer", organization=None, organization_type=""),
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.filter(pk=membership.pk).update(status=MembershipStatus.REVOKED)

    Membership.objects.filter(pk=membership.pk).update(
        status=MembershipStatus.REVOKED,
        revoked_at=timezone.now() + timedelta(seconds=1),
    )


def test_billing_profile_is_separate_and_one_to_one() -> None:
    organization = create_organization()
    BillingProfile.objects.create(organization=organization, legal_name="ACME sp. z o.o.")

    with pytest.raises(IntegrityError), transaction.atomic():
        BillingProfile.objects.create(organization=organization, legal_name="Duplicate")
