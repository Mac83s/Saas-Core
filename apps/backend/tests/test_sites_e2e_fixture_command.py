from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.models import Membership, Organization
from saas_core.modules.shared.billing.models import EntitlementSnapshot

pytestmark = pytest.mark.django_db


def test_sites_e2e_fixture_is_synthetic_entitled_and_removable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "w6-e2e-command@example.test"
    slug = "w6-e2e-command"
    monkeypatch.setenv("SITES_E2E_PASSWORD", "Synthetic-W6-E2E-Password!")

    call_command("sites_e2e_fixture", "prepare", email=email, slug=slug)

    user = User.objects.get(email=email)
    organization = Organization.objects.get(slug=slug)
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert user.status == UserStatus.ACTIVE
    assert user.is_staff is False
    assert Membership.objects.get(user=user, organization=organization).role.key == "admin"
    assert snapshot.features == {"sites.enabled": True, "storage.enabled": True}
    assert snapshot.quotas["sites.max"] == 3

    call_command("sites_e2e_fixture", "cleanup", email=email, slug=slug)

    assert not User.objects.filter(email=email).exists()
    assert not Organization.objects.filter(slug=slug).exists()


def test_sites_e2e_fixture_rejects_non_reserved_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SITES_E2E_PASSWORD", "Synthetic-W6-E2E-Password!")

    with pytest.raises(CommandError):
        call_command(
            "sites_e2e_fixture",
            "prepare",
            email="owner@example.test",
            slug="production",
        )
