"""What a guest reading another language gets of a company's stays (ADR-072,
„Rozstrzygnięcia plastra 5i"): beside the company's prices, the rate for an
indicative figure in the reader's own currency — on the form, on the company's
site, in the catalogue and on the customer's own link — while every amount
stays the company's; the offer's own words for the form's labels; and the
mails in the customer's language."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import (
    ExchangeRateTable,
    Membership,
    Organization,
)
from saas_core.modules.core.organizations.settings_service import change_settings, read_group
from saas_core.modules.shared.booking import catalog_card
from saas_core.modules.shared.booking.company_settings import PRICE_CONVERSION
from saas_core.modules.shared.booking.models import Appointment, Service
from saas_core.modules.shared.booking.notify import customer_person_changed
from saas_core.modules.shared.booking.presets import guest_words, latest_presets
from saas_core.modules.shared.booking.site_blocks import site_blocks
from test_booking import _no_delivery, catalog, company_today, mails, membership, tenant
from test_booking_catalog_card import CATALOG_URL, listed, shown_unit
from test_booking_public_stays import GUEST, booked, form, quoted
from test_media_api import MemoryStorage

pytestmark = pytest.mark.django_db

#: One złoty in euro at NBP's mid rate of 4.3797.
RATE = "0.228326"


@pytest.fixture(autouse=True)
def three_languages(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache.clear()
    _no_delivery(monkeypatch)
    with override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de")):
        yield


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> MemoryStorage:
    """Where a shown unit's picture is, in place of the object store."""
    memory = MemoryStorage()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: memory
    )
    return memory


def rates(*, days_ago: int = 0) -> ExchangeRateTable:
    """The bank's table as the scheduled task keeps it — no bank is asked."""
    return ExchangeRateTable.objects.create(
        source="nbp",
        base_currency="PLN",
        published_on=timezone.localdate() - timedelta(days=days_ago),
        rates={"PLN": "1", "EUR": "4.379700", "USD": "3.911100"},
    )


def speaking(owner: Membership, *locales: str) -> None:
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=list(locales))


def catalogue(configured: dict[str, Any], locale: str) -> Any:
    answer = APIClient().get(f"{configured['url']}/", {"locale": locale})
    assert answer.status_code == 200, answer.data
    return answer.json()


def test_the_form_in_another_language_gets_the_rate_and_the_prices_stay_the_companys() -> None:
    configured = form("waluty-formularz")
    speaking(configured["owner"], "pl", "en", "de")
    table = rates()

    german = catalogue(configured, "de")

    assert german["currency"] == "PLN"
    assert german["conversion"] == {
        "currency": "EUR",
        "rate": RATE,
        "date": table.published_on.isoformat(),
        "bank": "NBP",
    }
    # „od X zł/noc” and the quote are in the company's currency, as before:
    # the page works the indicative figure out from what it shows.
    (stay,) = german["stays"]
    assert stay["groups"][0]["from_price"]["currency"] == "PLN"
    quote = quoted(APIClient(), configured, locale="de").json()["quote"]
    assert quote["currency"] == "PLN"
    assert "conversion" not in quote
    # English readers count in euro too; Polish ones in the company's own.
    assert catalogue(configured, "en")["conversion"]["currency"] == "EUR"
    assert catalogue(configured, "pl")["conversion"] is None


def test_no_rate_no_figure_and_the_company_can_switch_it_off() -> None:
    configured = form("waluty-brak")
    owner: Membership = configured["owner"]
    speaking(owner, "pl", "de")

    # No table yet, then one that is too old: nothing rather than an old rate.
    assert catalogue(configured, "de")["conversion"] is None
    old = rates(days_ago=6)
    assert catalogue(configured, "de")["conversion"] is None
    old.delete()
    rates(days_ago=5)
    assert catalogue(configured, "de")["conversion"] is not None

    with tenant(owner):
        group = read_group("booking.online")
        assert PRICE_CONVERSION == "booking.online.price_conversion"
        assert group.values["price_conversion"].value is True
        change_settings(
            "booking.online",
            changes={"price_conversion": False},
            expected_version=group.version,
            idempotency_key=str(uuid4()),
        )
    assert catalogue(configured, "de")["conversion"] is None


def test_a_company_that_prices_in_euro_is_read_in_zloty_by_a_polish_guest() -> None:
    configured = form("waluty-euro", priced=False)
    owner: Membership = configured["owner"]
    Organization.objects.filter(pk=owner.organization_id).update(
        currency="EUR", public_locales=["de", "pl"]
    )
    rates()

    polish = catalogue(configured, "pl")["conversion"]
    assert (polish["currency"], polish["rate"]) == ("PLN", "4.379700")
    assert catalogue(configured, "de")["conversion"] is None


def test_the_companys_site_and_its_catalogue_page_say_the_same_rate(
    storage: MemoryStorage,
) -> None:
    configured = form("waluty-strona")
    owner: Membership = configured["owner"]
    speaking(owner, "pl", "de")
    first, _photo = shown_unit(configured)
    table = rates()
    expected = {
        "currency": "EUR",
        "rate": RATE,
        "date": table.published_on.isoformat(),
        "bank": "NBP",
    }

    # A block of the company's site, as the page in German is told it.
    live = site_blocks(owner.organization_id, "de", {"0": ("core.stay_units", {})})
    assert live["0"]["conversion"] == expected
    assert (
        site_blocks(owner.organization_id, "pl", {"0": ("core.stay_units", {})})["0"]["conversion"]
        is None
    )

    # The card in the catalogue and the unit's page under it.
    assert catalog_card.card(owner.organization_id, "de")["conversion"] == expected
    assert catalog_card.unit(owner.organization_id, "de", first.public_slug)["conversion"] == (
        expected
    )
    entry = listed(owner)
    page = APIClient().get(
        f"{CATALOG_URL}{entry.city_slug}/{entry.slug}/units/{first.public_slug}/", {"locale": "de"}
    )
    assert page.status_code == 200, page.data
    assert page.json()["booking"]["conversion"] == expected
    assert page.json()["unit"]["from_price"]["currency"] == "PLN"
    card = APIClient().get(f"{CATALOG_URL}{entry.city_slug}/{entry.slug}/", {"locale": "de"})
    assert card.json()["booking"]["conversion"] == expected


def test_a_booked_stay_tells_its_customer_the_rate_and_freezes_the_companys_amounts() -> None:
    configured = form("waluty-rezerwacja")
    speaking(configured["owner"], "pl", "de")
    rates()
    client = APIClient()
    quote = quoted(client, configured, locale="de").json()["quote"]

    made = booked(
        client,
        configured,
        quote_digest=quote["digest"],
        customer={**GUEST, "locale": "de"},
    )

    assert made.status_code == 201, made.data
    answer = made.json()
    assert answer["conversion"]["currency"] == "EUR"
    assert answer["quote"]["currency"] == "PLN"
    # What is frozen on the booking knows nothing of another currency.
    stay = Appointment.all_objects.get(pk=answer["id"])
    assert stay.quote["currency"] == "PLN"
    assert "EUR" not in str(stay.quote)


def test_the_form_says_the_offers_own_words_where_somebody_has_them() -> None:
    lodging = next(preset for preset in latest_presets() if preset.id == "core.lodging")
    words = lodging.raw["vocabulary"]
    offer = Service(
        preset_id=lodging.id, preset_version=lodging.version, vocabulary=dict(words["pl"])
    )

    # The company's own language: the offer's words, which it may have changed.
    offer.vocabulary["unit"] = "Chata"
    assert guest_words(offer, "pl", "pl") == {"unit": "Chata", "participants": "Goście"}
    # Another language the preset speaks: the preset's.
    assert guest_words(offer, "en", "pl") == {"unit": "Cottage", "participants": "Guests"}
    # A language nobody has words in: none, and the form keeps its general ones.
    assert guest_words(offer, "de", "pl") == {}
    # A company that writes in German got the preset's English copy: not
    # German words, so not said on a German page.
    assert guest_words(offer, "de", "de") == {}
    # An offer made by hand.
    assert guest_words(Service(), "pl", "pl") == {}

    configured = form("slowa-oferty", priced=False)
    speaking(configured["owner"], "pl", "en", "de")
    Service.all_objects.filter(pk=configured["service"].id).update(
        preset_id=lodging.id, preset_version=lodging.version, vocabulary=dict(words["pl"])
    )
    assert catalogue(configured, "pl")["stays"][0]["words"] == {
        "unit": "Domek",
        "participants": "Goście",
    }
    assert catalogue(configured, "en")["stays"][0]["words"] == {
        "unit": "Cottage",
        "participants": "Guests",
    }
    assert catalogue(configured, "de")["stays"][0]["words"] == {}


def test_a_german_customer_hears_in_german_that_the_person_changed() -> None:
    owner = membership("osoba-po-niemiecku")
    configured = catalog(owner)
    speaking(owner, "pl", "de")
    url = "/api/v1/booking/public/osoba-po-niemiecku"
    from saas_core.modules.shared.booking.models import PublicBookingRoute

    PublicBookingRoute.objects.get_or_create(
        public_slug="osoba-po-niemiecku", organization_id=owner.organization_id
    )
    query = {
        "service_id": str(configured["service"].id),
        "location_id": str(configured["location"].id),
    }
    client = APIClient()
    day = company_today() + timedelta(days=7)
    times = client.get(f"{url}/times/", {**query, "date": day.isoformat()}).json()["items"]
    made = client.post(
        f"{url}/appointments/",
        {
            **query,
            "starts_at": times[0]["starts_at"],
            "customer": {"display_name": "Anna", "email": "anna@example.test", "locale": "de"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert made.status_code == 201, made.data
    visit = Appointment.all_objects.select_related("customer").get(pk=made.json()["id"])
    # The customer chose the person, so a change of it is theirs to know.
    visit.requested_staff_id = visit.staff_id

    with tenant(owner):
        customer_person_changed(visit, previous_lead_id=visit.staff_id)

    (mail,) = mails(visit.id, "booking.person_changed")
    assert (mail.locale, mail.template_version) == ("de", 2)
    assert "/de/booking/" in mail.context["manage_url"]
