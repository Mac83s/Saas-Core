"""Booking presets as a company reads and applies them (ADR-072 §10): the
contract's own order, the latest version of each, a deploy that fails when the
files did not reach the image, and an offer started from one — a switched-off
copy that remembers its origin and can be taken back while it is a draft."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from datetime import date, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.models import Organization, OrganizationAuditEntry
from saas_core.modules.shared.booking import presets
from saas_core.modules.shared.booking.apps import check_preset_contracts
from saas_core.modules.shared.booking.models import (
    BookingSetupMutation,
    Extra,
    PriceRule,
    Service,
    ServiceStaff,
)
from saas_core.modules.shared.booking.presets import apply_preset, find_preset, list_presets
from saas_core.modules.shared.booking.prices import save_extra, save_price
from saas_core.modules.shared.booking.services import BookingIdempotencyConflict
from saas_core.modules.shared.booking.setup import discard_draft, save_service
from test_booking import company_today, membership, tenant
from test_booking_slots import at, book, team
from test_organization_lifecycle import authenticated_member
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    # Logins are throttled per client address; the catalogue is read once a process.
    cache.clear()
    presets._catalogue.cache_clear()
    yield
    presets._catalogue.cache_clear()


def next_monday() -> date:
    today = company_today()
    return today + timedelta(days=7 - today.weekday())


def _manifest() -> list[str]:
    path = Path(settings.BOOKING_PRESET_CONTRACTS_PATH) / "manifest.json"
    return [entry["id"] for entry in json.loads(path.read_text(encoding="utf-8"))["presets"]]


def test_a_company_reads_the_presets_in_the_contracts_order() -> None:
    owner = membership("wzorce-lista")
    bookable(owner.organization)
    with tenant(owner):
        listed = list_presets()

    assert [item.id for item in listed] == _manifest()
    visit = listed[0]
    assert (visit.id, visit.version, visit.readiness) == ("core.specialist_visit", 1, "ready")
    assert (visit.time_model, visit.booked_subject, visit.booked_staff, visit.place) == (
        "slot",
        "staff",
        "required",
        "business",
    )
    assert visit.labels["pl"]["name"] == "Wizyta u specjalisty"
    # A visit at the company's place is booked through the site, and since the
    # public form of stays (phase 5b) so is a stay: its words no longer say
    # that the site comes later (owner decision 67a).
    assert visit.online_booking == "ready"
    lodging = next(item for item in listed if item.id == "core.lodging")
    assert (lodging.version, lodging.readiness, lodging.online_booking) == (3, "ready", "ready")
    assert "wkrótce" not in lodging.labels["pl"]["description"]
    # A visit at the customer's is still the team's to book.
    at_customer = next(item for item in listed if item.id == "core.service_at_customer")
    assert (at_customer.readiness, at_customer.online_booking) == ("ready", "soon")
    assert "wkrótce" in at_customer.labels["pl"]["description"]
    assert lodging.required_inputs == ()
    assert lodging.catalog_category == "turystyka-i-noclegi"
    assert {item.id: item.version for item in listed if item.readiness == "ready"} == {
        "core.specialist_visit": 1,
        "core.service_at_customer": 2,
        "core.lodging": 3,
        "core.rental": 3,
        "core.care_stay": 3,
    }
    # Hours are not booked yet: the preset is announced, and so not online either.
    hourly = next(item for item in listed if item.id == "core.hourly_space")
    assert (hourly.readiness, hourly.online_booking) == ("soon", "soon")


def test_the_list_is_for_whoever_sets_services_up() -> None:
    _, owner, client = authenticated_member(
        email="wzorce-api@example.test", role_key="owner", slug="wzorce-api"
    )
    bookable(owner.organization)

    answer = client.get("/api/v1/booking/presets/")

    assert answer.status_code == 200, answer.data
    listed = answer.json()["presets"]
    assert [item["id"] for item in listed] == _manifest()
    assert listed[0] == {
        "id": "core.specialist_visit",
        "version": 1,
        "readiness": "ready",
        "labels": {
            "pl": {
                "name": "Wizyta u specjalisty",
                "description": listed[0]["labels"]["pl"]["description"],
            },
            "en": {
                "name": "Appointment with a specialist",
                "description": listed[0]["labels"]["en"]["description"],
            },
        },
        "time_model": "slot",
        "booked_subject": "staff",
        "booked_staff": "required",
        "place": "business",
        "required_inputs": [],
        "catalog_category": None,
        "online_booking": "ready",
    }

    worker = authenticated_client(member_of(owner, "wzorce-pracownik@example.test", "staff"))
    assert worker.get("/api/v1/booking/presets/").status_code == 403


def _refused(preset_id: str, version: int | None) -> tuple[list[str], list[str]]:
    with pytest.raises(ValidationError) as refused:
        find_preset(preset_id, version)
    codes = refused.value.get_codes()
    assert isinstance(codes, dict)
    return list(codes), [str(code) for code in codes["preset_id"]]


def test_a_named_preset_is_found_or_refused_with_a_code_on_its_field() -> None:
    assert find_preset("core.specialist_visit", None).version == 1
    assert find_preset("core.specialist_visit", 1).id == "core.specialist_visit"
    assert _refused("core.nie_ma", None) == (["preset_id"], ["preset_unknown"])
    assert _refused("core.specialist_visit", 7) == (["preset_id"], ["preset_unknown"])
    assert _refused("core.hourly_space", None) == (["preset_id"], ["preset_not_ready"])
    # A version that was only announced stays so, whatever came after it.
    assert find_preset("core.lodging", None).version == 3
    assert _refused("core.lodging", 1) == (["preset_id"], ["preset_not_ready"])


def test_a_deploy_fails_when_the_presets_did_not_reach_the_image(tmp_path: Path) -> None:
    assert check_preset_contracts() == []

    # The manifest came, one of the versions it names did not.
    copied = tmp_path / "booking-presets"
    shutil.copytree(Path(settings.BOOKING_PRESET_CONTRACTS_PATH), copied)
    (copied / "core.lodging.v1.json").unlink()
    presets._catalogue.cache_clear()
    with override_settings(BOOKING_PRESET_CONTRACTS_PATH=copied):
        (error,) = check_preset_contracts()
    assert (error.id, error.obj) == ("booking.E010", str(copied))
    assert "core.lodging.v1.json" in error.msg

    with override_settings(BOOKING_PRESET_CONTRACTS_PATH=tmp_path / "nie-ma"):
        assert [found.id for found in check_preset_contracts()] == ["booking.E010"]


VISIT = {"preset_id": "core.specialist_visit", "name": "Konsultacja", "duration_minutes": 45}


def test_applying_a_preset_makes_a_switched_off_offer_that_remembers_its_origin() -> None:
    owner = membership("wzorce-zastosuj")
    with tenant(owner):
        looked = apply_preset(**VISIT, preview=True)
        assert (looked.created, looked.value.service.active) == (True, False)
        assert not Service.all_objects.filter(organization=owner.organization).exists()

        saved = apply_preset(**VISIT, idempotency_key="wzorzec-1")
        again = apply_preset(**VISIT, idempotency_key="wzorzec-1")
        with pytest.raises(BookingIdempotencyConflict):
            apply_preset(**{**VISIT, "name": "Inna"}, idempotency_key="wzorzec-1")

    service = Service.all_objects.get(organization=owner.organization)
    assert (again.item_id, again.replayed) == (saved.item_id, True)
    assert (service.active, service.draft, service.origin_ref) == (False, True, "")
    assert (service.preset_id, service.preset_version) == ("core.specialist_visit", 1)
    assert (service.time_model, service.duration_minutes, service.staff_count) == ("slot", 45, 1)
    assert service.vocabulary == {
        "booking": "Wizyta",
        "bookings": "Wizyty",
        "participant": "Klient",
        "participants": "Klienci",
    }
    # Nobody and no place are picked for the company.
    assert (saved.value.staff_ids, saved.value.location_ids) == ([], [])
    receipt = BookingSetupMutation.all_objects.get(organization=owner.organization)
    assert (receipt.action, receipt.result_id) == ("service.create", service.id)


def test_the_words_come_in_the_companys_first_language() -> None:
    owner = membership("wzorce-en")
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=["en", "pl"])
    with tenant(owner):
        saved = apply_preset(**VISIT, idempotency_key="wzorzec-en")
    assert saved.value.service.vocabulary["booking"] == "Appointment"


@pytest.mark.parametrize(
    ("preset_id", "unit", "start", "end", "policy"),
    [
        ("core.lodging", "night", time(16), time(11), "on_site"),
        ("core.rental", "day", time(9), time(18), "on_site"),
        ("core.care_stay", "day", time(9), time(18), "on_site"),
    ],
)
def test_a_stay_preset_makes_an_offer_the_team_books_in_the_panel(
    preset_id: str, unit: str, start: time, end: time, policy: str
) -> None:
    owner = membership(f"wzorce-{unit}-{preset_id.rpartition('.')[2].replace('_', '-')}")
    with tenant(owner):
        saved = apply_preset(preset_id=preset_id, name="Oferta", idempotency_key="okres-1")
    service = saved.value.service
    assert (service.time_model, service.range_unit) == ("range", unit)
    assert (service.range_start_local, service.range_end_local) == (start, end)
    # A stay takes a unit and nobody's time; the company adds its units itself.
    assert (service.duration_minutes, service.staff_count) == (None, 0)
    assert (saved.value.resource_ids, saved.value.group_ids) == ([], [])
    # A draft, switched off until the company has set it up — and then on the
    # public form: customers book it through the site (phase 5b).
    assert (service.active, service.draft, service.online) == (False, True, True)
    assert (service.payment_policy, service.preset_version) == (policy, 3)
    assert service.vocabulary["timeUnit"] in ("noc", "doba")
    # Prices and units are never a preset's.
    assert not PriceRule.all_objects.filter(organization=owner.organization).exists()
    assert not Extra.all_objects.filter(organization=owner.organization).exists()


def test_a_presets_prepayment_is_the_companys_own_choice_and_its_terms_come_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A preset that asks for a prepayment starts an offer in a company
    without orders or a bank account too: the policy stays the company's to
    choose in „Cennik”, with the preset's percent and days already there."""
    owner = membership("wzorce-przedplata")
    lodging = find_preset("core.lodging", None)
    monkeypatch.setitem(
        lodging.raw,
        "payment",
        {"policy": "deposit", "depositPercent": 40, "transferDueDays": 5},
    )
    with tenant(owner):
        saved = apply_preset(preset_id="core.lodging", name="Domek", idempotency_key="przedplata")
    service = saved.value.service
    assert (service.payment_policy, service.deposit_percent, service.transfer_due_days) == (
        "none",
        40,
        5,
    )


def test_a_visit_at_the_customers_keeps_travel_time_before_it() -> None:
    owner = membership("wzorce-u-klienta")
    with tenant(owner):
        saved = apply_preset(
            preset_id="core.service_at_customer",
            name="Usuwanie awarii",
            duration_minutes=60,
            idempotency_key="u-klienta-1",
        )
        visit = apply_preset(**VISIT, idempotency_key="u-klienta-2").value.service
    service = saved.value.service
    assert (service.time_model, service.duration_minutes, service.staff_count) == ("slot", 60, 1)
    # Travel is a buffer the company changes in the offer (owner decision 68a).
    assert (service.buffer_before_minutes, service.buffer_after_minutes) == (30, 0)
    assert (service.online, service.payment_policy) == (False, "on_site")
    # A visit at the company's place is as before: no buffers, in online booking.
    assert (visit.buffer_before_minutes, visit.online, visit.payment_policy) == (0, True, "none")


def test_what_a_preset_cannot_start_is_refused_on_its_field() -> None:
    owner = membership("wzorce-odmowa")
    with tenant(owner):
        for data, field, code in (
            ({**VISIT, "preset_id": "core.hourly_space"}, "preset_id", "preset_not_ready"),
            ({**VISIT, "preset_id": "core.nie_ma"}, "preset_id", "preset_unknown"),
            ({**VISIT, "duration_minutes": None}, "duration_minutes", "required"),
        ):
            with pytest.raises(ValidationError) as refused:
                apply_preset(**data, idempotency_key=f"odmowa-{code}")
            codes = refused.value.get_codes()
            assert isinstance(codes, dict)
            assert list(codes) == [field]
            assert code in str(codes[field])
    assert not Service.all_objects.filter(organization=owner.organization).exists()


def test_a_draft_is_taken_back_with_everything_it_had() -> None:
    owner = membership("wzorce-cofnij")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        draft = apply_preset(
            **VISIT,
            staff_ids=[configured["staff"][0].id],
            location_ids=[configured["location"].id],
            idempotency_key="szkic-1",
        )
        assert discard_draft(service_id=draft.item_id, preview=True).changes == {"discarded": True}
        assert Service.all_objects.filter(pk=draft.item_id).exists()

        gone = discard_draft(service_id=draft.item_id, idempotency_key="cofnij-1")
        again = discard_draft(service_id=draft.item_id, idempotency_key="cofnij-1")
        assert (gone.item_id, again.replayed) == (draft.item_id, True)
        assert not Service.all_objects.filter(pk=draft.item_id).exists()
        assert not ServiceStaff.all_objects.filter(service_id=draft.item_id).exists()
        # The key that made it makes a new draft, not an answer about one that is gone.
        anew = apply_preset(
            **VISIT,
            staff_ids=[configured["staff"][0].id],
            location_ids=[configured["location"].id],
            idempotency_key="szkic-1",
        )
        assert (anew.replayed, anew.item_id != draft.item_id) == (False, True)
    entry = OrganizationAuditEntry.objects.filter(
        organization=owner.organization, target_id=str(draft.item_id)
    ).latest("occurred_at")
    assert entry.metadata == {"changes": {"name": {"from": "Konsultacja", "to": None}}}


def _refused_discard(service_id: UUID) -> list[str]:
    with pytest.raises(ValidationError) as refused:
        discard_draft(service_id=service_id, idempotency_key=str(uuid4()))
    codes = refused.value.get_codes()
    assert isinstance(codes, dict)
    return [str(code) for code in codes["service_id"]]


def test_an_offer_that_was_ever_switched_on_is_not_discarded() -> None:
    owner = membership("wzorce-wlaczona")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    with tenant(owner):
        # What existed before drafts were kept is not one.
        assert _refused_discard(configured["service"].id) == ["not_a_draft"]

        draft = apply_preset(**VISIT, idempotency_key="szkic-2")
        on = save_service(
            service_id=draft.item_id,
            data={"active": True},
            expected_version=draft.version,
            idempotency_key="wlacz",
        )
        off = save_service(
            service_id=draft.item_id,
            data={"active": False},
            expected_version=on.version,
            idempotency_key="wylacz",
        )
        assert (on.value.service.draft, off.value.service.draft) == (False, False)
        assert _refused_discard(draft.item_id) == ["not_a_draft"]
        with pytest.raises(NotFound):
            discard_draft(service_id=uuid4(), idempotency_key="nie-ma")

    # A draft cannot be booked; if one ever had a booking, it would stay.
    book(owner, configured, at(next_monday(), 9), "szkic-z-wizyta")
    Service.all_objects.filter(pk=configured["service"].id).update(draft=True)
    with tenant(owner):
        assert _refused_discard(configured["service"].id) == ["service_has_bookings"]


def test_a_draft_with_prices_and_extras_is_taken_back_whole() -> None:
    owner = membership("wzorce-cofnij-ceny")
    with tenant(owner):
        draft = apply_preset(**VISIT, idempotency_key="szkic-ceny")
        save_price(
            price_id=None,
            data={"service_id": draft.item_id, "basis": "per_booking", "amount_minor": 12000},
            idempotency_key=str(uuid4()),
        )
        save_extra(
            extra_id=None,
            data={"service_id": draft.item_id, "name": "Dojazd", "amount_minor": 5000},
            idempotency_key=str(uuid4()),
        )
        discard_draft(service_id=draft.item_id, idempotency_key="cofnij-ceny")
    assert not Service.all_objects.filter(pk=draft.item_id).exists()
    assert not PriceRule.all_objects.filter(organization=owner.organization).exists()
    assert not Extra.all_objects.filter(organization=owner.organization).exists()
