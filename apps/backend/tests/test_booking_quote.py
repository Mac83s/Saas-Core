"""One quote, frozen in the booking (ADR-072 §7, phase 3b): what a stay and a
visit cost by the price list, who of the people pays, the tax on each line, and
a booking that keeps the price it was made at."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.http.exceptions import problem_errors
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.booking.item_translations import save_item_translation
from saas_core.modules.shared.booking.models import Appointment, PriceRule
from saas_core.modules.shared.booking.periods import move_stay, plan_stay, stay_quote
from saas_core.modules.shared.booking.prices import delete_price, save_category, save_price
from saas_core.modules.shared.booking.quote import Quote, QuoteChanged, quote_offer, quote_visit
from saas_core.modules.shared.booking.rules import save_rule
from saas_core.modules.shared.booking.services import create_appointment, reschedule_appointment
from saas_core.modules.shared.booking.setup import save_resource, save_service
from test_booking import catalog, membership, tenant
from test_booking_prices import add, key, season
from test_booking_slots import team
from test_booking_stays import GUEST, cottages, stay
from test_organization_lifecycle import authenticated_member, csrf_value
from test_team_people import bookable

pytestmark = pytest.mark.django_db

WARSAW = ZoneInfo("Europe/Warsaw")
#: Next year, so the dates are ahead whenever the tests run.
YEAR = timezone.localdate().year + 1


@pytest.fixture(autouse=True)
def clear_throttles() -> None:
    cache.clear()


def day(month: int, number: int) -> date:
    return date(YEAR, month, number)


def category(name: str, **given: Any) -> Any:
    return save_category(
        category_id=None, data={"name": name, **given}, idempotency_key=key()
    ).value


def people(standard: int = 0, **others: int) -> list[dict[str, Any]]:
    """`people(2, **{str(child.id): 1})` — two standard people and a child."""
    party: list[dict[str, Any]] = [{"category_id": None, "count": standard}] if standard else []
    return party + [{"category_id": ident, "count": count} for ident, count in others.items()]


def lines(quote: Quote) -> list[tuple[str, int, int, int, int, int]]:
    return [
        (
            line.kind,
            line.quantity,
            line.unit_amount_minor,
            line.net_minor,
            line.vat_minor,
            line.gross_minor,
        )
        for line in quote.lines
    ]


def of_stay(
    setup: dict[str, Any], first: date, last: date, party: Any = None, **given: Any
) -> Quote:
    plan = plan_stay(
        service_id=setup["service"].id,
        start_date=first,
        end_date=last,
        group_id=setup["group"].id,
    )
    return stay_quote(plan, participants=party, **given)


def refused(setup: dict[str, Any], first: date, last: date, party: Any) -> list[tuple[Any, Any]]:
    with pytest.raises(ValidationError) as error:
        of_stay(setup, first, last, party)
    return [(found["field"], found["code"]) for found in problem_errors(error.value)]


def priced_cottages(owner: Any) -> dict[str, Any]:
    """Cottages for six, 300 a night for four people and 500 in July and
    August; a further person 50 a night, a child 25 (30 in season), a dog 20 a
    night out of season; a week is 10% cheaper. All at 8%."""
    setup = cottages(owner, units=1)
    offer = setup["service"].id
    with tenant(owner):
        child, dog = category("Dziecko"), category("Pies", counts_towards_capacity=False)
        add(
            30000,
            "per_time_unit",
            service_id=offer,
            vat_code="8",
            included_people=4,
            extra_person_amount_minor=5000,
            extra_person_per_time_unit=True,
            category_prices=[
                {"category_id": child.id, "amount_minor": 2500},
                {"category_id": dog.id, "amount_minor": 2000},
            ],
            length_discounts=[{"min_length": 7, "percent": 10}],
        )
        add(
            50000,
            "per_time_unit",
            service_id=offer,
            vat_code="8",
            included_people=4,
            extra_person_amount_minor=6000,
            category_prices=[{"category_id": child.id, "amount_minor": 3000}],
            **season(f"{YEAR}-07-01", f"{YEAR}-08-31"),
        )
    return {**setup, "child": child, "dog": dog}


def test_a_stay_is_priced_night_by_night_with_the_tax_on_each_line() -> None:
    owner = membership("wycena-pobyt")
    setup = priced_cottages(owner)
    party = people(4, **{str(setup["child"].id): 2, str(setup["dog"].id): 1})
    with tenant(owner):
        quote = of_stay(setup, day(6, 28), day(7, 5), party)
        assert (quote.currency, quote.amounts, quote.priced) == ("PLN", "gross", True)
        # Three nights out of season, four in it; the four adults are the people
        # the price includes, so the children pay; the dog out of season only.
        assert lines(quote) == [
            ("price", 3, 30000, 83333, 6667, 90000),
            ("category", 6, 2500, 13889, 1111, 15000),
            ("category", 3, 2000, 5556, 444, 6000),
            ("price", 4, 50000, 185185, 14815, 200000),
            ("category", 8, 3000, 22222, 1778, 24000),
            ("discount", 1, -33500, -31019, -2481, -33500),
        ]
        assert (quote.net_minor, quote.vat_minor, quote.gross_minor) == (279166, 22334, 301500)
        assert [line.time_units for line in quote.lines] == [3, 3, 3, 4, 4, None]
        assert quote.lines[-1].percent == 10

        # Read net, the same amounts get the tax on top.
        version = read_group("pricing.entry").version
        change_settings(
            "pricing.entry",
            changes={"amounts": "net"},
            expected_version=version,
            idempotency_key=key(),
        )
        net = of_stay(setup, day(6, 28), day(7, 5), party)
    assert net.amounts == "net"
    assert lines(net)[0] == ("price", 3, 30000, 90000, 7200, 97200)
    assert (net.net_minor, net.vat_minor, net.gross_minor) == (301500, 24120, 325620)
    assert net.digest != quote.digest


def test_the_price_includes_whoever_would_pay_the_most() -> None:
    owner = membership("wycena-osoby")
    setup = cottages(owner, units=1)
    with tenant(owner):
        child = category("Dziecko")
        add(
            40000,
            service_id=setup["service"].id,
            included_people=4,
            extra_person_amount_minor=5000,
            category_prices=[{"category_id": child.id, "amount_minor": 2500}],
        )
        # Two adults and three children: the adults and two children are the
        # four included, one child pays — once, the price is per booking.
        family = of_stay(setup, day(6, 1), day(6, 4), people(2, **{str(child.id): 3}))
        six = of_stay(setup, day(6, 1), day(6, 4), people(6))
        four = of_stay(setup, day(6, 1), day(6, 4), people(4))
    assert lines(family) == [
        ("price", 1, 40000, 32520, 7480, 40000),
        ("category", 1, 2500, 2033, 467, 2500),
    ]
    assert [(line.kind, line.quantity, line.people) for line in six.lines] == [
        ("price", 1, None),
        ("extra_person", 2, 2),
    ]
    assert (six.gross_minor, four.gross_minor) == (50000, 40000)


def test_a_quote_names_what_it_cannot_price() -> None:
    owner = membership("wycena-odmowy")
    setup = priced_cottages(owner)
    with tenant(owner):
        assert refused(setup, day(6, 1), day(6, 3), people(7)) == [
            ("participants", "unit_capacity_exceeded")
        ]
        assert refused(setup, day(6, 1), day(6, 3), people(**{str(setup["dog"].id): 1})) == [
            ("participants", "participants_required")
        ]
        assert refused(
            setup, day(6, 1), day(6, 3), people(1, **{"00000000-0000-7000-8000-000000000000": 1})
        ) == [("participants", "invalid")]
        # A dog takes no place: six people and a dog fit a cottage for six.
        assert of_stay(setup, day(6, 1), day(6, 3), people(6, **{str(setup["dog"].id): 1})).priced

    bare = membership("wycena-bez-ceny")
    seasonal = cottages(bare, units=1)
    with tenant(bare):
        free = of_stay(seasonal, day(6, 1), day(6, 3))
        assert (free.priced, free.lines, free.gross_minor) == (False, (), 0)
        assert free.participants == ({"category_id": None, "count": 1},)
        add(
            50000,
            "per_time_unit",
            service_id=seasonal["service"].id,
            **season(f"{YEAR}-07-01", f"{YEAR}-08-31"),
        )
        # A price list with a hole in it refuses the nights it does not price.
        assert refused(seasonal, day(6, 29), day(7, 3), None) == [("start_date", "price_missing")]
        assert of_stay(seasonal, day(7, 1), day(7, 3)).gross_minor == 100000


def test_a_visit_is_priced_by_its_day_and_hour_and_per_person_by_who_comes() -> None:
    owner = membership("wycena-wizyta")
    service = catalog(owner)["service"]
    with tenant(owner):
        child, dog = category("Dziecko"), category("Pies", counts_towards_capacity=False)
        add(15000, service_id=service.id)
        add(20000, service_id=service.id, local_from=time(17), local_to=time(21))

        def at(hour: int, party: Any = None) -> Quote:
            return quote_visit(
                service=service,
                starts_at=datetime(YEAR, 6, 8, hour, tzinfo=WARSAW),
                participants=party,
            )

        assert (at(10).gross_minor, at(18).gross_minor) == (15000, 20000)
        assert lines(at(10)) == [("price", 1, 15000, 12195, 2805, 15000)]

        add(
            8000,
            "per_person",
            service_id=service.id,
            category_prices=[{"category_id": child.id, "amount_minor": 4000}],
            **season(f"{YEAR}-06-01", f"{YEAR}-06-30"),
        )
        tickets = at(10, people(2, **{str(child.id): 1, str(dog.id): 1}))
    # Each person pays; the child its own amount; the dog, unpriced, comes free.
    assert [(line.kind, line.quantity, line.gross_minor) for line in tickets.lines] == [
        ("price", 2, 16000),
        ("category", 1, 4000),
    ]


def test_the_customer_reads_the_lines_in_their_language_and_the_digest_stays() -> None:
    owner = membership("wycena-jezyk")
    type(owner.organization).objects.filter(pk=owner.organization_id).update(
        public_locales=["pl", "en"]
    )
    setup = priced_cottages(owner)
    party = people(4, **{str(setup["child"].id): 1})
    with tenant(owner):
        for kind, item, text in (
            ("service", setup["service"].id, "Cottage stay"),
            ("participant_category", setup["child"].id, "Child"),
        ):
            save_item_translation(
                kind=kind,
                item_id=item,
                locale="en",
                texts={"name": text},
                expected_version=0,
                idempotency_key=key(),
            )
        own = of_stay(setup, day(6, 1), day(6, 9), party)
        english = of_stay(setup, day(6, 1), day(6, 9), party, locale="en")
    assert [(line.name, line.customer_name) for line in english.lines] == [
        ("Pobyt w domku", "Cottage stay"),
        ("Dziecko", "Child"),
        ("Rabat za długość pobytu (10%)", "Discount for the length of stay (10%)"),
    ]
    assert [line.customer_name for line in own.lines][:2] == ["Pobyt w domku", "Dziecko"]
    assert english.digest == own.digest


def test_a_stay_keeps_the_price_it_was_booked_at() -> None:
    owner = membership("wycena-zamrozona")
    setup = priced_cottages(owner)
    party = people(4, **{str(setup["child"].id): 2})
    first, last = day(6, 1), day(6, 4)
    with tenant(owner):
        shown = of_stay(setup, first, last, party)
        preview = stay(setup, first, last, participants=party, preview=True)
        assert preview.quote is not None and preview.quote.digest == shown.digest

        # The price went up after the guest saw it.
        rule = next(item for item in _rules(owner) if item.starts_on is None)
        save_price(
            price_id=rule.id,
            data={"amount_minor": 32000},
            expected_version=rule.version,
            idempotency_key=key(),
        )
        with pytest.raises(QuoteChanged) as changed:
            stay(setup, first, last, participants=party, quote_digest=shown.digest)
        assert not Appointment.all_objects.filter(organization=owner.organization).exists()
        fresh = changed.value.quote
        assert (changed.value.status_code, fresh.gross_minor) == (409, 3 * 32000 + 6 * 2500)

        booked = stay(setup, first, last, participants=party, quote_digest=fresh.digest)
        kept = booked.appointment.quote
        assert (kept["gross_minor"], booked.appointment.quote_digest) == (111000, fresh.digest)
        assert kept["participants"] == [
            {"category_id": None, "count": 4},
            {"category_id": str(setup["child"].id), "count": 2},
        ]

        # A later change of the price list does not reach a booking made.
        save_price(
            price_id=rule.id,
            data={"amount_minor": 99900},
            expected_version=rule.version + 1,
            idempotency_key=key(),
        )
        booked.appointment.refresh_from_db()
        assert booked.appointment.quote["gross_minor"] == 111000

        # Moved, it is priced again for the new dates, for the same people.
        moved = move_stay(
            appointment_id=booked.appointment.id,
            start_date=day(6, 10),
            end_date=day(6, 12),
            idempotency_key=key(),
            principal_ref="test",
        )
    assert isinstance(moved, Appointment)
    assert moved.quote["gross_minor"] == 2 * 99900 + 4 * 2500
    assert moved.quote["participants"] == kept["participants"]


def _rules(owner: Any) -> list[Any]:
    from saas_core.modules.shared.booking.models import PriceRule

    return list(PriceRule.all_objects.filter(organization=owner.organization))


def test_an_offer_without_a_price_list_books_as_before_and_says_who_comes() -> None:
    owner = membership("wycena-brak")
    setup = cottages(owner, units=1)
    with tenant(owner):
        booked = stay(setup, day(6, 1), day(6, 3), participants=people(3))
    quote = booked.appointment.quote
    assert (quote["lines"], quote["gross_minor"]) == ([], 0)
    assert quote["participants"] == [{"category_id": None, "count": 3}]
    assert booked.appointment.quote_digest == quote["digest"]


def test_a_visit_keeps_its_price_and_a_move_prices_it_again() -> None:
    owner = membership("wycena-wizyta-zapis")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    service = configured["service"]
    monday = timezone.localdate() + timedelta(days=7 - timezone.localdate().weekday())
    with tenant(owner):
        add(15000, service_id=service.id)
        add(18000, service_id=service.id, weekdays=[1])

        def book(starts_at: datetime, **given: Any) -> Any:
            return create_appointment(
                service_id=service.id,
                staff_id=configured["staff"][0].id,
                location_id=configured["location"].id,
                starts_at=starts_at,
                customer_data=GUEST,
                idempotency_key=key(),
                principal_ref=str(owner.user_id),
                **given,
            )

        starts = datetime.combine(monday, time(10), WARSAW)
        with pytest.raises(QuoteChanged):
            book(starts, quote_digest="0" * 64)
        made = book(starts).appointment
        assert made.quote["gross_minor"] == 15000
        moved = reschedule_appointment(
            appointment_id=made.id,
            starts_at=starts + timedelta(days=1),
            idempotency_key=key(),
            principal_ref=str(owner.user_id),
        )
    assert (moved.quote["gross_minor"], moved.quote_digest) == (18000, moved.quote["digest"])


def test_the_quote_api_prices_and_a_booking_answers_a_changed_price() -> None:
    _, owner, client = authenticated_member(
        email="wycena-api@example.test", role_key="owner", slug="wycena-api"
    )
    bookable(owner.organization)
    setup = priced_cottages(owner)
    csrf = csrf_value(client)
    body = {
        "service_id": str(setup["service"].id),
        "group_id": str(setup["group"].id),
        "start_date": day(6, 1).isoformat(),
        "end_date": day(6, 4).isoformat(),
        "participants": [{"category_id": None, "count": 5}],
    }
    quoted = client.post("/api/v1/booking/quote/", body, format="json", HTTP_X_CSRFTOKEN=csrf)
    assert quoted.status_code == 200, quoted.data
    quote = quoted.json()
    assert (quote["gross_minor"], quote["currency"], len(quote["lines"])) == (105000, "PLN", 2)
    assert quote["lines"][1] == {
        "kind": "extra_person",
        "name": "Dodatkowa osoba",
        "customer_name": "Dodatkowa osoba",
        "quantity": 3,
        "unit_amount_minor": 5000,
        "net_minor": 13889,
        "vat_minor": 1111,
        "gross_minor": 15000,
        "vat_code": "8",
        "time_units": 3,
        "people": 1,
        "category_id": None,
        "price_rule_id": quote["lines"][1]["price_rule_id"],
        "percent": None,
        "extra_id": None,
    }
    crowded = client.post(
        "/api/v1/booking/quote/",
        {**body, "participants": [{"count": 7}]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert crowded.status_code == 400
    assert [(error["field"], error["code"]) for error in crowded.json()["errors"]] == [
        ("participants", "unit_capacity_exceeded")
    ]

    booking = {**body, "customer": GUEST}
    preview = client.post(
        "/api/v1/booking/stays/preview/", booking, format="json", HTTP_X_CSRFTOKEN=csrf
    )
    assert preview.json()["quote"]["digest"] == quote["digest"]
    stale = client.post(
        "/api/v1/booking/stays/",
        {**booking, "quote_digest": "0" * 64},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "quote_changed")
    # The new quote comes with the refusal, amounts as numbers.
    assert stale.json()["detail"]["quote"] == quote
    made = client.post(
        "/api/v1/booking/stays/",
        {**booking, "quote_digest": quote["digest"]},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert made.status_code == 201, made.data
    assert made.json()["quote"]["gross_minor"] == 105000

    with tenant(owner):
        service = catalog(owner)["service"]
        add(15000, service_id=service.id)
        assert (
            quote_offer(
                service_id=service.id, starts_at=datetime(YEAR, 6, 8, 10, tzinfo=WARSAW)
            ).gross_minor
            == 15000
        )
    visit = client.post(
        "/api/v1/booking/quote/",
        {"service_id": str(service.id), "starts_at": f"{YEAR}-06-08T10:00:00+02:00"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert (visit.status_code, visit.json()["gross_minor"]) == (200, 15000)
    neither = client.post(
        "/api/v1/booking/quote/",
        {"service_id": str(service.id)},
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert neither.status_code == 400


def test_the_price_list_answers_for_a_time_that_cannot_be_booked() -> None:
    """The preview beside the price list (phase 3e): a taken unit, a season's
    rule and an offer still switched off refuse a booking, not a question
    about the price — and every line names the price it came from."""
    _, owner, client = authenticated_member(
        email="cennik-podglad@example.test", role_key="owner", slug="cennik-podglad"
    )
    bookable(owner.organization)
    setup = priced_cottages(owner)
    offer = setup["service"]
    csrf = csrf_value(client)
    with tenant(owner):
        # The only cottage is taken for the first days of July, and from the
        # tenth a stay is a week or nothing.
        stay(setup, day(7, 1), day(7, 5))
        save_rule(
            rule_id=None,
            data={
                "service_id": offer.id,
                "starts_on": day(7, 10),
                "ends_on": day(7, 31),
                "min_length": 7,
            },
            idempotency_key=key(),
        )
        summer = PriceRule.all_objects.get(service=offer, starts_on=day(7, 1)).id

    def ask(first: date, last: date, **given: Any) -> Any:
        return client.post(
            "/api/v1/booking/quote/",
            {
                "service_id": str(offer.id),
                "group_id": str(setup["group"].id),
                "start_date": first.isoformat(),
                "end_date": last.isoformat(),
                **given,
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )

    assert (ask(day(7, 2), day(7, 4)).json()["code"]) == "slot_unavailable"
    taken = ask(day(7, 2), day(7, 4), price_only=True)
    assert taken.status_code == 200, taken.data
    assert (taken.json()["gross_minor"], taken.json()["lines"][0]["price_rule_id"]) == (
        100000,
        str(summer),
    )
    short = ask(day(7, 12), day(7, 14))
    assert [error["code"] for error in short.json()["errors"]] == ["rule_min_length"]
    assert ask(day(7, 12), day(7, 14), price_only=True).json()["gross_minor"] == 100000
    # The price list still refuses what it cannot price: more people than a
    # cottage takes.
    crowded = ask(day(7, 12), day(7, 14), price_only=True, participants=[{"count": 7}])
    assert [(error["field"], error["code"]) for error in crowded.json()["errors"]] == [
        ("participants", "unit_capacity_exceeded")
    ]

    with tenant(owner):
        save_service(
            service_id=offer.id,
            data={"active": False},
            expected_version=offer.version,
            idempotency_key=key(),
        )
    assert ask(day(6, 1), day(6, 3)).status_code == 404
    assert ask(day(6, 1), day(6, 3), price_only=True).json()["gross_minor"] == 60000


def test_a_price_per_person_per_night_reads_as_the_price_not_as_further_people() -> None:
    """„Za osobę za noc” (phase 3e) is a price per night of nothing with nobody
    in it: the quote has no line of 0 and no "further person" — the people are
    the price, under the offer's name, and a category keeps its own amount."""
    owner = membership("wycena-osoba-noc")
    setup = cottages(owner, units=1)
    with tenant(owner):
        child = category("Dziecko")
        rule = add(
            0,
            "per_time_unit",
            service_id=setup["service"].id,
            vat_code="8",
            included_people=0,
            extra_person_amount_minor=8000,
            extra_person_per_time_unit=True,
            category_prices=[{"category_id": child.id, "amount_minor": 4000}],
            length_discounts=[{"min_length": 3, "percent": 10}],
        )
        quote = of_stay(setup, day(6, 1), day(6, 4), people(2, **{str(child.id): 1}))
    assert [
        (line.kind, line.name, line.quantity, line.unit_amount_minor) for line in quote.lines
    ] == [
        ("price", "Pobyt w domku", 6, 8000),
        ("category", "Dziecko", 3, 4000),
        ("discount", "Rabat za długość pobytu (10%)", 1, -6000),
    ]
    assert {line.price_rule_id for line in quote.lines} == {rule.id}
    assert quote.gross_minor == 54000


def test_a_category_pays_for_every_night_when_the_price_says_so() -> None:
    owner = membership("wycena-pies-za-noc")
    setup = cottages(owner, units=1)
    with tenant(owner):
        dog = category("Pies", counts_towards_capacity=False)
        add(
            30000,
            "per_time_unit",
            service_id=setup["service"].id,
            extra_person_per_time_unit=True,
            category_prices=[{"category_id": dog.id, "amount_minor": 2000}],
        )
        week = of_stay(setup, day(6, 1), day(6, 8), people(2, **{str(dog.id): 1}))
    # Seven nights with a dog at 20 a night: 140, not 20.
    assert [(line.kind, line.quantity, line.gross_minor) for line in week.lines] == [
        ("price", 7, 210000),
        ("category", 7, 14000),
    ]


def test_people_beyond_the_included_pay_what_the_owner_said() -> None:
    owner = membership("wycena-ponad-cene")
    setup = cottages(owner, units=1)
    party = None
    with tenant(owner):
        child = category("Dziecko")
        party = people(2, **{str(child.id): 1})
        add(
            40000,
            service_id=setup["service"].id,
            included_people=2,
            extra_person_amount_minor=5000,
            category_prices=[{"category_id": child.id, "amount_minor": 2500}],
        )
        paid = of_stay(setup, day(6, 1), day(6, 3), party)
        # The same price with further people said to come free: the child is
        # the dearest of the three, so the price includes it.
        rule = _rules(owner)[0]
        save_price(
            price_id=rule.id,
            data={"extra_person_amount_minor": 0},
            expected_version=1,
            idempotency_key=key(),
        )
        free = of_stay(setup, day(6, 1), day(6, 3), party)
    assert (paid.gross_minor, free.gross_minor) == (42500, 40000)


def test_the_longest_threshold_reached_gives_the_discount() -> None:
    owner = membership("wycena-progi")
    setup = cottages(owner, units=1)
    with tenant(owner):
        add(
            10000,
            "per_time_unit",
            service_id=setup["service"].id,
            length_discounts=[{"min_length": 3, "percent": 10}, {"min_length": 7, "percent": 20}],
        )
        two, six, seven = (of_stay(setup, day(6, 1), day(6, 1 + nights)) for nights in (2, 6, 7))
    assert [(quote.gross_minor, quote.lines[-1].percent) for quote in (two, six, seven)] == [
        (20000, None),
        (54000, 10),
        (56000, 20),
    ]


def test_a_priced_offer_is_never_free_by_omission() -> None:
    owner = membership("wycena-luka")
    setup = cottages(owner, units=2)
    first, second = setup["units"]
    with tenant(owner):
        # A price for one cottage, the other forgotten.
        own = add(45000, "per_time_unit", resource_id=first.id)

        def of_unit(unit: Any) -> Quote:
            plan = plan_stay(
                service_id=setup["service"].id,
                start_date=day(6, 1),
                end_date=day(6, 3),
                resource_id=unit.id,
            )
            return stay_quote(plan)

        priced = of_unit(first)
        with pytest.raises(ValidationError) as missing:
            of_unit(second)
        # Switched off, the offer's only price is still a price it has.
        save_price(
            price_id=own.id, data={"active": False}, expected_version=1, idempotency_key=key()
        )
        with pytest.raises(ValidationError) as off:
            of_unit(first)
        # Free again is said by deleting the price.
        delete_price(price_id=own.id, expected_version=2, idempotency_key=key())
        free = of_unit(first)

        visit = catalog(owner)["service"]
        rule = add(15000, service_id=visit.id)
        save_price(
            price_id=rule.id, data={"active": False}, expected_version=1, idempotency_key=key()
        )
        with pytest.raises(ValidationError) as visit_off:
            quote_visit(service=visit, starts_at=datetime(YEAR, 6, 8, 10, tzinfo=WARSAW))
    # The unit's own price is the one in the quote.
    assert (priced.gross_minor, priced.lines[0].price_rule_id) == (90000, own.id)
    for refusal, field in ((missing, "start_date"), (off, "start_date"), (visit_off, "starts_at")):
        assert [(found["field"], found["code"]) for found in problem_errors(refusal.value)] == [
            (field, "price_missing")
        ]
    assert (free.priced, free.gross_minor) == (False, 0)


def test_a_seasons_price_for_everyone_beats_a_cottages_own_base_price() -> None:
    """„Domek 350, lipiec 500 dla wszystkich” is 500 in July (owner decision 75b)."""
    owner = membership("wycena-sezon-ponad-domek")
    setup = cottages(owner, units=1)
    (unit,) = setup["units"]
    with tenant(owner):
        add(35000, "per_time_unit", resource_id=unit.id)
        add(
            50000,
            "per_time_unit",
            service_id=setup["service"].id,
            starts_on=day(7, 1),
            ends_on=day(7, 31),
        )
        quote = of_stay(setup, day(6, 29), day(7, 2))
    # Two nights of June at the cottage's own price, the night of 1 July at the season's.
    assert [(line.quantity, line.unit_amount_minor) for line in quote.lines] == [
        (2, 35000),
        (1, 50000),
    ]
    assert quote.gross_minor == 120000


def test_the_unit_that_takes_the_party_is_picked_before_the_least_busy() -> None:
    owner = membership("wycena-pojemnosc")
    setup = cottages(owner, units=2)
    small, large = setup["units"]
    with tenant(owner):
        save_resource(
            resource_id=small.id, data={"capacity": 4}, expected_version=1, idempotency_key=key()
        )
        # The larger cottage is the busier one.
        stay(setup, day(5, 1), day(5, 8), resource_id=large.id, group_id=None)
        four = stay(setup, day(6, 1), day(6, 3), participants=people(4), preview=True)
        six = stay(setup, day(6, 1), day(6, 3), participants=people(6), preview=True)
        booked = stay(setup, day(6, 1), day(6, 3), participants=people(6)).appointment
        with pytest.raises(ValidationError) as crowd:
            stay(setup, day(6, 10), day(6, 12), participants=people(7), preview=True)
    assert (four.unit.id, six.unit.id, booked.resource_id) == (small.id, large.id, large.id)
    assert [(found["field"], found["code"]) for found in problem_errors(crowd.value)] == [
        ("participants", "unit_capacity_exceeded")
    ]


def test_a_booking_moves_with_what_it_was_booked_with() -> None:
    owner = membership("wycena-przenosiny")
    setup = priced_cottages(owner)
    party = people(2, **{str(setup["child"].id): 3})
    with tenant(owner):
        booked = stay(setup, day(6, 1), day(6, 4), participants=party).appointment
        before = dict(booked.quote)
        # The company stops taking children as a category of their own.
        save_category(
            category_id=setup["child"].id,
            data={"active": False},
            expected_version=1,
            idempotency_key=key(),
        )
        assert refused(setup, day(6, 20), day(6, 22), party) == [("participants", "invalid")]

        # A move with the price the mover saw for other dates is asked again…
        stale = of_stay(setup, day(6, 20), day(6, 22), people(2))
        with pytest.raises(QuoteChanged):
            move_stay(
                appointment_id=booked.id,
                start_date=day(6, 10),
                end_date=day(6, 13),
                idempotency_key=key(),
                principal_ref="test",
                quote_digest=stale.digest,
            )
        booked.refresh_from_db()
        assert (booked.starts_at.date(), booked.quote) == (day(6, 1), before)
        # …and without one the stay moves, the child still on it.
        moved = move_stay(
            appointment_id=booked.id,
            start_date=day(6, 10),
            end_date=day(6, 13),
            idempotency_key=key(),
            principal_ref="test",
        )
    assert isinstance(moved, Appointment)
    assert moved.quote["participants"] == before["participants"]
    assert moved.quote["gross_minor"] == before["gross_minor"]


def test_the_tax_rounds_halves_up_on_each_line_also_below_zero() -> None:
    owner = membership("wycena-polowki")
    setup = cottages(owner, units=1)
    with tenant(owner):
        version = read_group("pricing.entry").version
        change_settings(
            "pricing.entry",
            changes={"amounts": "net"},
            expected_version=version,
            idempotency_key=key(),
        )
        # 2.50 net at 23%: the tax is 57.5 grosze. Seven nights of 50 grosze
        # with 10% off: a discount of 35, whose tax is 8.05 the other way.
        add(250, service_id=catalog(owner)["service"].id)
        add(
            50,
            "per_time_unit",
            service_id=setup["service"].id,
            length_discounts=[{"min_length": 7, "percent": 10}],
        )
        visit = quote_visit(
            service=_rules(owner)[0].service, starts_at=datetime(YEAR, 6, 8, 10, tzinfo=WARSAW)
        )
        week = of_stay(setup, day(6, 1), day(6, 8))
    assert lines(visit) == [("price", 1, 250, 250, 58, 308)]
    assert lines(week) == [
        ("price", 7, 50, 350, 81, 431),
        ("discount", 1, -35, -35, -8, -43),
    ]
    # The totals are the lines added up, nothing rounded twice.
    assert (week.net_minor, week.vat_minor, week.gross_minor) == (315, 73, 388)


def test_nights_are_dates_and_a_visits_day_is_the_companys() -> None:
    owner = membership("wycena-zegar")
    setup = cottages(owner, units=1)
    # The night the clocks go back has 25 hours and is one night.
    sunday = date(YEAR, 10, 31)
    sunday -= timedelta(days=(sunday.weekday() + 1) % 7)
    with tenant(owner):
        add(30000, "per_time_unit", service_id=setup["service"].id)
        over = of_stay(setup, sunday - timedelta(days=1), sunday + timedelta(days=1))

        visit = catalog(owner)["service"]
        add(15000, service_id=visit.id)
        add(20000, service_id=visit.id, weekdays=[5])
        saturday = day(6, 1) + timedelta(days=(5 - day(6, 1).weekday()) % 7)
        late = datetime.combine(saturday, time(23, 30), WARSAW)
        # Half past midnight on Sunday in Warsaw is still Saturday in UTC.
        after = (late + timedelta(hours=1)).astimezone(ZoneInfo("UTC"))
        prices = [
            quote_visit(service=visit, starts_at=starts_at).gross_minor
            for starts_at in (late, after)
        ]
    assert [(line.quantity, line.gross_minor) for line in over.lines] == [(2, 60000)]
    assert after.weekday() == 5
    assert prices == [20000, 15000]
