"""Extras and deposits of an offer (ADR-072 §6, phase 3c): what an offer adds
to its price, what the customer picks, the deposit it holds, and how a quote
and a booking carry them."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.services import update_current_organization
from saas_core.modules.shared.booking.item_translations import save_item_translation
from saas_core.modules.shared.booking.models import Appointment, Extra
from saas_core.modules.shared.booking.periods import move_stay
from saas_core.modules.shared.booking.prices import list_extras, save_extra
from saas_core.modules.shared.booking.quote import Quote, quote_visit
from test_booking import catalog, membership, tenant
from test_booking_prices import add, key
from test_booking_quote import WARSAW, YEAR, day, lines, of_stay, people
from test_booking_stays import GUEST, cottages, stay
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    cache.clear()


def extra(service_id: Any, name: str, amount: int, **given: Any) -> Extra:
    return save_extra(
        extra_id=None,
        data={"service_id": service_id, "name": name, "amount_minor": amount, **given},
        idempotency_key=key(),
    ).value


def refused(**data: Any) -> list[tuple[Any, Any]]:
    with pytest.raises(ValidationError) as error:
        save_extra(extra_id=None, data=data, idempotency_key=key())
    return [(found["field"], found["code"]) for found in problem_errors(error.value)]


def picks(*chosen: tuple[Extra, int]) -> list[dict[str, Any]]:
    return [{"extra_id": item.id, "quantity": quantity} for item, quantity in chosen]


def with_extras(owner: Any) -> dict[str, Any]:
    """Cottages at 300 a night (8%) with a cleaning fee and a local tax on
    every booking, bed linen and an extra bed to pick, and a deposit."""
    setup = cottages(owner, units=1)
    offer = setup["service"].id
    with tenant(owner):
        add(
            30000,
            "per_time_unit",
            service_id=offer,
            vat_code="8",
            length_discounts=[{"min_length": 7, "percent": 10}],
        )
        made = {
            "cleaning": extra(offer, "Sprzątanie końcowe", 15000, mandatory=True),
            "tax": extra(
                offer,
                "Opłata miejscowa",
                300,
                basis="per_person_per_time_unit",
                vat_code="np",
                mandatory=True,
            ),
            "linen": extra(offer, "Pościel", 3000, basis="per_person"),
            "bed": extra(offer, "Dostawka", 2000, basis="per_time_unit", max_quantity=2),
            "deposit": extra(offer, "Kaucja", 50000, kind="security_deposit", vat_code="23"),
        }
    return {**setup, **made}


def test_an_extra_is_a_setup_item_of_its_offer() -> None:
    owner = membership("doplaty-zapis")
    setup = with_extras(owner)
    visit = catalog(owner)["service"].id
    offer = setup["service"].id
    with tenant(owner):
        # A deposit is one amount per booking, outside VAT, on every booking.
        deposit = setup["deposit"]
        assert (deposit.basis, deposit.vat_code, deposit.mandatory, deposit.currency) == (
            "per_booking",
            "np",
            True,
            "PLN",
        )
        assert refused(service_id=offer, name="pościel", amount_minor=1) == [("name", "name_taken")]
        assert refused(service_id=visit, name="Dojazd", amount_minor=1, basis="per_time_unit") == [
            ("basis", "basis_needs_time_unit")
        ]
        # The same name on another offer is another extra.
        extra(visit, "Pościel", 1000)
        off = save_extra(
            extra_id=setup["linen"].id,
            data={"active": False, "amount_minor": 3500},
            expected_version=1,
            idempotency_key=key(),
        )
        assert off.changes == {
            "amount_minor": {"from": 3000, "to": 3500},
            "active": {"from": True, "to": False},
        }
        assert len(list_extras()) == 6
        # An extra holds an amount in the company's currency too.
        with pytest.raises(ValidationError) as kept:
            update_current_organization(changes={"currency": "EUR", "version": 1})
    assert kept.value.get_codes() == {"currency": ["currency_in_use"]}


def test_a_quote_charges_the_mandatory_and_the_picked_and_names_the_deposit() -> None:
    owner = membership("doplaty-wycena")
    setup = with_extras(owner)
    with tenant(owner):
        bare = of_stay(setup, day(6, 1), day(6, 4), people(4))
        chosen = picks((setup["bed"], 2), (setup["linen"], 1))
        full = of_stay(setup, day(6, 1), day(6, 4), people(4), extras=chosen)
        week = of_stay(setup, day(6, 1), day(6, 8), people(2))
    # Three nights for four: the price, then the extras by name.
    assert lines(full) == [
        ("price", 3, 30000, 83333, 6667, 90000),
        ("extra", 6, 2000, 9756, 2244, 12000),
        ("extra", 12, 300, 3600, 0, 3600),
        ("extra", 4, 3000, 9756, 2244, 12000),
        ("extra", 1, 15000, 12195, 2805, 15000),
    ]
    assert [line.name for line in full.lines[1:]] == [
        "Dostawka",
        "Opłata miejscowa",
        "Pościel",
        "Sprzątanie końcowe",
    ]
    assert (full.net_minor, full.vat_minor, full.gross_minor) == (118640, 13960, 132600)
    # The deposit is held, not charged; the picks are kept as picked.
    assert (full.security_deposit_minor, bare.security_deposit_minor) == (50000, 50000)
    assert full.extras == (
        {"extra_id": str(setup["bed"].id), "quantity": 2},
        {"extra_id": str(setup["linen"].id), "quantity": 1},
    )
    assert [line.name for line in bare.lines] == [
        "Pobyt w domku",
        "Opłata miejscowa",
        "Sprzątanie końcowe",
    ]
    assert bare.digest != full.digest
    # The discount for a week takes 10% off the nights, never off an extra.
    assert [(line.kind, line.gross_minor) for line in week.lines] == [
        ("price", 210000),
        ("discount", -21000),
        ("extra", 4200),
        ("extra", 15000),
    ]


def test_a_pick_is_checked_and_a_booking_moved_keeps_what_it_took() -> None:
    owner = membership("doplaty-zmiany")
    setup = with_extras(owner)

    def no(party: Any, chosen: Any) -> list[tuple[Any, Any]]:
        with pytest.raises(ValidationError) as error:
            of_stay(setup, day(6, 20), day(6, 23), party, extras=chosen)
        return [(found["field"], found["code"]) for found in problem_errors(error.value)]

    with tenant(owner):
        assert no(people(2), picks((setup["bed"], 3))) == [("extras", "extra_quantity_exceeded")]
        assert no(
            people(2), [{"extra_id": "00000000-0000-7000-8000-000000000000", "quantity": 1}]
        ) == [("extras", "invalid")]

        booked = stay(
            setup,
            day(6, 1),
            day(6, 4),
            participants=people(2),
            extras=picks((setup["linen"], 1)),
        ).appointment
        assert booked.quote["extras"] == [{"extra_id": str(setup["linen"].id), "quantity": 1}]
        assert (booked.quote["security_deposit_minor"], booked.quote["gross_minor"]) == (
            50000,
            90000 + 6000 + 1800 + 15000,
        )

        # The company stops offering bed linen: a new booking cannot take it,
        # the one that did keeps it when it moves.
        save_extra(
            extra_id=setup["linen"].id,
            data={"active": False},
            expected_version=1,
            idempotency_key=key(),
        )
        assert no(people(2), picks((setup["linen"], 1))) == [("extras", "invalid")]
        moved = move_stay(
            appointment_id=booked.id,
            start_date=day(6, 10),
            end_date=day(6, 12),
            idempotency_key=key(),
            principal_ref="test",
        )
    assert isinstance(moved, Appointment)
    assert [line["name"] for line in moved.quote["lines"]] == [
        "Pobyt w domku",
        "Opłata miejscowa",
        "Pościel",
        "Sprzątanie końcowe",
    ]
    assert moved.quote["gross_minor"] == 60000 + 1200 + 6000 + 15000


def test_a_visit_takes_extras_and_the_customer_reads_them_in_their_language() -> None:
    owner = membership("doplaty-wizyta")
    type(owner.organization).objects.filter(pk=owner.organization_id).update(
        public_locales=["pl", "en"]
    )
    service = catalog(owner)["service"]
    with tenant(owner):
        travel = extra(service.id, "Dojazd", 5000, mandatory=True)
        photos = extra(service.id, "Zdjęcia", 2000, basis="per_person", max_quantity=3)
        save_item_translation(
            kind="extra",
            item_id=travel.id,
            locale="en",
            texts={"name": "Travel"},
            expected_version=0,
            idempotency_key=key(),
        )

        def priced(**given: Any) -> Quote:
            from datetime import datetime

            return quote_visit(
                service=service, starts_at=datetime(YEAR, 6, 8, 10, tzinfo=WARSAW), **given
            )

        # No price list: the extras alone make the price.
        alone = priced(participants=people(2), extras=picks((photos, 2)), locale="en")
    assert [(line.name, line.customer_name, line.quantity) for line in alone.lines] == [
        ("Dojazd", "Travel", 1),
        ("Zdjęcia", "Zdjęcia", 4),
    ]
    assert (alone.priced, alone.gross_minor) == (True, 13000)


def test_the_extras_api_and_a_booking_with_extras() -> None:
    _, owner, client = authenticated_member(
        email="doplaty-api@example.test", role_key="owner", slug="doplaty-api"
    )
    bookable(owner.organization)
    setup = cottages(owner, units=1)
    csrf = csrf_value(client)

    def headers() -> dict[str, str]:
        return {"HTTP_X_CSRFTOKEN": csrf, "HTTP_IDEMPOTENCY_KEY": key()}

    with tenant(owner):
        add(30000, "per_time_unit", service_id=setup["service"].id, vat_code="8")
    made = client.post(
        "/api/v1/booking/setup/extras/",
        {
            "service_id": str(setup["service"].id),
            "name": "Sprzątanie końcowe",
            "amount_minor": 15000,
            "mandatory": True,
        },
        format="json",
        **headers(),
    )
    assert made.status_code == 201, made.data
    assert (made.json()["kind"], made.json()["basis"], made.json()["currency"]) == (
        "charge",
        "per_booking",
        "PLN",
    )
    linen = client.post(
        "/api/v1/booking/setup/extras/",
        {
            "service_id": str(setup["service"].id),
            "name": "Pościel",
            "amount_minor": 3000,
            "basis": "per_person",
        },
        format="json",
        **headers(),
    ).json()
    preview = client.post(
        f"/api/v1/booking/setup/extras/{linen['id']}/preview/",
        {"amount_minor": 3500, "expected_version": 1},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert preview.json()["changes"] == {"amount_minor": {"from": 3000, "to": 3500}}
    assert [
        item["name"] for item in client.get("/api/v1/booking/setup/extras/").json()["items"]
    ] == [
        "Pościel",
        "Sprzątanie końcowe",
    ]

    body = {
        "service_id": str(setup["service"].id),
        "group_id": str(setup["group"].id),
        "start_date": day(6, 1).isoformat(),
        "end_date": day(6, 3).isoformat(),
        "participants": [{"count": 2}],
        "extras": [{"extra_id": linen["id"]}],
    }
    quote = client.post("/api/v1/booking/quote/", body, format="json", HTTP_X_CSRFTOKEN=csrf).json()
    assert (quote["gross_minor"], quote["security_deposit_minor"]) == (60000 + 6000 + 15000, 0)
    assert quote["extras"] == [{"extra_id": linen["id"], "quantity": 1}]
    assert [line["extra_id"] for line in quote["lines"]] == [None, linen["id"], made.json()["id"]]
    booked = client.post(
        "/api/v1/booking/stays/",
        {**body, "customer": GUEST, "quote_digest": quote["digest"]},
        format="json",
        **headers(),
    )
    assert booked.status_code == 201, booked.data
    assert booked.json()["quote"]["digest"] == quote["digest"]
