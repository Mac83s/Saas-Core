"""The price list (ADR-072 §6, phase 3a): prices of offers, groups and units,
which one applies, who comes, and what a company with prices may not change."""

from __future__ import annotations

from datetime import date, time
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.core.cache import cache
from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.core.organizations.services import update_current_organization
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.booking.item_translations import (
    list_item_translations,
    save_item_translation,
)
from saas_core.modules.shared.booking.models import (
    BookingSetupMutation,
    ParticipantCategory,
    PriceRule,
)
from saas_core.modules.shared.booking.prices import (
    amounts_are_gross,
    copy_prices_to_next_year,
    delete_price,
    list_prices,
    price_for,
    save_category,
    save_extra,
    save_price,
)
from saas_core.modules.shared.booking.services import (
    BookingIdempotencyConflict,
    BookingVersionConflict,
)
from saas_core.modules.shared.booking.setup import save_group, save_resource, save_service
from test_booking import catalog, membership, tenant
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable, member_of
from test_tenant_context import authenticated_client

pytestmark = pytest.mark.django_db

PRICING = "pricing.entry"


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    # Logins are throttled per client address, and the API tests log in.
    cache.clear()


def key() -> str:
    return str(uuid4())


def price(amount: int, basis: str = "per_booking", **given: Any) -> dict[str, Any]:
    return {"basis": basis, "amount_minor": amount, **given}


def season(starts: str, ends: str) -> dict[str, date]:
    return {"starts_on": date.fromisoformat(starts), "ends_on": date.fromisoformat(ends)}


def add(amount: int, basis: str = "per_booking", **given: Any) -> PriceRule:
    return save_price(
        price_id=None, data=price(amount, basis, **given), idempotency_key=key()
    ).value


def cottages(owner: Any) -> dict[str, Any]:
    """An offer booked by nights in a group of units, and one of its units."""
    configured = catalog(owner)
    with tenant(owner):
        group = save_group(group_id=None, data={"name": "Domek"}, idempotency_key=key()).value
        unit = save_resource(
            resource_id=configured["resource"].id,
            data={"group_id": group.id},
            expected_version=1,
            idempotency_key=key(),
        ).value
        stay = save_service(
            service_id=None,
            data={
                "name": "Nocleg w domku",
                "time_model": "range",
                "range_unit": "night",
                "group_ids": [group.id],
            },
            idempotency_key=key(),
        ).value.service
    return {**configured, "group": group, "unit": unit, "stay": stay}


def refused(data: dict[str, Any]) -> tuple[str, str]:
    with pytest.raises(ValidationError) as error:
        save_price(price_id=None, data=data, idempotency_key=key())
    codes = error.value.get_codes()
    assert isinstance(codes, dict) and len(codes) == 1, codes
    ((field, found),) = codes.items()
    return field, str(found[0] if isinstance(found, list) else found)


def test_a_price_is_a_setup_write_in_the_companys_currency() -> None:
    owner = membership("ceny-zapis")
    service = catalog(owner)["service"]
    with tenant(owner):
        looked = save_price(price_id=None, data=price(12000, service_id=service.id), preview=True)
        assert (looked.created, looked.value.currency) == (True, "PLN")
        assert not PriceRule.all_objects.filter(organization=owner.organization).exists()

        made = save_price(
            price_id=None, data=price(12000, service_id=service.id), idempotency_key="cena-1"
        )
        again = save_price(
            price_id=None, data=price(12000, service_id=service.id), idempotency_key="cena-1"
        )
        with pytest.raises(BookingIdempotencyConflict):
            save_price(
                price_id=None, data=price(15000, service_id=service.id), idempotency_key="cena-1"
            )
        assert (again.item_id, again.replayed) == (made.item_id, True)
        assert (made.value.vat_code, made.value.currency, made.version) == ("23", "PLN", 1)

        changed = save_price(
            price_id=made.item_id,
            data={"amount_minor": 15000, "vat_code": "8"},
            expected_version=1,
            idempotency_key=key(),
        )
        assert changed.changes == {
            "amount_minor": {"from": 12000, "to": 15000},
            "vat_code": {"from": "23", "to": "8"},
        }
        with pytest.raises(BookingVersionConflict):
            save_price(
                price_id=made.item_id,
                data={"amount_minor": 1},
                expected_version=1,
                idempotency_key=key(),
            )
        assert [item.amount_minor for item in list_prices()] == [15000]
        delete_price(price_id=made.item_id, expected_version=2, idempotency_key=key())
        assert list_prices() == []
        # The key that made it answers about a price that is gone: 404, not a crash.
        with pytest.raises(NotFound):
            save_price(
                price_id=None, data=price(12000, service_id=service.id), idempotency_key="cena-1"
            )
    assert sorted(
        BookingSetupMutation.all_objects.filter(organization=owner.organization).values_list(
            "action", flat=True
        )
    ) == ["price.create", "price.delete", "price.update"]
    assert (
        OrganizationAuditEntry.objects.filter(
            organization=owner.organization, action="booking.price.changed"
        ).count()
        == 3
    )


def test_one_price_applies_on_a_day_and_at_an_hour() -> None:
    owner = membership("ceny-pierwszenstwo")
    configured = cottages(owner)
    stay, group, unit = configured["stay"], configured["group"], configured["unit"]
    summer = season("2027-07-01", "2027-08-31")
    with tenant(owner):
        base = add(30000, "per_time_unit", service_id=stay.id)
        weekend = add(40000, "per_time_unit", service_id=stay.id, weekdays=[5, 4, 4])
        high = add(50000, "per_time_unit", service_id=stay.id, **summer)
        high_weekend = add(60000, "per_time_unit", service_id=stay.id, weekdays=[4, 5], **summer)
        add(99900, "per_time_unit", service_id=stay.id, active=False, **summer)
        evening = add(
            20000, service_id=configured["service"].id, local_from=time(17), local_to=time(21)
        )
        visit = add(15000, service_id=configured["service"].id)
        rules = list(PriceRule.all_objects.filter(organization=owner.organization))
    assert weekend.weekdays == [4, 5]

    def nightly(day: str, **scope: UUID) -> PriceRule | None:
        return price_for(rules, day=date.fromisoformat(day), service_id=stay.id, **scope)

    # 2027-06-08 is a Tuesday, 2027-06-12 a Saturday; July likewise.
    assert nightly("2027-06-08") == base
    assert nightly("2027-06-12") == weekend
    # A season beats a weekend that has no dates; the season's own weekend beats both.
    assert nightly("2027-07-06") == high
    assert nightly("2027-07-10") == high_weekend

    with tenant(owner):
        grouped = add(35000, "per_time_unit", group_id=group.id)
        own = add(70000, "per_time_unit", resource_id=unit.id, **season("2027-07-10", "2027-07-10"))
        rules = list(PriceRule.all_objects.filter(organization=owner.organization))
    # A price for some days only beats a base price, whoever it is for: the
    # offer's July over the group's base, its weekend over it in June (75b).
    assert nightly("2027-07-06", group_id=group.id, resource_id=unit.id) == high
    assert nightly("2027-06-12", group_id=group.id, resource_id=unit.id) == weekend
    # Between two base prices, and between two for some days only, the unit's
    # over its group's over the offer's.
    assert nightly("2027-06-08", group_id=group.id, resource_id=unit.id) == grouped
    assert nightly("2027-07-10", group_id=group.id, resource_id=unit.id) == own
    assert nightly("2027-07-10") == high_weekend

    def of_visit(at: time | None) -> PriceRule | None:
        return price_for(rules, day=date(2027, 6, 8), at=at, service_id=configured["service"].id)

    assert of_visit(time(18)) == evening
    assert of_visit(time(21)) == visit
    assert of_visit(None) == visit
    assert price_for(rules, day=date(2027, 6, 8), service_id=uuid4()) is None


def test_a_price_is_checked_before_it_is_kept() -> None:
    owner = membership("ceny-odmowy")
    other = membership("ceny-obca")
    configured = cottages(owner)
    visit, stay = configured["service"].id, configured["stay"].id
    foreign = catalog(other)["service"].id
    with tenant(other):
        foreign_category = save_category(
            category_id=None, data={"name": "Dziecko"}, idempotency_key=key()
        ).item_id
    with tenant(owner):
        child = save_category(
            category_id=None, data={"name": "Dziecko"}, idempotency_key=key()
        ).item_id
        for data, expected in (
            (price(100), ("service_id", "one_scope")),
            (
                price(100, service_id=visit, group_id=configured["group"].id),
                ("service_id", "one_scope"),
            ),
            (price(100, service_id=foreign), ("service_id", "invalid")),
            (
                price(100, service_id=visit, starts_on=date(2027, 7, 1)),
                ("ends_on", "required"),
            ),
            (
                price(100, service_id=visit, **season("2027-08-01", "2027-07-01")),
                ("ends_on", "end_before_start"),
            ),
            (price(100, service_id=visit, local_to=time(12)), ("local_from", "required")),
            (
                price(100, service_id=visit, local_from=time(12), local_to=time(12)),
                ("local_to", "end_before_start"),
            ),
            (price(100, "per_time_unit", service_id=visit), ("basis", "basis_needs_time_unit")),
            (
                price(100, "per_person", service_id=visit, included_people=2),
                ("included_people", "not_for_this_basis"),
            ),
            (
                price(100, service_id=visit, extra_person_amount_minor=50),
                ("included_people", "included_people_required"),
            ),
            # Who is beyond the included pays what the owner said, 0 too — never a guess.
            (
                price(100, service_id=visit, included_people=2),
                ("extra_person_amount_minor", "required"),
            ),
            # Asked for a price charged once, the flag is refused, not dropped.
            (
                price(100, service_id=visit, extra_person_per_time_unit=True),
                ("extra_person_per_time_unit", "not_for_this_basis"),
            ),
            (
                price(
                    100,
                    "per_time_unit",
                    service_id=stay,
                    length_discounts=[
                        {"min_length": 3, "percent": 20},
                        {"min_length": 7, "percent": 10},
                    ],
                ),
                ("length_discounts", "discount_must_grow"),
            ),
            (
                price(100, service_id=visit, length_discounts=[{"min_length": 7, "percent": 10}]),
                ("length_discounts", "not_for_this_basis"),
            ),
            (
                price(
                    100,
                    "per_time_unit",
                    service_id=stay,
                    length_discounts=[
                        {"min_length": 7, "percent": 10},
                        {"min_length": 7, "percent": 15},
                    ],
                ),
                ("length_discounts", "duplicate"),
            ),
            (
                price(
                    100,
                    service_id=visit,
                    category_prices=[
                        {"category_id": child, "amount_minor": 1},
                        {"category_id": child, "amount_minor": 2},
                    ],
                ),
                ("category_prices", "duplicate"),
            ),
            (
                price(
                    100,
                    service_id=visit,
                    category_prices=[{"category_id": foreign_category, "amount_minor": 1}],
                ),
                ("category_prices", "invalid"),
            ),
        ):
            assert refused(data) == expected, data

        kept = add(
            40000,
            "per_time_unit",
            service_id=stay,
            included_people=4,
            extra_person_amount_minor=5000,
            extra_person_per_time_unit=True,
            category_prices=[{"category_id": child, "amount_minor": 2500}],
            length_discounts=[{"min_length": 14, "percent": 15}, {"min_length": 7, "percent": 10}],
        )
        # A change of who pays what goes to the history without the ids.
        changed = save_price(
            price_id=kept.id,
            data={"category_prices": [], "length_discounts": kept.length_discounts},
            expected_version=1,
            idempotency_key=key(),
        )
    assert kept.category_prices == [{"category_id": str(child), "amount_minor": 2500}]
    assert kept.length_discounts == [
        {"min_length": 7, "percent": 10},
        {"min_length": 14, "percent": 15},
    ]
    assert changed.changes == {"category_prices": {"changed": True}}
    assert PriceRule.all_objects.filter(organization=owner.organization).count() == 1
    with tenant(owner):
        # „Za każdą noc” stays as the owner saved it, also with no extra-person
        # amount: it says how a category pays (a dog, per night).
        nightly = add(
            30000,
            "per_time_unit",
            service_id=stay,
            extra_person_per_time_unit=True,
            category_prices=[{"category_id": child, "amount_minor": 2000}],
        )
        free = add(40000, service_id=visit, included_people=2, extra_person_amount_minor=0)
    assert nightly.extra_person_per_time_unit is True
    assert (free.included_people, free.extra_person_amount_minor) == (2, 0)


def test_a_years_season_prices_copy_to_the_next_and_base_prices_stay() -> None:
    owner = membership("ceny-kopia")
    stay = cottages(owner)["stay"]
    with tenant(owner):
        add(30000, "per_time_unit", service_id=stay.id)
        add(50000, "per_time_unit", service_id=stay.id, **season("2028-02-29", "2028-03-10"))
        assert len(copy_prices_to_next_year(year=2028, preview=True).value) == 1
        copy_prices_to_next_year(year=2028, idempotency_key="ceny-2028")
        copy_prices_to_next_year(year=2028, idempotency_key="ceny-2028")
    dated = PriceRule.all_objects.filter(
        organization=owner.organization, starts_on__isnull=False
    ).order_by("starts_on")
    assert [(item.starts_on, item.ends_on, item.amount_minor) for item in dated] == [
        (date(2028, 2, 29), date(2028, 3, 10), 50000),
        (date(2029, 2, 28), date(2029, 3, 10), 50000),
    ]
    assert PriceRule.all_objects.filter(organization=owner.organization).count() == 3


def test_a_category_is_named_once_switched_off_and_said_in_other_languages() -> None:
    owner = membership("ceny-kategorie")
    type(owner.organization).objects.filter(pk=owner.organization_id).update(
        public_locales=["pl", "en"]
    )
    with tenant(owner):
        child = save_category(
            category_id=None, data={"name": " Dziecko "}, idempotency_key=key()
        ).value
        dog = save_category(
            category_id=None,
            data={"name": "Pies", "counts_towards_capacity": False},
            idempotency_key=key(),
        ).value
        with pytest.raises(ValidationError) as taken:
            save_category(category_id=None, data={"name": "dziecko"}, idempotency_key=key())
        off = save_category(
            category_id=dog.id, data={"active": False}, expected_version=1, idempotency_key=key()
        )
        save_item_translation(
            kind="participant_category",
            item_id=child.id,
            locale="en",
            texts={"name": "Child"},
            expected_version=0,
            idempotency_key=key(),
        )
        _entry, _item, _own, rows = list_item_translations("participant_category", child.id)
    assert (child.name, child.counts_towards_capacity) == ("Dziecko", True)
    assert taken.value.get_codes() == {"name": ["name_taken"]}
    assert (off.value.active, off.version, off.changes) == (
        False,
        2,
        {"active": {"from": True, "to": False}},
    )
    assert [(code, row.texts if row else None) for code, row in rows] == [("en", {"name": "Child"})]
    assert ParticipantCategory.all_objects.filter(organization=owner.organization).count() == 2


def test_gross_or_net_is_the_companys_setting_and_a_change_names_the_prices() -> None:
    owner = membership("ceny-brutto")
    service = catalog(owner)["service"]
    with tenant(owner):
        assert amounts_are_gross()
        version = read_group(PRICING).version
        quiet = change_settings(
            PRICING, changes={"amounts": "net"}, expected_version=version, preview=True
        )
        assert quiet.effects == ()

        add(12000, service_id=service.id)
        add(15000, service_id=service.id, **season("2027-07-01", "2027-08-31"))
        # An extra's amount is read the same way; a deposit carries no tax.
        for name, kind in (("Dojazd", "charge"), ("Kaucja", "security_deposit")):
            save_extra(
                extra_id=None,
                data={"service_id": service.id, "name": name, "amount_minor": 5000, "kind": kind},
                idempotency_key=key(),
            )
        looked = change_settings(
            PRICING, changes={"amounts": "net"}, expected_version=version, preview=True
        )
        assert amounts_are_gross()
        change_settings(
            PRICING, changes={"amounts": "net"}, expected_version=version, idempotency_key="netto"
        )
        assert not amounts_are_gross()
    (effect,) = looked.effects
    assert effect.summary["pl"] == (
        "Zmieni znaczenie 3 cen i dopłat w cenniku: kwoty zostają, a podatek będzie do nich "
        "doliczany."
    )
    assert "3 prices and extras" in effect.summary["en"]


def test_a_company_with_prices_keeps_its_currency() -> None:
    owner = membership("ceny-waluta")
    service = catalog(owner)["service"]
    with tenant(owner):
        update_current_organization(changes={"currency": "EUR", "version": 1})
        made = add(12000, service_id=service.id)
        assert made.currency == "EUR"
        with pytest.raises(ValidationError) as kept:
            update_current_organization(changes={"currency": "USD", "version": 2})
        assert kept.value.get_codes() == {"currency": ["currency_in_use"]}
        # Anything else of the company still changes.
        update_current_organization(changes={"name": "Domki nad jeziorem", "version": 2})
        delete_price(price_id=made.id, expected_version=1, idempotency_key=key())
        update_current_organization(changes={"currency": "USD", "version": 3})


def test_the_price_list_api_answers_management() -> None:
    _, owner, client = authenticated_member(
        email="ceny-api@example.test", role_key="owner", slug="ceny-api"
    )
    bookable(owner.organization)
    configured = catalog(owner)
    csrf = csrf_value(client)

    def headers() -> dict[str, str]:
        return {"HTTP_X_CSRFTOKEN": csrf, "HTTP_IDEMPOTENCY_KEY": key()}

    child = client.post(
        "/api/v1/booking/setup/participant-categories/",
        {"name": "Dziecko"},
        format="json",
        **headers(),
    )
    assert child.status_code == 201, child.data
    body = {
        "name": "Cennik podstawowy",
        "service_id": str(configured["service"].id),
        "basis": "per_booking",
        "amount_minor": 12000,
        "category_prices": [{"category_id": child.json()["id"], "amount_minor": 6000}],
    }
    keyless = client.post(
        "/api/v1/booking/setup/prices/", body, format="json", HTTP_X_CSRFTOKEN=csrf
    )
    assert keyless.status_code == 400
    made = client.post("/api/v1/booking/setup/prices/", body, format="json", **headers())
    assert made.status_code == 201, made.data
    assert (made.json()["currency"], made.json()["vat_code"], made.json()["version"]) == (
        "PLN",
        "23",
        1,
    )
    url = f"/api/v1/booking/setup/prices/{made.json()['id']}/"

    wrong = client.post(
        "/api/v1/booking/setup/prices/preview/",
        {**body, "basis": "per_time_unit"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert wrong.status_code == 400
    assert [(error["field"], error["code"]) for error in wrong.json()["errors"]] == [
        ("basis", "basis_needs_time_unit")
    ]
    preview = client.post(
        f"{url}preview/",
        {"amount_minor": 13000, "expected_version": 1},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert preview.json()["changes"] == {"amount_minor": {"from": 12000, "to": 13000}}

    listed = client.get("/api/v1/booking/setup/prices/").json()
    assert listed["amounts"] == "gross"
    assert [(item["name"], item["amount_minor"]) for item in listed["items"]] == [
        ("Cennik podstawowy", 12000)
    ]
    assert [
        item["name"]
        for item in client.get("/api/v1/booking/setup/participant-categories/").json()["items"]
    ] == ["Dziecko"]
    renamed = client.patch(
        f"/api/v1/booking/setup/participant-categories/{child.json()['id']}/",
        {"name": "Dziecko do 12 lat", "expected_version": 1},
        format="json",
        **headers(),
    )
    assert (renamed.status_code, renamed.json()["version"]) == (200, 2)

    copy = client.post(
        "/api/v1/booking/setup/prices/copy-year/", {"year": 2027}, format="json", **headers()
    )
    assert (copy.status_code, copy.json()["count"]) == (201, 0)
    assert client.delete(url, **headers()).status_code == 400
    assert client.delete(f"{url}?expected_version=1", **headers()).status_code == 204

    worker = authenticated_client(member_of(owner, "ceny-pracownik@example.test", "staff"))
    assert worker.get("/api/v1/booking/setup/prices/").status_code == 403
    assert worker.get("/api/v1/booking/setup/participant-categories/").status_code == 403
