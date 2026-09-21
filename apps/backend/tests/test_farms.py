"""The farm register (`shared.farms`, ADR-051).

Skipped where the profile does not compose the module. In Saas-Core the main
profile is `agro`, so these run in the default suite; in a product repository
they run under any profile that composes the register.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest import mock
from uuid import UUID

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from psycopg import sql
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditAction,
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


def link_for_schedule(
    company: Membership, farmer: Membership, registry_farm_id: UUID, *, schedule: bool = True
) -> Any:
    """Karta firmy połączona z gospodarstwem rolnika, ze zgodą na grafik lub bez.

    Łączy obsługa, nie kod aktywacyjny: kod zakłada rolnikowi nowe gospodarstwo,
    a tutaj dwie firmy mają trafić do tego samego. Zgodę ustawia wprost na
    wierszu, bo żaden przypadek użycia jej dziś nie przełącza.
    """
    from saas_core.modules.shared.farms.models import FarmShare  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415
    from saas_core.modules.shared.farms.sharing import link_without_code  # noqa: PLC0415

    with tenant(company) as request:
        card = create_farm(request=request, data={"name": "Karta gospodarstwa"})
    share = link_without_code(
        operator_id=company.user_id,
        company_organization_id=company.organization_id,
        company_farm_id=card.id,
        registry_organization_id=farmer.organization_id,
        registry_farm_id=registry_farm_id,
    )
    FarmShare.objects.filter(pk=share.pk).update(can_publish_schedule=schedule)
    share.can_publish_schedule = schedule
    return card, share


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

    with tenant(company) as request:
        # The card stays, the writing door closes — and the company may hand
        # out a code again, because nothing links the farm any more.
        assert [item.id for item in list_farms()] == [card.id]
        assert share_for_writing(company.organization_id, card.id) is None
        code, _ = issue_activation_code(request=request, farm_id=card.id)

    with tenant(farmer) as request:
        # Linking again revives the same share; the pair is unique.
        again = redeem_activation_code(request=request, code=code)
        assert (again["created"], again["animals_added"]) == (False, 0)
        assert again["share"].id == share.id
        assert (again["share"].status, again["share"].revoked_at) == (ShareStatus.ACTIVE, None)
        assert again["share"].partner_name == "firma-korekcja"
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


def test_the_code_carries_the_handover_so_the_farmer_reads_nothing_of_the_company() -> None:
    """The farmer redeems inside their own tenant, where row-level security
    hides the company's rows — so the card travels in the code itself."""
    from saas_core.modules.shared.farms.models import Animal, Farm  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        redeem_activation_code,
    )

    company = membership("firma-znika")
    farmer = membership("rolnik-po-firmie")
    with tenant(company) as request:
        card = create_farm(
            request=request,
            data={"name": "Gospodarstwo Znikające", "herd_number": "PL099999999-001"},
        )
        create_animal(request=request, farm_id=card.id, data={"national_id": "PL005432190001"})
        code, _ = issue_activation_code(request=request, farm_id=card.id)
        # Whatever happens to the card afterwards, the code still hands over
        # what the company agreed to give.
        Animal.all_objects.filter(farm=card).delete()
        Farm.all_objects.filter(pk=card.id).delete()

    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        assert (taken["created"], taken["animals_added"]) == (True, 1)
        assert taken["farm"].herd_number == "PL099999999001"  # canonical form
        assert taken["share"].company_name == "firma-znika"
        assert taken["share"].registry_name == "rolnik-po-firmie"
        assert [animal.national_id for animal in list_animals(farm_id=taken["farm"].id)] == [
            "PL005432190001"
        ]


def test_a_shared_card_writes_the_cow_into_the_farmers_register() -> None:
    """ADR-051 pt 7: the register is the source of truth, so the company's
    entries land there too — and only while the farmer allows it."""
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
        update_animal,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        redeem_activation_code,
        revoke_share,
    )

    company = membership("firma-sync")
    farmer = membership("rolnik-sync")
    with tenant(company) as request:
        card = create_farm(
            request=request, data={"name": "Gospodarstwo Sync", "herd_number": "PL088888888-001"}
        )
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        registry_farm = taken["farm"]
        share = taken["share"]

    with tenant(company) as request:
        cow = create_animal(
            request=request,
            farm_id=card.id,
            data={"national_id": "PL005432177001", "working_number": "12"},
        )
        # The rest of the company's work still runs as the company: the door
        # restores the caller's organization, `SET LOCAL` outlives the block.
        assert [animal.id for animal in list_animals(farm_id=card.id)] == [cow.id]
        update_animal(request=request, animal_id=cow.id, data={"status": "sold"})

    with tenant(farmer):
        (mirrored,) = list_animals(farm_id=registry_farm.id)
        assert (mirrored.national_id, mirrored.working_number) == ("PL005432177001", "12")
        assert mirrored.status == "sold"

    with tenant(farmer) as request:
        revoke_share(request=request, share_id=share.id)
    with tenant(company) as request:
        create_animal(request=request, farm_id=card.id, data={"national_id": "PL005432177002"})
    with tenant(farmer):
        # Revoked means revoked: the second cow stays with the company.
        assert [animal.national_id for animal in list_animals(farm_id=registry_farm.id)] == [
            "PL005432177001"
        ]


def test_a_company_publishes_the_animals_history_into_the_farmers_register() -> None:
    """ADR-051 pt 8: the keeper reads what was done to the cow, whoever did it."""
    from datetime import date  # noqa: PLC0415

    from saas_core.modules.shared.farms.api import farm_animals  # noqa: PLC0415
    from saas_core.modules.shared.farms.herd_sync import publish_health_entry  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_health_entries,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        redeem_activation_code,
        revoke_share,
    )

    company = membership("firma-historia")
    farmer = membership("rolnik-historia")
    with tenant(company) as request:
        card = create_farm(
            request=request,
            data={"name": "Gospodarstwo Historia", "herd_number": "PL077777777-001"},
        )
        cow = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432166001"}
        )
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        registry_animal = list(farm_animals(farmer.organization_id, taken["farm"].id))[0]
        share = taken["share"]

    with tenant(company):
        published = publish_health_entry(
            animal=cow,
            occurred_on=date(2026, 9, 20),
            source="hoofcare.visit",
            reference="visit-1",
            summary="Korekcja: DD M2 na LH, kontrola za 14 dni.",
            details={"limbs": ["LH"], "lesions": ["DD"]},
        )
        assert published is not None
        # The same visit published again corrects the entry instead of adding one.
        publish_health_entry(
            animal=cow,
            occurred_on=date(2026, 9, 20),
            source="hoofcare.visit",
            reference="visit-1",
            summary="Korekcja: DD M2 na LH, kontrola za 21 dni.",
        )

    with tenant(farmer):
        (entry,) = list_health_entries(animal_id=registry_animal.id)
        assert entry.summary.endswith("kontrola za 21 dni.")
        assert entry.author_name == "firma-historia"
        assert entry.details == {}

    with tenant(farmer) as request:
        revoke_share(request=request, share_id=share.id)
    with tenant(company):
        assert (
            publish_health_entry(
                animal=cow,
                occurred_on=date(2026, 9, 21),
                source="hoofcare.visit",
                reference="visit-2",
                summary="Nie powinno trafić do rejestru.",
            )
            is None
        )
    with tenant(farmer):
        assert len(list_health_entries(animal_id=registry_animal.id)) == 1


def test_the_animals_file_is_a_feed_of_kinds_with_its_own_notes() -> None:
    """Kartoteka: wpisy różnych rodzajów, filtrowane w bazie, z autorem."""
    from datetime import date  # noqa: PLC0415

    from saas_core.modules.shared.farms.models import HealthEntryKind  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_health_entries,
        record_health_entry,
    )

    member = membership("kartoteka")
    with tenant(member) as request:
        farm = create_farm(request=request, data={"name": "Gospodarstwo Kartoteka"})
        cow = create_animal(
            request=request, farm_id=farm.id, data={"national_id": "PL005432155001"}
        )
        note = record_health_entry(
            request=request,
            animal_id=cow.id,
            data={
                "kind": HealthEntryKind.NOTE,
                "occurred_on": date(2026, 9, 10),
                "summary": "Kuleje na prawą tylną.",
            },
        )
        record_health_entry(
            request=request,
            animal_id=cow.id,
            data={
                "kind": HealthEntryKind.MEDICATION,
                "occurred_on": date(2026, 9, 12),
                "summary": "Podano antybiotyk, karencja 5 dni.",
                "details": {"withdrawal_days": 5},
                "private": True,
            },
        )
        # Feed: newest first, and the writer is the person, not the company.
        feed = list_health_entries(animal_id=cow.id)
        assert [entry.occurred_on for entry in feed] == [date(2026, 9, 12), date(2026, 9, 10)]
        assert feed[0].author_organization_name == "kartoteka"
        assert all(not entry.author_is_external for entry in feed)
        assert feed[0].source == "farms.manual"
        # Two entries written in one breath keep their own rows.
        assert feed[1].id == note.id
        # Filters run in the database, not in the panel.
        assert [entry.kind for entry in list_health_entries(
            animal_id=cow.id, kinds=[HealthEntryKind.MEDICATION]
        )] == [HealthEntryKind.MEDICATION]
        assert list_health_entries(animal_id=cow.id, since=date(2026, 9, 11)) == [feed[0]]
        assert list_health_entries(animal_id=cow.id, until=date(2026, 9, 11)) == [feed[1]]
        assert list_health_entries(animal_id=cow.id, author="others") == []


def test_a_company_reads_the_file_through_the_share_except_what_is_private() -> None:
    """ADR-051 pt 8 w drugą stronę: korektor czyta kartotekę, gdy udział żyje."""
    from datetime import date  # noqa: PLC0415

    from saas_core.modules.shared.farms.api import farm_animals  # noqa: PLC0415
    from saas_core.modules.shared.farms.herd_sync import publish_health_entry  # noqa: PLC0415
    from saas_core.modules.shared.farms.models import HealthEntryKind  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_health_entries,
        record_health_entry,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        redeem_activation_code,
        revoke_share,
    )

    company = membership("firma-czyta")
    farmer = membership("rolnik-czyta")
    with tenant(company) as request:
        card = create_farm(
            request=request, data={"name": "Gospodarstwo Czyta", "herd_number": "PL066666666-001"}
        )
        cow = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432144001"}
        )
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        (registry_cow,) = list(farm_animals(farmer.organization_id, taken["farm"].id))
        record_health_entry(
            request=request,
            animal_id=registry_cow.id,
            data={"kind": HealthEntryKind.NOTE, "summary": "Cielna, termin w maju."},
        )
        record_health_entry(
            request=request,
            animal_id=registry_cow.id,
            data={"kind": HealthEntryKind.NOTE, "summary": "Sprawa z sąsiadem.", "private": True},
        )
        share = taken["share"]

    with tenant(company):
        publish_health_entry(
            animal=cow,
            occurred_on=date(2026, 9, 20),
            source="hoofcare.visit",
            reference="wizyta-1",
            summary="Korekcja: DD M2.",
            author_name="Piotr Korektor",
        )
        feed = list_health_entries(animal_id=cow.id)
        summaries = [entry.summary for entry in feed]
        # Notatka rolnika tak, prywatna nie; własny wpis firmy też w feedzie.
        assert "Cielna, termin w maju." in summaries
        assert "Sprawa z sąsiadem." not in summaries
        assert "Korekcja: DD M2." in summaries
        keeper = next(entry for entry in feed if entry.summary.startswith("Cielna"))
        assert keeper.author_is_external is True
        assert keeper.author_organization_name == "rolnik-czyta"
        # Wpis z rejestru wraca pod identyfikatorem zwierzęcia firmy.
        assert {entry.animal_id for entry in feed} == {cow.id}
        # Autor publikacji to osoba, nie firma; nazwa firmy obok.
        published = next(entry for entry in feed if entry.summary.startswith("Korekcja"))
        assert (published.author_name, published.author_organization_name) == (
            "Piotr Korektor",
            "firma-czyta",
        )
        assert published.kind == HealthEntryKind.TREATMENT

    with tenant(farmer) as request:
        revoke_share(request=request, share_id=share.id)
    with tenant(company):
        # Cofnięty udział zamyka drzwi także dla odczytu.
        assert [entry.summary for entry in list_health_entries(animal_id=cow.id)] == []


def test_what_a_company_writes_waits_for_the_keeper_to_look_at_it() -> None:
    """Nic nie kasujemy: rozjazd to znacznik, a decyzja należy do hodowcy."""
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
        update_animal,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        redeem_activation_code,
    )

    company = membership("firma-rozjazd")
    farmer = membership("rolnik-rozjazd")
    with tenant(company) as request:
        card = create_farm(
            request=request, data={"name": "Gospodarstwo Rozjazd", "herd_number": "PL055555555-001"}
        )
        create_animal(request=request, farm_id=card.id, data={"national_id": "PL005432133001"})
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        registry_farm = taken["farm"]
        # Stado przejęte kodem też czeka na przejrzenie: to cudzy obraz stada.
        (first,) = list_animals(farm_id=registry_farm.id, review=True)
        assert first.national_id == "PL005432133001"
        update_animal(request=request, animal_id=first.id, data={"reviewed": True})
        assert list_animals(farm_id=registry_farm.id, review=True) == []

    with tenant(company) as request:
        second = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432133002"}
        )
    with tenant(farmer):
        # Nowa sztuka od firmy wraca na listę do przejrzenia.
        assert [animal.national_id for animal in list_animals(
            farm_id=registry_farm.id, review=True
        )] == ["PL005432133002"]

    with tenant(company) as request:
        # Zapis bez zmiany niczego nie zgłasza: wizyta co miesiąc nie może
        # zasypać hodowcy tymi samymi czterdziestoma krowami.
        update_animal(request=request, animal_id=second.id, data={"working_number": ""})
    with tenant(farmer) as request:
        (pending,) = list_animals(farm_id=registry_farm.id, review=True)
        update_animal(request=request, animal_id=pending.id, data={"reviewed": True})
        assert list_animals(farm_id=registry_farm.id, review=True) == []
    with tenant(company) as request:
        update_animal(request=request, animal_id=second.id, data={"status": "sold"})
    with tenant(farmer):
        assert [animal.status for animal in list_animals(
            farm_id=registry_farm.id, review=True
        )] == ["sold"]


def test_a_company_sends_the_whole_herd_and_the_keeper_hears_about_it() -> None:
    """Domyka okno kodu: sztuki dopisane po jego wydaniu docierają do rejestru,
    a hodowca dostaje o nich jedną wiadomość, nie czterdzieści."""
    from saas_core.modules.shared.farms.herd_sync import push_herd  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
        update_animal,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        Conflict,
        issue_activation_code,
        redeem_activation_code,
    )
    from saas_core.modules.shared.farms.tasks import (  # noqa: PLC0415
        notify_pending_reviews,
    )
    from saas_core.modules.shared.notifications.models import (  # noqa: PLC0415
        AppNotification,
    )

    company = membership("firma-wysylka")
    farmer = membership("rolnik-wysylka")
    with tenant(company) as request:
        card = create_farm(
            request=request, data={"name": "Gospodarstwo Wysyłka", "herd_number": "PL044444444-001"}
        )
        create_animal(request=request, farm_id=card.id, data={"national_id": "PL005432122001"})
        code, _ = issue_activation_code(request=request, farm_id=card.id)
        # Krowa dopisana po wydaniu kodu: przekazanie jest już zamrożone.
        late = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432122002"}
        )
        # I sztuka, która wyszła ze stada — ta do rejestru nie pojedzie.
        gone = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432122003"}
        )
        update_animal(request=request, animal_id=gone.id, data={"status": "sold"})
        with pytest.raises(Conflict, match="nie jest połączone"):
            push_herd(request, farm_id=card.id)
        with pytest.raises(NotFound):
            push_herd(request, farm_id=uuid.uuid7())

    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        registry_farm = taken["farm"]
        assert [animal.national_id for animal in list_animals(farm_id=registry_farm.id)] == [
            "PL005432122001"
        ]

    with tenant(company) as request:
        assert push_herd(request, farm_id=card.id) == {
            "added": 1,
            "updated": 0,
            "unchanged": 1,
        }
        # Druga wysyłka niczego nie zmienia i nie stawia znaczników.
        assert push_herd(request, farm_id=card.id) == {
            "added": 0,
            "updated": 0,
            "unchanged": 2,
        }
        update_animal(request=request, animal_id=late.id, data={"working_number": "17"})

    with tenant(farmer):
        herd = list_animals(farm_id=registry_farm.id)
        assert sorted(animal.national_id for animal in herd) == [
            "PL005432122001",
            "PL005432122002",
        ]
        assert [animal.national_id for animal in list_animals(review=True)] == [
            "PL005432122001",
            "PL005432122002",
        ]

    # Jedna wiadomość na gospodarstwo, dla osoby, która może się tym zająć.
    assert notify_pending_reviews() == 1
    message = AppNotification.all_objects.get(organization_id=farmer.organization_id)
    assert message.kind == "farms.herd_review"
    assert message.payload["count"] == 2
    assert message.payload["farm_name"] == registry_farm.name
    # Przebieg bez nowych sztuk nie mówi nic.
    assert notify_pending_reviews() == 0


def test_support_links_a_card_without_a_code_and_the_keeper_can_revoke_it() -> None:
    """ADR-051 pkt 5: kod nie dotarł, obsługa łączy ręcznie — z audytem po obu
    stronach i bez kopiowania stada."""
    from saas_core.modules.shared.farms.models import ShareBasis, ShareStatus  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_animals,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        Conflict,
        link_without_code,
        list_shares,
        revoke_share,
    )

    company = membership("firma-wsparcie")
    farmer = membership("rolnik-wsparcie")
    operator = User.objects.create_user(email="obsluga@example.test")
    with tenant(company) as request:
        card = create_farm(request=request, data={"name": "Gospodarstwo Wsparcie"})
        create_animal(request=request, farm_id=card.id, data={"national_id": "PL005432111001"})
    with tenant(farmer) as request:
        own = create_farm(request=request, data={"name": "Moje Gospodarstwo"})

    link = dict(
        operator_id=operator.id,
        company_organization_id=company.organization_id,
        company_farm_id=card.id,
        registry_organization_id=farmer.organization_id,
        registry_farm_id=own.id,
    )
    share = link_without_code(**link)
    assert (share.basis, share.status) == (ShareBasis.SUPPORT, ShareStatus.ACTIVE)
    assert (share.company_name, share.registry_name) == ("firma-wsparcie", "rolnik-wsparcie")
    # Druga próba mówi wprost, zamiast łączyć po raz drugi.
    with pytest.raises(Conflict, match="już połączone"):
        link_without_code(**link)

    # Ślad zostaje po obu stronach, z operatorem jako sprawcą.
    granted = OrganizationAuditEntry.objects.filter(
        action=OrganizationAuditAction.FARM_SHARE_GRANTED, actor_user=operator
    )
    assert {entry.organization_id for entry in granted} == {
        company.organization_id,
        farmer.organization_id,
    }

    with tenant(farmer) as request:
        # Stado nie pojechało: to zadanie akcji „wyślij stado".
        assert list_animals(farm_id=own.id) == []
        (mine,) = list_shares(farm_id=own.id)
        assert mine.partner_name == "firma-wsparcie"
        # Połączenie bez kodu cofa się tak samo jak każde inne.
        assert revoke_share(request=request, share_id=share.id).status == ShareStatus.REVOKED


def test_a_photo_stays_with_its_author_and_is_read_through_the_entry() -> None:
    """Decyzja z 20.09: plik nie jest kopiowany, czytelnik wchodzi przez wpis."""
    from datetime import date  # noqa: PLC0415

    from saas_core.modules.shared.farms.api import farm_animals  # noqa: PLC0415
    from saas_core.modules.shared.farms.herd_sync import (  # noqa: PLC0415
        publish_health_entry,
        read_entry_photo,
    )
    from saas_core.modules.shared.farms.services import (  # noqa: PLC0415
        create_animal,
        create_farm,
        list_health_entries,
    )
    from saas_core.modules.shared.farms.sharing import (  # noqa: PLC0415
        issue_activation_code,
        redeem_activation_code,
        revoke_share,
    )

    photo_id = uuid.uuid7()
    read_by: list[tuple[UUID, UUID]] = []

    def fake_preview(*, asset_id: UUID, **_: Any) -> bytes:
        context = require_tenant_context()
        read_by.append((context.organization_id, asset_id))
        return b"webp"

    company = membership("firma-zdjecia")
    farmer = membership("rolnik-zdjecia")
    with tenant(company) as request:
        card = create_farm(
            request=request, data={"name": "Gospodarstwo Zdjęcia", "herd_number": "PL033333333-001"}
        )
        cow = create_animal(
            request=request, farm_id=card.id, data={"national_id": "PL005432199901"}
        )
        code, _ = issue_activation_code(request=request, farm_id=card.id)
    with tenant(farmer) as request:
        taken = redeem_activation_code(request=request, code=code)
        (registry_cow,) = list(farm_animals(farmer.organization_id, taken["farm"].id))
        share = taken["share"]
    with tenant(company):
        publish_health_entry(
            animal=cow,
            occurred_on=date(2026, 9, 20),
            source="hoofcare.visit",
            reference="wizyta-foto",
            summary="Korekcja: DD M2, zdjęcie racicy.",
            photos=[str(photo_id)],
        )

    with (
        tenant(farmer),
        mock.patch(
            "saas_core.modules.shared.farms.herd_sync.read_media_preview", side_effect=fake_preview
        ),
    ):
        (entry,) = list_health_entries(animal_id=registry_cow.id)
        assert [str(item) for item in entry.photos] == [str(photo_id)]
        assert read_entry_photo(entry_id=entry.id, media_id=photo_id) == b"webp"
        # Plik czytany jest w magazynie autora, nie rolnika.
        assert read_by == [(company.organization_id, photo_id)]
        # Zdjęcie spoza wpisu nie otwiera cudzego magazynu.
        with pytest.raises(NotFound):
            read_entry_photo(entry_id=entry.id, media_id=uuid.uuid7())

    with tenant(farmer) as request:
        revoke_share(request=request, share_id=share.id)
    with (
        tenant(farmer),
        mock.patch(
            "saas_core.modules.shared.farms.herd_sync.read_media_preview", side_effect=fake_preview
        ),
        pytest.raises(NotFound),
    ):
        # Cofnięty udział zamyka też zdjęcia — bez sprzątania plików.
        read_entry_photo(entry_id=entry.id, media_id=photo_id)


def test_a_visit_reaches_the_register_only_after_the_second_consent() -> None:
    """ADR-052 pkt 4: rolnik zgadzał się na wpisy zdrowotne, nie na grafik firmy."""
    from saas_core.modules.shared.farms.herd_sync import (  # noqa: PLC0415
        list_farm_visits,
        publish_farm_visit,
    )
    from saas_core.modules.shared.farms.models import FarmShare, VisitStatus  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415

    company = membership("firma-wizyty")
    farmer = membership("rolnik-wizyty")
    with tenant(farmer) as request:
        farm = create_farm(request=request, data={"name": "Gospodarstwo Wizyty"})
    with tenant(company) as request:
        lonely = create_farm(request=request, data={"name": "Karta bez rolnika"})

    visit: dict[str, Any] = {
        "source": "hoofcare.visit",
        "reference": "wizyta-1",
        "status": VisitStatus.PLANNED,
        "scheduled_for": timezone.now(),
        "summary": "Korekcja, wtorek rano.",
    }
    with tenant(company):
        # Karta, której nikt nie przejął, to zwykły przypadek, nie błąd.
        assert (
            publish_farm_visit(
                company_organization_id=company.organization_id,
                company_farm_id=lonely.id,
                **visit,
            )
            is None
        )

    card, share = link_for_schedule(company, farmer, farm.id, schedule=False)
    assert share.can_publish_health is True
    with tenant(company):
        # Zgoda na kartotekę zwierząt nie otwiera grafiku: to osobna decyzja.
        assert (
            publish_farm_visit(
                company_organization_id=company.organization_id,
                company_farm_id=card.id,
                **visit,
            )
            is None
        )

    FarmShare.objects.filter(pk=share.pk).update(can_publish_schedule=True)
    with tenant(company):
        entry = publish_farm_visit(
            company_organization_id=company.organization_id,
            company_farm_id=card.id,
            **visit,
        )
    assert entry is not None
    # Wiersz istnieje wyłącznie u rolnika i wskazuje jego gospodarstwo, nie kartę
    # firmy — kopia po stronie firmy byłaby drugim źródłem prawdy (ADR-052 pkt 2).
    assert entry.organization_id == farmer.organization_id
    assert entry.farm_id == share.registry_farm_id == farm.id
    assert entry.farm_id != card.id
    assert (entry.company_organization_id, entry.company_name) == (
        company.organization_id,
        "firma-wizyty",
    )
    with tenant(farmer):
        assert [item.id for item in list_farm_visits(farm.id)] == [entry.id]


def test_the_same_visit_is_one_row_from_planned_through_done_to_canceled() -> None:
    """ADR-052 pkt 8: odwołanie jest faktem, który hodowca ma prawo pamiętać,
    a nie zdarzeniem do wymazania — kartoteka wizyt jest księgą, nie listą."""
    from datetime import date, timedelta  # noqa: PLC0415

    from saas_core.modules.shared.farms.herd_sync import (  # noqa: PLC0415
        list_farm_visits,
        publish_farm_visit,
    )
    from saas_core.modules.shared.farms.models import VisitStatus  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415

    company = membership("firma-jeden-wiersz")
    farmer = membership("rolnik-jeden-wiersz")
    with tenant(farmer) as request:
        farm = create_farm(request=request, data={"name": "Gospodarstwo Jeden Wiersz"})
    card, _ = link_for_schedule(company, farmer, farm.id)

    same = {
        "company_organization_id": company.organization_id,
        "company_farm_id": card.id,
        "source": "hoofcare.visit",
        "reference": "wizyta-7",
    }
    with tenant(company):
        planned = publish_farm_visit(
            **same,
            status=VisitStatus.PLANNED,
            scheduled_for=timezone.now() + timedelta(days=3),
            summary="Umówiona na wtorek.",
        )
        done = publish_farm_visit(
            **same,
            status=VisitStatus.DONE,
            occurred_on=date(2026, 9, 21),
            summary="Skorygowano 12 sztuk.",
        )
        canceled = publish_farm_visit(
            **same, status=VisitStatus.CANCELED, summary="Odwołana, choroba."
        )
    assert planned is not None and done is not None and canceled is not None
    # Ten sam numer wizyty poprawia wiersz, zamiast dokładać drugi.
    assert planned.id == done.id == canceled.id
    assert (done.status, done.occurred_on) == (VisitStatus.DONE, date(2026, 9, 21))

    with tenant(farmer):
        (only,) = list_farm_visits(farm.id)
    assert (only.id, only.status, only.summary) == (
        planned.id,
        VisitStatus.CANCELED,
        "Odwołana, choroba.",
    )


def test_two_companies_in_one_farm_do_not_overwrite_each_other() -> None:
    """ADR-052 pkt 3: numery wizyt są lokalne dla firmy, więc bez firmy w kluczu
    unikalności druga z nich nadpisałaby wizytę pierwszej przez update_or_create."""
    from saas_core.modules.shared.farms.herd_sync import (  # noqa: PLC0415
        list_farm_visits,
        publish_farm_visit,
    )
    from saas_core.modules.shared.farms.models import VisitStatus  # noqa: PLC0415
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415

    first = membership("firma-pierwsza")
    second = membership("firma-druga")
    farmer = membership("rolnik-dwie-firmy")
    with tenant(farmer) as request:
        farm = create_farm(request=request, data={"name": "Gospodarstwo Dwie Firmy"})
    first_card, _ = link_for_schedule(first, farmer, farm.id)
    second_card, _ = link_for_schedule(second, farmer, farm.id)

    visit: dict[str, Any] = {
        "source": "hoofcare.visit",
        "reference": "wizyta-1",
        "status": VisitStatus.PLANNED,
        "scheduled_for": timezone.now(),
    }
    with tenant(first):
        publish_farm_visit(
            company_organization_id=first.organization_id,
            company_farm_id=first_card.id,
            summary="Korekcja u pierwszej.",
            **visit,
        )
    with tenant(second):
        publish_farm_visit(
            company_organization_id=second.organization_id,
            company_farm_id=second_card.id,
            summary="Badanie u drugiej.",
            **visit,
        )

    with tenant(farmer):
        visits = list_farm_visits(farm.id)
    assert sorted(item.summary for item in visits) == [
        "Badanie u drugiej.",
        "Korekcja u pierwszej.",
    ]
    assert {item.company_organization_id for item in visits} == {
        first.organization_id,
        second.organization_id,
    }


def test_a_revoked_share_hides_the_planned_visit_but_keeps_the_history() -> None:
    """ADR-052 pkt 9: po cofnięciu drzwi są zamknięte i nikt już nie przestawi
    statusu, więc wizyta, która się nie odbędzie, wisiałaby w przyszłości bez
    końca. Historia zostaje — ona nie zależy od dzisiejszej zgody."""
    from saas_core.modules.shared.farms.herd_sync import (  # noqa: PLC0415
        list_farm_visits,
        publish_farm_visit,
    )
    from saas_core.modules.shared.farms.models import (  # noqa: PLC0415
        FarmVisitEntry,
        VisitStatus,
    )
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415
    from saas_core.modules.shared.farms.sharing import revoke_share  # noqa: PLC0415

    company = membership("firma-cofnieta")
    farmer = membership("rolnik-cofniety")
    with tenant(farmer) as request:
        farm = create_farm(request=request, data={"name": "Gospodarstwo Cofnięte"})
    card, share = link_for_schedule(company, farmer, farm.id)

    with tenant(company):
        for reference, status, summary in (
            ("wizyta-przyszla", VisitStatus.PLANNED, "Umówiona na przyszły tydzień."),
            ("wizyta-odbyta", VisitStatus.DONE, "Skorygowano 12 sztuk."),
            ("wizyta-odwolana", VisitStatus.CANCELED, "Odwołana, choroba."),
        ):
            publish_farm_visit(
                company_organization_id=company.organization_id,
                company_farm_id=card.id,
                source="hoofcare.visit",
                reference=reference,
                status=status,
                summary=summary,
            )

    with tenant(farmer) as request:
        assert len(list_farm_visits(farm.id)) == 3
        revoke_share(request=request, share_id=share.id)
        assert sorted(item.status for item in list_farm_visits(farm.id)) == [
            VisitStatus.CANCELED,
            VisitStatus.DONE,
        ]
    # Ukrycie przy odczycie, nie zapis korygujący: wiersz stoi tam, gdzie stał.
    assert (
        FarmVisitEntry.all_objects.filter(
            organization_id=farmer.organization_id, status=VisitStatus.PLANNED
        ).count()
        == 1
    )


def test_a_visit_pointing_at_another_organizations_farm_is_refused() -> None:
    """Klucz obcy mówi, że gospodarstwo istnieje, nie czyje jest — a wiersz
    wizyty pisze gość wpuszczony drzwiami rejestru."""
    from saas_core.modules.shared.farms.models import (  # noqa: PLC0415
        FarmVisitEntry,
        VisitStatus,
    )
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415

    first = membership("rejestr-wizyt-a")
    second = membership("rejestr-wizyt-b")
    with tenant(first) as request:
        farm = create_farm(request=request, data={"name": "Cudze Gospodarstwo"})

    with pytest.raises(IntegrityError), transaction.atomic():
        FarmVisitEntry.all_objects.create(
            organization_id=second.organization_id,
            farm_id=farm.id,
            source="hoofcare.visit",
            source_reference="wizyta-obca",
            company_organization_id=uuid.uuid7(),
            status=VisitStatus.PLANNED,
        )


def test_the_visit_register_is_isolated_under_a_role_without_bypass() -> None:
    """Baza testowa łączy się właścicielem tabel, a właściciela polityki nie
    dotyczą — więc zielony test wyżej nie dowodzi izolacji. Tu polityka jest
    wykonana na prawdziwej roli bez BYPASSRLS."""
    from saas_core.modules.shared.farms.models import (  # noqa: PLC0415
        FarmVisitEntry,
        VisitStatus,
    )
    from saas_core.modules.shared.farms.services import create_farm  # noqa: PLC0415

    members = [membership(f"wizyty-rls-{index}") for index in range(2)]
    for member in members:
        with tenant(member) as request:
            farm = create_farm(request=request, data={"name": "Gospodarstwo RLS"})
            FarmVisitEntry.all_objects.create(
                organization_id=member.organization_id,
                farm=farm,
                source="hoofcare.visit",
                source_reference="wizyta-rls",
                company_organization_id=uuid.uuid7(),
                status=VisitStatus.PLANNED,
            )

    table = "farms_farmvisitentry"
    role = sql.Identifier(f"saas_core_visit_probe_{uuid.uuid4().hex}")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        try:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(table), role))
            with transaction.atomic():
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
                cursor.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
                assert cursor.fetchone() == (False, False)
                cursor.execute("SELECT set_config('app.organization_id', '', true)")
                cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
                assert cursor.fetchone() == (0,)
                counts = []
                for member in members:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)",
                        [str(member.organization_id)],
                    )
                    cursor.execute(
                        sql.SQL("SELECT organization_id FROM {}").format(sql.Identifier(table))
                    )
                    rows = cursor.fetchall()
                    assert rows == [(member.organization_id,)]
                    counts.append(len(rows))
                cursor.execute("RESET ROLE")
                print(f"FarmVisitEntry nonowner NOSUPERUSER NOBYPASSRLS: brak/A/B = {[0, *counts]}")
        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(
                sql.SQL("REVOKE SELECT ON {} FROM {}").format(sql.Identifier(table), role)
            )
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))
