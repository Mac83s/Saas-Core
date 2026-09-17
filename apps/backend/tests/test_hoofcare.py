"""The HoofCare vertical's use cases.

The suite runs under `business` by default, which composes no vertical, so these
are skipped there and run under the `hoofcare` profile — the only composition in
which these tables and permissions exist at all.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from django.conf import settings
from django.db import transaction

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationStatus,
    Role,
    RoleScope,
)
from saas_core.modules.core.organizations.permissions import SYSTEM_ROLE_PERMISSIONS
from saas_core.modules.shared.billing.api import EntitlementRequired
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    Feature,
    SubscriptionState,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        "vertical.hoofcare" not in settings.ACTIVE_MODULES,
        reason="wertykał istnieje tylko w profilu, który go składa",
    ),
]


def membership(slug: str, *, entitled: bool = True) -> Membership:
    Feature.objects.get_or_create(
        key="hoofcare.enabled",
        defaults={"name": "Korekcja racic", "module": "vertical.hoofcare"},
    )
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE, timezone="Europe/Warsaw"
    )
    role, _ = Role.objects.get_or_create(
        key="owner",
        organization=None,
        defaults={
            "name": "Owner",
            "scope": RoleScope.SYSTEM,
            "permissions": list(SYSTEM_ROLE_PERMISSIONS["owner"]),
            "is_immutable": True,
        },
    )
    member = Membership.objects.create(organization=organization, user=user, role=role)
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"hoofcare.enabled": entitled},
        quotas={},
        sources={"hoofcare.enabled": {"kind": "plan"}},
    )
    return member


@contextmanager
def tenant(member: Membership) -> Any:
    context = context_from_membership(member)
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        yield context


def test_a_farm_and_its_animals_are_created_and_listed_for_the_tenant() -> None:
    from saas_core.modules.vertical.hoofcare.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
        list_farms,
    )

    member = membership("gospodarstwa")
    with tenant(member):
        farm = create_farm(data={"name": "Gospodarstwo Nowak", "village": "Żydowo"})
        create_animal(farm_id=farm.id, data={"national_id": "PL 05432198765", "name": "LUNA"})

        assert [item.name for item in list_farms()] == ["Gospodarstwo Nowak"]
        animals = list_animals(farm_id=farm.id)
        assert [item.national_id for item in animals] == ["PL 05432198765"]


def test_another_tenants_farm_is_simply_not_found() -> None:
    """Not a 403: the answer to "that is not yours" must not confirm it exists."""
    from saas_core.modules.vertical.hoofcare.models import Farm  # noqa: PLC0415
    from saas_core.modules.vertical.hoofcare.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
    )

    first = membership("stado-a")
    second = membership("stado-b")
    with tenant(first):
        farm = create_farm(data={"name": "Cudze gospodarstwo"})

    with tenant(second), pytest.raises(Farm.DoesNotExist):
        create_animal(farm_id=farm.id, data={"national_id": "PL 1"})


def test_the_vertical_is_closed_without_its_entitlement() -> None:
    """A composed module is not a sold one: the plan still decides."""
    from saas_core.modules.vertical.hoofcare.services import list_farms  # noqa: PLC0415

    member = membership("bez-planu", entitled=False)
    with tenant(member), pytest.raises(EntitlementRequired):
        list_farms()
