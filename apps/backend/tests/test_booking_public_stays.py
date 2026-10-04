"""Stays on the company's public form and on the customer's own link
(ADR-072, „Uzupełnienie 2026-10-04: faza 5 w plastrach”, slice 5a): a guest
sees what can be booked from–to, on which days, and what it costs; books at
the price shown; and moves their own stay by its dates."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.models import (
    Appointment,
    AppointmentResourceAllocation,
    Location,
    PublicBookingRoute,
    Service,
)
from saas_core.modules.shared.booking.occupancy import occupancy
from saas_core.modules.shared.booking.periods import PUBLIC_WINDOW_DAYS, period_last_day
from saas_core.modules.shared.booking.rules import save_rule
from saas_core.modules.shared.booking.setup import save_location, save_resource, save_service
from test_booking import _no_delivery, catalog, company_today, membership, tenant
from test_booking_extras import with_extras
from test_booking_prices import key
from test_booking_quote import WARSAW, category
from test_booking_stays import cottages, saturday_after

pytestmark = pytest.mark.django_db

GUEST = {"display_name": "Jan Gość", "email": "jan-gosc@example.test"}


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def form(slug: str, *, priced: bool = True, units: int = 1) -> dict[str, Any]:
    """A company whose cottages are booked on its public form: 300 a night
    with a cleaning fee and a local tax on every booking, bed linen and an
    extra bed to pick, and a deposit — or, without `priced`, no price list."""
    owner = membership(slug)
    setup = with_extras(owner) if priced else cottages(owner, units=units)
    # Saving the offer gave the company its form's address: its own slug.
    assert PublicBookingRoute.objects.filter(
        public_slug=slug, organization_id=owner.organization_id
    ).exists()
    first = saturday_after(30)
    return {
        **setup,
        "owner": owner,
        "url": f"/api/v1/booking/public/{slug}",
        "first": first,
        "target": {"service_id": str(setup["service"].id), "group_id": str(setup["group"].id)},
        "dates": {
            "start_date": first.isoformat(),
            "end_date": (first + timedelta(days=2)).isoformat(),
        },
    }


def quoted(client: APIClient, configured: dict[str, Any], **body: Any) -> Any:
    return client.post(
        f"{configured['url']}/stays/quote/",
        {**configured["target"], **configured["dates"], **body},
        format="json",
    )


def booked(
    client: APIClient, configured: dict[str, Any], idem: str | None = None, **body: Any
) -> Any:
    return client.post(
        f"{configured['url']}/stays/",
        {**configured["target"], **configured["dates"], "customer": GUEST, **body},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem or key(),
    )


def test_the_form_lists_stays_apart_from_visits_with_what_a_guest_chooses() -> None:
    configured = form("pobyty-katalog", priced=False, units=2)
    owner = configured["owner"]
    visit = catalog(owner)
    with tenant(owner):
        dog = category("Pies", counts_towards_capacity=False)
        # A unit the offer lists by itself, and one at a place that is not
        # offered online: the second is not on the form.
        elsewhere = save_location(
            location_id=None, data={"name": "Zaplecze", "online": False}, idempotency_key=key()
        ).value
        lakeside, hidden = (
            save_resource(
                resource_id=None,
                data={"name": name, "location_id": place, "capacity": 4, "description": text},
                idempotency_key=key(),
            ).value
            for name, place, text in (
                ("Apartament nad jeziorem", configured["place"].id, "Z tarasem."),
                ("Pokój na zapleczu", elsewhere.id, ""),
            )
        )
        offer = Service.all_objects.get(pk=configured["service"].id)
        save_service(
            service_id=offer.id,
            data={"resource_ids": [lakeside.id, hidden.id]},
            expected_version=offer.version,
            idempotency_key=key(),
        )
        # An offer the team books in the panel only.
        save_service(
            service_id=None,
            data={
                "name": "Pobyt dla stałych gości",
                "time_model": "range",
                "range_unit": "night",
                "staff_count": 0,
                "online": False,
                "group_ids": [configured["group"].id],
            },
            idempotency_key=key(),
        )

    listing = APIClient().get(f"{configured['url']}/").json()

    # The visit calendar's list keeps offering visits only.
    assert [item["name"] for item in listing["services"]] == [visit["service"].name]
    (stay,) = listing["stays"]
    # Units the company does not show as content, and no price list.
    plain = {"public_slug": "", "photos": [], "amenities": [], "town": None, "from_price": None}
    assert stay == {
        "id": str(configured["service"].id),
        "name": "Pobyt w domku",
        "public_slug": stay["public_slug"],
        "range_unit": "night",
        "range_start_local": stay["range_start_local"],
        "range_end_local": stay["range_end_local"],
        "confirmation": "instant",
        "response_hours": 24,
        # A group is one choice: which of its cottages, the server picks.
        "groups": [
            {
                "id": str(configured["group"].id),
                "name": "Domek 6-os.",
                "description": "",
                "capacity": 6,
                "units": 2,
                **plain,
            }
        ],
        "units": [
            {
                "id": str(lakeside.id),
                "name": "Apartament nad jeziorem",
                "description": "Z tarasem.",
                "capacity": 4,
                "public_slug": "",
                **plain,
            }
        ],
    }
    assert listing["participant_categories"] == [
        {"id": str(dog.id), "name": "Pies", "counts_towards_capacity": False}
    ]
    with tenant(owner):
        assert listing["online"]["period_last_day"] == period_last_day(WARSAW).isoformat()
    # The unit behind the place that is not online cannot be asked about either.
    hidden_days = APIClient().get(
        f"{configured['url']}/stays/starts/",
        {
            "service_id": str(configured["service"].id),
            "resource_id": str(hidden.id),
            "from": configured["first"].isoformat(),
            "to": configured["first"].isoformat(),
        },
    )
    assert hidden_days.status_code == 404


def test_the_forms_catalogue_reads_the_same_number_of_times_whatever_the_company_has() -> None:
    configured = form("pobyty-zapytania", priced=False, units=1)
    owner = configured["owner"]

    def queries() -> int:
        cache.clear()
        seen: list[str] = []

        def note(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
            seen.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(note):
            assert APIClient().get(f"{configured['url']}/").status_code == 200
        return len(seen)

    before = queries()
    more = cottages_again(owner, configured)
    assert len(APIClient().get(f"{configured['url']}/").json()["stays"]) == 1 + more
    assert queries() == before


def cottages_again(owner: Any, configured: dict[str, Any]) -> int:
    """Two more offers on the same group and three more units in it."""
    with tenant(owner):
        for n in range(2, 5):
            save_resource(
                resource_id=None,
                data={
                    "name": f"Domek {n}",
                    "group_id": configured["group"].id,
                    "location_id": configured["place"].id,
                    "capacity": 6,
                },
                idempotency_key=key(),
            )
        for name in ("Weekend w domku", "Tydzień w domku"):
            save_service(
                service_id=None,
                data={
                    "name": name,
                    "time_model": "range",
                    "range_unit": "night",
                    "staff_count": 0,
                    "group_ids": [configured["group"].id],
                },
                idempotency_key=key(),
            )
    return 2


def test_the_calendar_offers_arrivals_and_departures_within_the_forms_reach() -> None:
    configured = form("pobyty-kalendarz", priced=False)
    owner, first = configured["owner"], configured["first"]
    client = APIClient()
    with tenant(owner):
        # Saturday to Saturday in that week, and nothing further ahead than
        # the season says.
        save_rule(
            rule_id=None,
            data={
                "service_id": configured["service"].id,
                "starts_on": first - timedelta(days=3),
                "ends_on": first + timedelta(days=10),
                "start_weekdays": [5],
                "min_length": 2,
            },
            idempotency_key=key(),
        )

    starts = client.get(
        f"{configured['url']}/stays/starts/",
        {
            **configured["target"],
            "from": (first - timedelta(days=3)).isoformat(),
            "to": (first + timedelta(days=10)).isoformat(),
        },
    )
    assert starts.status_code == 200, starts.data
    assert starts.json()["items"] == [first.isoformat(), (first + timedelta(days=7)).isoformat()]
    ends = client.get(
        f"{configured['url']}/stays/ends/", {**configured["target"], "start": first.isoformat()}
    )
    assert ends.status_code == 200, ends.data
    # The season's shortest stay is two nights.
    assert ends.json()["items"][0] == (first + timedelta(days=2)).isoformat()

    # One search is a few months at most; the panel's calendar is not limited so.
    wide = client.get(
        f"{configured['url']}/stays/starts/",
        {
            **configured["target"],
            "from": first.isoformat(),
            "to": (first + timedelta(days=PUBLIC_WINDOW_DAYS + 1)).isoformat(),
        },
    )
    assert (wide.status_code, wide.json()["errors"][0]["field"]) == (400, "to")
    # Past the platform's bound the calendar offers nothing and a stay is refused.
    with tenant(owner):
        last = period_last_day(WARSAW)
    far = last + timedelta(days=3)
    beyond = client.get(
        f"{configured['url']}/stays/starts/",
        {
            **configured["target"],
            "from": far.isoformat(),
            "to": (far + timedelta(days=7)).isoformat(),
        },
    )
    assert (beyond.status_code, beyond.json()["items"]) == (200, [])
    assert client.get(
        f"{configured['url']}/stays/ends/", {**configured["target"], "start": far.isoformat()}
    ).json() == {"items": []}
    refused = quoted(
        client,
        configured,
        start_date=far.isoformat(),
        end_date=(far + timedelta(days=2)).isoformat(),
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "beyond_booking_horizon")
    # An offer that is not on the form is as if it did not exist.
    with tenant(owner):
        Service.all_objects.filter(pk=configured["service"].id).update(online=False)
    assert (
        client.get(
            f"{configured['url']}/stays/starts/",
            {**configured["target"], "from": first.isoformat(), "to": first.isoformat()},
        ).status_code
        == 404
    )
    assert quoted(client, configured).status_code == 404
    assert booked(client, configured).status_code == 404


def test_a_guest_books_a_stay_at_the_price_they_were_shown() -> None:
    configured = form("pobyty-rezerwacja")
    owner = configured["owner"]
    client = APIClient()
    party = {
        "participants": [{"category_id": None, "count": 2}],
        "extras": [{"extra_id": str(configured["linen"].id), "quantity": 1}],
    }

    answer = quoted(client, configured, **party)
    assert answer.status_code == 200, answer.data
    plan = answer.json()
    # The stay's instants and length, and the price as a customer reads it:
    # gross, by name, without the unit a booking would pick.
    assert set(plan) == {"starts_at", "ends_at", "length", "range_unit", "quote"}
    assert (plan["length"], plan["range_unit"]) == (2, "night")
    quote = plan["quote"]
    assert sorted(
        (line["name"], line["quantity"], line["gross_minor"]) for line in quote["lines"]
    ) == [
        # Two nights; the tax per person and night, the linen per person.
        ("Opłata miejscowa", 4, 1200),
        ("Pobyt w domku", 2, 60000),
        ("Pościel", 2, 6000),
        ("Sprzątanie końcowe", 1, 15000),
    ]
    assert (quote["gross_minor"], quote["security_deposit_minor"]) == (82200, 50000)
    assert "net_minor" not in quote and "participants" not in quote

    # A price nobody showed the guest is not booked: the answer is the quote.
    unseen = booked(client, configured, **party)
    assert (unseen.status_code, unseen.json()["code"]) == (409, "quote_changed")
    assert unseen.json()["detail"]["quote"] == quote
    # Nor a price that was shown for another party.
    other = booked(
        client,
        configured,
        participants=[{"category_id": None, "count": 3}],
        quote_digest=quote["digest"],
    )
    assert (other.status_code, other.json()["code"]) == (409, "quote_changed")
    assert other.json()["detail"]["quote"]["gross_minor"] != quote["gross_minor"]
    with tenant(owner):
        assert not Appointment.all_objects.exists()

    idem = key()
    made = booked(
        client,
        configured,
        idem,
        **party,
        quote_digest=quote["digest"],
        customer_notes=" Późny przyjazd ",
    )
    assert made.status_code == 201, made.data
    stay = made.json()
    assert (stay["status"], stay["time_model"], stay["range_unit"], stay["unit_name"]) == (
        "confirmed",
        "range",
        "night",
        "Domek 1",
    )
    assert stay["quote"] == quote
    assert stay["self_service_token"].startswith("bk_")
    # The same key answers the first booking again.
    again = booked(
        client,
        configured,
        idem,
        **party,
        quote_digest=quote["digest"],
        customer_notes=" Późny przyjazd ",
    )
    assert (again.status_code, again.json()["id"]) == (200, stay["id"])
    # The only cottage is taken now: for the calendar, the quote and a booking.
    taken = quoted(client, configured, **party)
    assert (taken.status_code, taken.json()["code"]) == (409, "slot_unavailable")
    late = booked(client, configured, **party, quote_digest=quote["digest"])
    assert (late.status_code, late.json()["code"]) == (409, "slot_unavailable")
    starts = client.get(
        f"{configured['url']}/stays/starts/",
        {
            **configured["target"],
            "from": configured["first"].isoformat(),
            "to": (configured["first"] + timedelta(days=1)).isoformat(),
        },
    )
    assert starts.json()["items"] == []

    with tenant(owner):
        saved = Appointment.all_objects.get(pk=stay["id"])
        assert (saved.resource.name, saved.staff_id, saved.customer_notes) == (
            "Domek 1",
            None,
            "Późny przyjazd",
        )
        assert saved.quote["digest"] == quote["digest"]
        assert (
            AppointmentResourceAllocation.all_objects.filter(appointment=saved, active=True).count()
            == 1
        )
        # The company sees it in „Obłożenie”.
        board = occupancy(first=configured["first"], last=configured["first"] + timedelta(days=2))
        assert [(held.appointment, held.kind) for held in board.held] == [(saved, "stay")]


def test_more_people_than_a_unit_takes_and_a_broken_rule_are_said_before_booking() -> None:
    configured = form("pobyty-odmowy")
    client = APIClient()
    crowd = quoted(client, configured, participants=[{"category_id": None, "count": 7}])
    assert crowd.status_code == 400
    assert [(error["field"], error["code"]) for error in crowd.json()["errors"]] == [
        ("participants", "unit_capacity_exceeded")
    ]
    backwards = quoted(
        client, configured, end_date=(configured["first"] - timedelta(days=1)).isoformat()
    )
    assert backwards.status_code == 400
    assert [(error["field"], error["code"]) for error in backwards.json()["errors"]] == [
        ("end_date", "end_before_start")
    ]


def test_a_stay_without_a_price_is_booked_without_a_digest_and_the_forms_rules_hold() -> None:
    configured = form("pobyty-bez-ceny", priced=False)
    owner = configured["owner"]
    client = APIClient()
    assert quoted(client, configured).json()["quote"] is None

    def online(name: str, **changes: Any) -> None:
        with tenant(owner):
            change_settings(
                "booking.online",
                changes=changes,
                expected_version=read_group("booking.online").version,
                idempotency_key=name,
            )

    # What the company requires of an online customer holds for a stay too.
    online("kontakt", contact="email_and_phone")
    missing = booked(client, configured)
    assert missing.status_code == 400
    assert [error["field"] for error in missing.json()["errors"]] == ["customer.phone"]
    # …and so does the pause: the form refuses, the team books on.
    online("pauza", paused=True, contact="email")
    paused = booked(client, configured)
    assert (paused.status_code, paused.json()["code"]) == (409, "booking_paused")
    online("wznowienie", paused=False)

    made = booked(client, configured)
    assert made.status_code == 201, made.data
    assert (made.json()["quote"], made.json()["status"]) == (None, "confirmed")


def test_the_customers_link_shows_a_stay_and_moves_it_by_its_dates() -> None:
    configured = form("pobyty-link")
    owner, first = configured["owner"], configured["first"]
    client = APIClient()
    quote = quoted(client, configured).json()["quote"]
    stay = booked(client, configured, quote_digest=quote["digest"]).json()
    link = f"/api/v1/booking/self-service/{stay['self_service_token']}"

    read = client.get(f"{link}/")
    assert read.status_code == 200
    assert (read.json()["time_model"], read.json()["unit_name"]) == ("range", "Domek 1")
    assert read.json()["self_service"]["reschedule"] is True
    # A stay is not moved by a time of day.
    by_time = client.post(
        f"{link}/reschedule/",
        {"starts_at": stay["starts_at"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert by_time.status_code == 400
    assert by_time.json()["errors"][0]["code"] == "stay_moves_by_dates"

    later = {
        "start_date": (first + timedelta(days=7)).isoformat(),
        "end_date": (first + timedelta(days=10)).isoformat(),
    }
    preview = client.post(f"{link}/stay/preview/", later, format="json")
    assert preview.status_code == 200, preview.data
    # Three nights at 300, the cleaning, and the tax for one person.
    assert (preview.json()["length"], preview.json()["quote"]["gross_minor"]) == (3, 105900)
    # Three nights are not the price of two: without the new price's digest
    # nothing moves.
    unseen = client.post(f"{link}/stay/", later, format="json", HTTP_IDEMPOTENCY_KEY=key())
    assert (unseen.status_code, unseen.json()["code"]) == (409, "quote_changed")
    assert unseen.json()["detail"]["quote"] == preview.json()["quote"]
    idem = key()
    moved = client.post(
        f"{link}/stay/",
        {**later, "quote_digest": preview.json()["quote"]["digest"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem,
    )
    assert moved.status_code == 200, moved.data
    assert moved.json()["quote"] == preview.json()["quote"]
    with tenant(owner):
        saved = Appointment.all_objects.get(pk=stay["id"])
        assert timezone.localtime(saved.starts_at, WARSAW).date() == first + timedelta(days=7)
        assert timezone.localtime(saved.ends_at, WARSAW).date() == first + timedelta(days=10)
    # The offer left the form: the guest still moves what they booked…
    with tenant(owner):
        Service.all_objects.filter(pk=configured["service"].id).update(online=False)
        Location.all_objects.filter(pk=configured["place"].id).update(online=False)
    back = {**configured["dates"]}
    offline = client.post(f"{link}/stay/preview/", back, format="json")
    assert offline.status_code == 200, offline.data
    # …but only as far as the booking's own terms let the link.
    with tenant(owner):
        Appointment.all_objects.filter(pk=stay["id"]).update(self_service_mode="cancel_only")
    locked = client.post(f"{link}/stay/preview/", back, format="json")
    assert (locked.status_code, locked.json()["code"]) == (409, "appointment_not_changeable")
    # An unknown link is the same 404 as for a visit.
    assert (
        client.post(
            "/api/v1/booking/self-service/bk_nieznany/stay/preview/", back, format="json"
        ).status_code
        == 404
    )


def test_another_companys_offer_and_a_plan_without_booking_are_not_reached() -> None:
    """The rows of the authorization matrix a public form has: its company's
    own offers only, and nothing when the company's plan has no booking."""
    configured = form("pobyty-swoje", priced=False)
    other = form("pobyty-cudze", priced=False)
    client = APIClient()
    first = configured["first"].isoformat()
    window = {"from": first, "to": first}
    # Through one company's form another company's offer does not exist, nor
    # does another company's unit under this company's own offer.
    foreign = {"service_id": str(other["service"].id), "group_id": str(other["group"].id)}
    mixed = {
        "service_id": str(configured["service"].id),
        "resource_id": str(other["units"][0].id),
    }
    for target in (foreign, mixed):
        answers = (
            client.get(f"{configured['url']}/stays/starts/", {**target, **window}),
            client.get(f"{configured['url']}/stays/ends/", {**target, "start": first}),
            client.post(
                f"{configured['url']}/stays/quote/",
                {**target, **configured["dates"]},
                format="json",
            ),
            client.post(
                f"{configured['url']}/stays/",
                {**target, **configured["dates"], "customer": GUEST},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key(),
            ),
        )
        assert [answer.status_code for answer in answers] == [404, 404, 404, 404], target
    for company in (configured, other):
        with tenant(company["owner"]):
            assert not Appointment.all_objects.exists()

    # The company's plan lost booking: its form answers 403, whatever is asked.
    made = booked(client, configured)
    assert made.status_code == 201, made.data
    link = f"/api/v1/booking/self-service/{made.json()['self_service_token']}"
    EntitlementSnapshot.all_objects.filter(
        organization_id=configured["owner"].organization_id
    ).update(features={})
    cache.clear()
    refused = (
        client.get(f"{configured['url']}/stays/starts/", {**configured["target"], **window}),
        client.get(f"{configured['url']}/stays/ends/", {**configured["target"], "start": first}),
        quoted(client, configured),
        booked(client, configured),
        client.post(f"{link}/stay/preview/", configured["dates"], format="json"),
        client.post(
            f"{link}/stay/", configured["dates"], format="json", HTTP_IDEMPOTENCY_KEY=key()
        ),
    )
    assert [(answer.status_code, answer.json()["code"]) for answer in refused] == [
        (403, "entitlement_required")
    ] * 6


def test_today_is_the_companys_day_for_the_forms_reach() -> None:
    owner = membership("pobyty-dzien")
    with tenant(owner):
        assert period_last_day(WARSAW) > company_today() + timedelta(days=365)
