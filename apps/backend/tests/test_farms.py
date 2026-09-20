"""The farm register (`shared.farms`, ADR-051).

Skipped where the profile does not compose the module. In Saas-Core the main
profile is `agro`, so these run in the default suite; in a product repository
they run under any profile that composes the register.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
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
        "shared.farms" not in settings.ACTIVE_MODULES,
        reason="rejestr gospodarstw istnieje tylko w profilu, który go składa",
    ),
]


def membership(slug: str, *, entitled: bool = True) -> Membership:
    Feature.objects.get_or_create(
        key="farms.enabled", defaults={"name": "Rejestr gospodarstw", "module": "shared.farms"}
    )
    user = User.objects.create_user(email=f"{slug}@example.test")
    user.status = UserStatus.ACTIVE
    user.save()
    organization = Organization.objects.create(
        name=slug, slug=slug, status=OrganizationStatus.ACTIVE, timezone="Europe/Warsaw"
    )
    # Transactional tests flush the seeded roles between tests, so the owner
    # role is restored the way the migration wrote it.
    role, _ = Role.objects.get_or_create(
        key="owner",
        organization=None,
        organization_type="",
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
        features={"farms.enabled": entitled},
        quotas={},
        sources={"farms.enabled": {"kind": "plan"}},
    )
    return member


@contextmanager
def tenant(member: Membership) -> Any:
    context = context_from_membership(member)
    with transaction.atomic(), activate_tenant_context(context):
        set_local_organization_id(context.organization_id)
        yield SimpleNamespace(user=member.user)


def test_the_register_is_granted_to_core_roles() -> None:
    assert {"farms.read", "farms.manage"} <= set(SYSTEM_ROLE_PERMISSIONS["owner"])
    assert "farms.read" in SYSTEM_ROLE_PERMISSIONS["viewer"]
    assert "farms.manage" not in SYSTEM_ROLE_PERMISSIONS["viewer"]


def test_a_farm_is_identified_by_its_herd_number_and_audited() -> None:
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_farm,
        list_farms,
        update_farm,
    )

    member = membership("rejestr")
    with tenant(member) as request:
        farm = create_farm(
            request=request,
            data={
                "name": "Gospodarstwo Nowak",
                "herd_number": "pl 012345678-001",
                "tax_id": "777-000-00-00",
            },
        )
        assert farm.herd_number == "PL012345678001"
        assert farm.tax_id == "7770000000"

        # One herd however the suffix is typed: the database constraint answers.
        for spelling in ("PL012345678-001", "PL 012345678 001"):
            with pytest.raises(ValidationError, match="numerem siedziby stada"):
                create_farm(request=request, data={"name": spelling, "herd_number": spelling})
        with pytest.raises(ValidationError, match="nazwie"):
            create_farm(request=request, data={"name": "Gospodarstwo Nowak"})
        with pytest.raises(ValidationError, match="PL012345678-001"):
            create_farm(request=request, data={"name": "Zły numer", "herd_number": "12"})
        with pytest.raises(ValidationError, match="10 cyfr"):
            create_farm(request=request, data={"name": "Zły NIP", "tax_id": "123"})
        # A word where the NIP goes is a mistake, not a request to erase it.
        with pytest.raises(ValidationError, match="10 cyfr"):
            update_farm(request=request, farm_id=farm.id, data={"tax_id": "brak"})

        updated = update_farm(request=request, farm_id=farm.id, data={"village": "Żydowo"})
        assert (updated.tax_id, updated.animal_count) == ("7770000000", 0)
        assert [item.name for item in list_farms(search="012345678-001")] == ["Gospodarstwo Nowak"]
        assert [item.name for item in list_farms(search="żydowo")] == ["Gospodarstwo Nowak"]

    actions = set(
        OrganizationAuditEntry.objects.filter(organization_id=member.organization_id).values_list(
            "action", flat=True
        )
    )
    assert {"farms.farm.created", "farms.farm.updated"} <= actions


def test_an_animal_is_a_species_and_a_normalized_identifier() -> None:
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        get_farm,
        list_animals,
        update_animal,
    )

    member = membership("zwierzeta")
    with tenant(member) as request:
        farm = create_farm(request=request, data={"name": "Ferma"})
        animal = create_animal(
            request=request,
            farm_id=farm.id,
            data={"national_id": "pl 005 432 198 765", "name": "LUNA"},
        )
        assert (animal.species, animal.national_id) == ("cattle", "PL005432198765")

        with pytest.raises(ValidationError, match="jest już"):
            create_animal(request=request, farm_id=farm.id, data={"national_id": "PL005432198765"})
        with pytest.raises(ValidationError, match="gatunek"):
            create_animal(
                request=request,
                farm_id=farm.id,
                data={"national_id": "PL123456789012", "species": "sheep"},
            )
        with pytest.raises(ValidationError, match="formatu"):
            create_animal(request=request, farm_id=farm.id, data={"national_id": "krowa"})

        update_animal(request=request, animal_id=animal.id, data={"status": "sold"})
        assert get_farm(farm.id).animal_count == 1
        assert [item.status for item in list_animals(search="8765")] == ["sold"]
        assert [item.name for item in list_animals(search="luna")] == ["LUNA"]


def test_another_organizations_farm_is_simply_not_found() -> None:
    """Not a 403: the answer to "that is not yours" must not confirm it exists."""
    from saas_core.modules.shared.farms.models import Animal  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        get_farm,
    )

    first = membership("rejestr-a")
    second = membership("rejestr-b")
    with tenant(first) as request:
        farm = create_farm(request=request, data={"name": "Cudze"})

    with tenant(second) as request:
        with pytest.raises(NotFound):
            get_farm(farm.id)
        with pytest.raises(NotFound):
            create_animal(request=request, farm_id=farm.id, data={"national_id": "PL1234567"})

    # The database guard is the second line: a row pointing at another
    # organization's farm is refused even when the code above is bypassed.
    with pytest.raises(IntegrityError), transaction.atomic():
        Animal.all_objects.create(
            organization_id=second.organization_id, farm_id=farm.id, national_id="PL7654321"
        )


def test_the_register_is_closed_without_its_entitlement() -> None:
    from saas_core.modules.shared.farms.services import list_farms  # noqa: PLC0415

    member = membership("bez-rejestru", entitled=False)
    with tenant(member), pytest.raises(EntitlementRequired):
        list_farms()


def test_a_cow_found_in_the_barn_is_resolved_or_recorded_once() -> None:
    from saas_core.modules.shared.farms.api import farm_animals, resolve_animal  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415

    member = membership("obora")
    with tenant(member) as request:
        farm = create_farm(request=request, data={"name": "Obora"})
        first, created = resolve_animal(
            request=request,
            organization_id=member.organization_id,
            farm_id=farm.id,
            national_id="pl 005 432 198 999",
        )
        again, created_again = resolve_animal(
            request=request,
            organization_id=member.organization_id,
            farm_id=farm.id,
            national_id="PL005432198999",
        )
        assert (created, created_again, again.id) == (True, False, first.id)
        with pytest.raises(ValidationError, match="formatu"):
            resolve_animal(
                request=request,
                organization_id=member.organization_id,
                farm_id=farm.id,
                national_id="krowa",
            )
        assert [a.national_id for a in farm_animals(member.organization_id, farm.id)] == [
            "PL005432198999"
        ]


def test_a_farmer_takes_the_herd_over_with_the_companys_code_and_can_revoke_it() -> None:
    """ADR-051: the card becomes the farmer's farm, the company keeps its copy."""
    from saas_core.modules.shared.farms.models import (  # noqa: PLC0415
        FarmActivationCode,
        ShareStatus,
    )
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
        list_farms,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        Conflict,
        issue_activation_code,
        list_shares,
        redeem_activation_code,
        revoke_share,
        share_for_writing,
    )

    company = membership("firma-korekcja")
    farmer = membership("rolnik")
    with tenant(company) as request:
        card = create_farm(
            request=request,
            data={
                "name": "Gospodarstwo Nowak",
                "herd_number": "PL012345678-001",
                "keeper_name": "Jan Nowak",
                "notes": "brama od strony pola",
            },
        )
        for tag in ("PL005432198765", "PL005432198766"):
            create_animal(request=request, farm_id=card.id, data={"national_id": tag})
        code, expires_at = issue_activation_code(request=request, farm_id=card.id)
        first_digest = FarmActivationCode.objects.get(farm_id=card.id).token_digest
        # A second code invalidates the first: a printed code is a way in.
        code, _ = issue_activation_code(request=request, farm_id=card.id)
        assert not FarmActivationCode.objects.filter(token_digest=first_digest).exists()
        with pytest.raises(ValidationError, match="tej samej organizacji"):
            redeem_activation_code(request=request, code=code)

    with tenant(farmer) as request:
        with pytest.raises(ValidationError, match="nieprawid"):
            redeem_activation_code(request=request, code="AAAA-BBBB-CCCC-DDDD")
        # Typed the way a farmer types it: lower case, no dashes.
        taken = redeem_activation_code(request=request, code=code.replace("-", "").lower())
        assert (taken["created"], taken["animals_added"]) == (True, 2)
        farm = taken["farm"]
        assert farm.herd_number == card.herd_number
        assert farm.notes == ""  # the company's private note stays with the company
        assert len(list_animals(farm_id=farm.id)) == 2
        with pytest.raises(ValidationError, match="nieprawid"):
            redeem_activation_code(request=request, code=code)
        (share,) = list_shares(farm_id=farm.id)
        assert (share.status, share.can_write_herd) == (ShareStatus.ACTIVE, True)
        # Each side is told who the other one is, not just its id.
        assert (share.partner_name, share.partner_is_company) == ("firma-korekcja", True)

    with tenant(company) as request:
        # Each side sees its own side of the sharing, and only its own farms.
        assert [item.id for item in list_farms()] == [card.id]
        (company_side,) = list_shares(farm_id=card.id)
        assert company_side.id == share.id
        assert (company_side.partner_name, company_side.partner_is_company) == ("rolnik", False)
        assert share_for_writing(company.organization_id, card.id) is not None
        with pytest.raises(Conflict, match="połączone"):
            issue_activation_code(request=request, farm_id=card.id)

    with tenant(farmer) as request:
        revoked = revoke_share(request=request, share_id=share.id)
        assert revoked.status == ShareStatus.REVOKED
        assert revoked.partner_name == "firma-korekcja"
        assert revoke_share(request=request, share_id=share.id).revoked_at == revoked.revoked_at

    with tenant(company):
        # The card stays, the writing door closes.
        assert [item.id for item in list_farms()] == [card.id]
        assert share_for_writing(company.organization_id, card.id) is None
    assert expires_at > timezone.now()


def test_a_share_belongs_to_the_two_it_names() -> None:
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        list_shares,
        redeem_activation_code,
        revoke_share,
    )

    company = membership("firma-obca")
    farmer = membership("rolnik-obcy")
    stranger = membership("ktos-inny")
    with tenant(company) as request:
        card = create_farm(request=request, data={"name": "Ferma", "herd_number": "PL999888777"})
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
    with tenant(stranger) as request:
        assert list_shares(farm_id=taken["farm"].id) == []
        assert list_shares(farm_id=card.id) == []
        with pytest.raises(NotFound):
            revoke_share(request=request, share_id=taken["share"].id)
    # The company holds the card, not the register: it cannot revoke for the farmer.
    with tenant(company) as request, pytest.raises(NotFound):
        revoke_share(request=request, share_id=taken["share"].id)
