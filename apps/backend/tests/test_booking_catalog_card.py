"""The catalogue knows who can be booked online (ADR-072, „Rozstrzygnięcia
plastra 5h”): the listing's badge and filter, what a company's card lets a
visitor book, a unit's own page under the card, the signed token that makes a
booking the catalogue's, the category an offer's preset points at — and the
fact that a company letting units by the night is a lodging business."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.organizations import origin as origin_tokens
from saas_core.modules.core.organizations.api import (
    issue_origin,
    organization_facts,
    read_origin,
)
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking import catalog_card
from saas_core.modules.shared.booking.models import Appointment, PublicBookingRoute, Service
from saas_core.modules.shared.booking.periods import book_stay
from saas_core.modules.shared.booking.presets import apply_preset
from saas_core.modules.shared.booking.setup import save_service
from saas_core.modules.shared.commerce.models import Order
from saas_core.modules.shared.media.models import AiOrigin, MediaAsset
from saas_core.modules.shared.profiles import catalog_listing
from saas_core.modules.shared.profiles.catalog import publish_profile
from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.catalog_listing import badge_keys, hinted_category
from saas_core.modules.shared.profiles.models import CatalogEntry
from saas_core.modules.shared.profiles.search_index import INDEX_SETTINGS, _filters
from saas_core.modules.shared.profiles.services import organization_profile, update_profile
from test_booking import _no_delivery, catalog, membership, tenant
from test_booking_prices import key
from test_booking_public_stays import GUEST, booked, form, quoted
from test_booking_unit_content import change, picture
from test_commerce_orders import with_orders

pytestmark = pytest.mark.django_db

CATALOG_URL = "/api/v1/public/catalog/"
TOWN = "mragowo"


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


def known_categories(owner: Membership) -> dict[str, Any]:
    return categories(owner.organization.organization_type or settings.DEFAULT_ORGANIZATION_TYPE)


def listed(owner: Membership, name: str = "Domki nad Jeziorem", **card: Any) -> CatalogEntry:
    """The company's card, filled in and published in the catalogue."""
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
    snapshot.features = {**snapshot.features, "profiles.enabled": True}
    snapshot.sources = {**snapshot.sources, "profiles.enabled": {"kind": "plan"}}
    snapshot.save()
    with tenant(owner):
        profile = organization_profile()
        update_profile(
            profile.id,
            expected_version=profile.version,
            **{
                "display_name": name,
                "city_slug": TOWN,
                "category": next(iter(known_categories(owner))),
                **card,
            },
        )
        return publish_profile()


def shown_unit(configured: dict[str, Any], **content: Any) -> Any:
    """The company's first cottage, shown to guests with a picture."""
    owner: Membership = configured["owner"]
    photo = picture(owner)
    (first, *_rest) = configured["units"]
    change(
        owner,
        first,
        **{
            "public": True,
            "photo_ids": [photo.id],
            "amenities": ["sauna", "wifi"],
            "city_slug": TOWN,
            "latitude": "53.864000",
            "longitude": "21.305000",
            **content,
        },
    )
    first.refresh_from_db()
    return first, photo


def card_of(entry: CatalogEntry, locale: str | None = None) -> Any:
    answer = APIClient().get(
        f"{CATALOG_URL}{entry.city_slug}/{entry.slug}/", {"locale": locale} if locale else {}
    )
    assert answer.status_code == 200, answer.data
    return answer.json()


def found(**query: str) -> list[str]:
    answer = APIClient().get(CATALOG_URL, query)
    assert answer.status_code == 200, answer.data
    return [item["display_name"] for item in answer.json()["items"]]


# --- the token ---------------------------------------------------------------


def test_an_origin_token_speaks_for_one_company_and_ages_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    here, elsewhere = membership("token-tu"), membership("token-tam")
    token = issue_origin("catalog", here.organization_id)

    assert read_origin(token, here.organization_id) == "catalog"
    # Another company's form learns nothing from it.
    assert read_origin(token, elsewhere.organization_id) is None
    # Not ours: no token, a changed one, one signed for something else, noise.
    assert read_origin("", here.organization_id) is None
    assert read_origin(token[:-2] + "xx", here.organization_id) is None
    assert read_origin(signing.dumps({"c": "catalog"}), here.organization_id) is None
    assert read_origin("x" * 4000, here.organization_id) is None
    # Only the channels a token can vouch for are issued.
    with pytest.raises(ValueError, match="company_site"):
        issue_origin("company_site", here.organization_id)
    # It fits the booking's column, with room to spare.
    assert len(token) < origin_tokens.ORIGIN_TOKEN_MAX_LENGTH - 60

    monkeypatch.setattr(origin_tokens, "ORIGIN_MAX_AGE", timedelta(seconds=-1))
    assert read_origin(token, here.organization_id) is None


# --- the badge and the filter ------------------------------------------------


def test_the_listing_marks_and_filters_the_companies_booked_online() -> None:
    configured = form("katalog-odznaka", priced=False)
    owner: Membership = configured["owner"]
    entry = listed(owner)
    # A company in the catalogue that takes no bookings online.
    plain = membership("katalog-bez-rezerwacji")
    listed(plain, name="Bez Rezerwacji")

    assert entry.badges == ["online_booking"]
    assert badge_keys() == ["online_booking"]
    assert found() == ["Bez Rezerwacji", "Domki nad Jeziorem"]
    assert found(badge="online_booking") == ["Domki nad Jeziorem"]
    # A key the catalogue does not know is no filter at all.
    assert found(badge="anything") == ["Bez Rezerwacji", "Domki nad Jeziorem"]
    (row,) = [
        item for item in APIClient().get(CATALOG_URL).json()["items"] if item["slug"] == entry.slug
    ]
    assert row["badges"] == ["online_booking"]
    assert APIClient().get(f"{CATALOG_URL}dictionary/").json()["badges"] == ["online_booking"]
    # The engine filters by the same copy.
    assert "badges" in INDEX_SETTINGS["filterableAttributes"]
    assert _filters(None, "", "online_booking") == ['badges = "online_booking"']

    # The offer leaves the form: the row follows, and so does the listing.
    with tenant(owner):
        offer = Service.all_objects.get(pk=configured["service"].id)
        save_service(
            service_id=offer.id,
            data={"online": False},
            expected_version=offer.version,
            idempotency_key=key(),
        )
    entry.refresh_from_db()
    assert entry.badges == []
    assert found(badge="online_booking") == []
    assert card_of(entry)["booking"] is None


def test_the_badge_needs_the_form_and_the_plan(settings: Any) -> None:
    configured = form("katalog-odznaka-plan", priced=False)
    owner: Membership = configured["owner"]
    organization_id = owner.organization_id

    assert catalog_card.books_online(organization_id) is True

    # The plan stops covering bookings: nothing is booked there online.
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=organization_id)
    snapshot.features = {**snapshot.features, "booking.enabled": False}
    snapshot.save()
    assert catalog_card.books_online(organization_id) is False
    with tenant(owner):
        assert catalog_card.card(organization_id, "pl") is None

    snapshot.features = {**snapshot.features, "booking.enabled": True}
    snapshot.save()
    # A product without public forms has no such badge to give.
    settings.PUBLIC_BOOKING_ENABLED = False
    assert catalog_card.books_online(organization_id) is False


def test_rows_written_before_the_badge_get_it_from_the_command() -> None:
    configured = form("katalog-odznaka-wstecz", priced=False)
    entry = listed(configured["owner"])
    # As a deploy finds it: published before badges were kept.
    CatalogEntry.all_objects.filter(pk=entry.pk).update(badges=[])

    said = StringIO()
    call_command("refresh_catalog_badges", stdout=said)
    again = StringIO()
    call_command("refresh_catalog_badges", stdout=again)

    entry.refresh_from_db()
    assert entry.badges == ["online_booking"]
    assert "zmienione: 1" in said.getvalue()
    assert "zmienione: 0" in again.getvalue()


# --- the card ----------------------------------------------------------------


def test_the_card_says_what_can_be_booked_and_vouches_for_the_way_there() -> None:
    configured = form("katalog-karta")
    owner: Membership = configured["owner"]
    first, photo = shown_unit(configured)
    MediaAsset.all_objects.filter(pk=photo.id).update(
        ai_origin=AiOrigin.GENERATED, width=1600, height=1200
    )
    entry = listed(owner)

    card = card_of(entry)
    booking = card["booking"]

    assert card["badges"] == ["online_booking"]
    assert booking["form_url"].endswith("/book/katalog-karta")
    # The token is the catalogue's word for this company, and for no other.
    assert read_origin(booking["origin"], owner.organization_id) == "catalog"
    assert read_origin(booking["origin"], membership("katalog-karta-obca").organization_id) is None
    # The group of cottages is one thing to book: the unit the company shows
    # speaks for it, under the group's name and the unit's address.
    (unit,) = booking["units"]
    assert (unit["slug"], unit["name"], unit["range_unit"]) == (
        first.public_slug,
        "Domek 6-os.",
        "night",
    )
    assert unit["town"] == {"slug": TOWN, "name": "Mrągowo"}
    assert unit["from_price"] == {"gross_minor": 30000, "currency": "PLN", "per": "night"}
    assert unit["photo"] == {
        "id": str(photo.id),
        "thumbnail_url": f"/api/v1/booking/public/katalog-karta/photos/{photo.id}/thumbnail/",
        "preview_url": f"/api/v1/booking/public/katalog-karta/photos/{photo.id}/preview/",
        "width": 1600,
        "height": 1200,
        # A picture a model made is marked where it is shown (ADR-059).
        "ai_generated": True,
    }
    # A unit's point is the company's and the server's.
    assert "53.864" not in str(card)


def test_a_company_that_books_visits_only_has_a_form_and_no_units() -> None:
    owner = membership("katalog-wizyty")
    catalog(owner)
    # The form's address, as saving an offer in the panel gives it.
    PublicBookingRoute.objects.create(
        public_slug="katalog-wizyty", organization_id=owner.organization_id
    )
    entry = listed(owner, name="Gabinet")

    booking = card_of(entry)["booking"]

    assert entry.badges == ["online_booking"]
    assert booking["form_url"].endswith("/book/katalog-wizyty")
    assert booking["units"] == []


# --- the unit's page ----------------------------------------------------------


def test_a_unit_the_form_shows_has_a_page_under_the_card() -> None:
    configured = form("katalog-jednostka", priced=False, units=2)
    owner: Membership = configured["owner"]
    first, photo = shown_unit(configured)
    entry = listed(owner)
    url = f"{CATALOG_URL}{entry.city_slug}/{entry.slug}/units/{first.public_slug}/"

    with CaptureQueriesContext(connection) as queries:
        answer = APIClient().get(url, {"locale": "en"})

    assert answer.status_code == 200, answer.data
    page = answer.json()
    # The card it stands under, for the page's frame and the company's node.
    assert page["company"]["display_name"] == "Domki nad Jeziorem"
    assert (page["company"]["city_slug"], page["company"]["slug"]) == (TOWN, entry.slug)
    # A company that lets cottages by the night is a lodging business.
    assert page["company"]["business_type"] == "LodgingBusiness"
    unit = page["unit"]
    assert (unit["slug"], unit["name"], unit["capacity"]) == (first.public_slug, "Domek 6-os.", 6)
    assert [item["id"] for item in unit["photos"]] == [str(photo.id)]
    # The dictionary's words follow the page; the company's stay its own
    # where it wrote none in that language.
    assert unit["amenities"] == [
        {"key": "wifi", "label": "Wi-Fi"},
        {"key": "sauna", "label": "Sauna"},
    ]
    assert (unit["locale"], unit["source_locale"], unit["translated_locales"]) == ("pl", "pl", [])
    # No price list, no „od X zł”.
    assert unit["from_price"] is None
    # Booked through the offer, by choosing the group the unit speaks for.
    assert page["offers"] == [
        {
            "id": str(configured["service"].id),
            "name": "Pobyt w domku",
            "range_unit": "night",
            "choice": {"kind": "group", "id": str(configured["group"].id)},
        }
    ]
    form_facts = page["booking"]
    assert form_facts["form_slug"] == "katalog-jednostka"
    assert (form_facts["timezone"], form_facts["paused"]) == ("Europe/Warsaw", False)
    assert read_origin(form_facts["origin"], owner.organization_id) == "catalog"
    assert page["thing"]["@type"] == "Accommodation"
    assert "53.864" not in str(page)

    # The test database bypasses row-level security, so the order of the
    # statements stands in for isolation: the tenant is set before anything of
    # booking is read (AGENTS.md).
    statements = [query["sql"] for query in queries]
    first_tenant = next(n for n, sql in enumerate(statements) if "app.organization_id" in sql)
    first_booking = next(
        n
        for n, sql in enumerate(statements)
        if '"booking_' in sql and "booking_publicbookingroute" not in sql
    )
    assert first_tenant < first_booking

    # No such unit, a unit the company does not show, and no such card.
    other = configured["units"][1]
    assert other.public_slug == ""
    gone = APIClient().get(f"{CATALOG_URL}{entry.city_slug}/{entry.slug}/units/nie-ma/")
    assert (gone.status_code, gone.json()["code"]) == (404, "catalog_unit_not_found")
    nowhere = APIClient().get(f"{CATALOG_URL}{TOWN}/nie-ma-firmy/units/{first.public_slug}/")
    assert (nowhere.status_code, nowhere.json()["code"]) == (404, "catalog_entry_not_found")

    # Taken off the form, the unit's page is gone with it.
    change(owner, first, public=False)
    assert APIClient().get(url).status_code == 404


# --- the booking's channel ----------------------------------------------------


def test_a_booking_the_catalogue_sent_says_so_and_so_does_its_order() -> None:
    configured = form("katalog-kanal")
    owner: Membership = configured["owner"]
    with_orders(owner.organization_id)
    entry = listed(owner)
    client = APIClient()
    origin = card_of(entry)["booking"]["origin"]
    digest = quoted(client, configured).json()["quote"]["digest"]

    made = booked(client, configured, quote_digest=digest, origin=origin)

    assert made.status_code == 201, made.data
    with tenant(owner):
        appointment = Appointment.all_objects.get(pk=made.json()["id"])
        (order,) = Order.all_objects.filter(organization_id=owner.organization_id)
    assert (appointment.channel, appointment.origin_token) == ("catalog", origin)
    # The order copies the booking's channel (ADR-073 §3).
    assert order.channel == "catalog"


def test_a_token_that_does_not_hold_never_refuses_a_booking() -> None:
    configured = form("katalog-kanal-obcy", priced=False, units=3)
    owner: Membership = configured["owner"]
    client = APIClient()
    foreign = issue_origin("catalog", membership("katalog-kanal-inna").organization_id)
    first = configured["first"]

    def stay(week: int, **body: Any) -> str:
        start = first + timedelta(days=7 * week)
        answer = booked(
            client,
            {
                **configured,
                "dates": {
                    "start_date": start.isoformat(),
                    "end_date": (start + timedelta(days=2)).isoformat(),
                },
            },
            **body,
        )
        assert answer.status_code == 201, answer.data
        return str(answer.json()["id"])

    # By itself, with another company's token and with noise: the company's
    # own form, and nothing kept of what did not hold.
    from_form = [stay(0), stay(1, origin=foreign), stay(2, origin="nie-token")]
    with tenant(owner):
        plain, borrowed, noise = (Appointment.all_objects.get(pk=made) for made in from_form)
        # The team's own booking is the office's, whatever it is handed.
        start = first + timedelta(days=28)
        office = book_stay(
            service_id=configured["service"].id,
            group_id=configured["group"].id,
            start_date=start,
            end_date=start + timedelta(days=2),
            customer_data=GUEST,
            idempotency_key=key(),
            principal_ref=str(owner.id),
            origin=issue_origin("catalog", owner.organization_id),
        ).appointment

    assert [(item.channel, item.origin_token) for item in (plain, borrowed, noise, office)] == [
        ("company_site", ""),
        ("company_site", ""),
        ("company_site", ""),
        ("office", ""),
    ]
    # A token longer than any of ours is a malformed request, not a booking.
    refused = booked(client, configured, origin="x" * 300)
    assert refused.status_code == 400


def test_the_panel_reads_where_a_booking_came_from() -> None:
    configured = form("katalog-kanal-panel", priced=False)
    owner: Membership = configured["owner"]
    origin = issue_origin("catalog", owner.organization_id)
    made = booked(APIClient(), configured, origin=origin)
    assert made.status_code == 201, made.data

    from saas_core.modules.shared.booking.views import _appointment_payload

    with tenant(owner):
        payload = _appointment_payload(Appointment.all_objects.get(pk=made.json()["id"]))

    assert payload["channel"] == "catalog"
    # What the guest gets back says nothing about the channel.
    assert "channel" not in made.json()


# --- the category hint --------------------------------------------------------


def test_an_offer_made_from_a_preset_hints_the_cards_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = membership("katalog-podpowiedz")
    known = known_categories(owner)
    with tenant(owner):
        assert catalog_card.category_hint(owner.organization_id) == ""
        apply_preset(preset_id="core.lodging", name="Domek", idempotency_key=key())
        # The preset's own category; the card is offered it only where the
        # company's dictionary has such a category.
        assert catalog_card.category_hint(owner.organization_id) == "turystyka-i-noclegi"
        assert hinted_category(owner.organization_id, known) == (
            "turystyka-i-noclegi" if "turystyka-i-noclegi" in known else ""
        )
        assert hinted_category(owner.organization_id, {"inna": object()}) == ""

    # Whatever the product's dictionary is: a hint in it reaches the card's
    # form while the card has no category, and sets nothing.
    wanted = next(iter(known))
    monkeypatch.setitem(
        catalog_listing._hints, "shared.booking.presets", lambda _organization_id: wanted
    )
    snapshot = EntitlementSnapshot.all_objects.get(organization_id=owner.organization_id)
    snapshot.features = {**snapshot.features, "profiles.enabled": True}
    snapshot.sources = {**snapshot.sources, "profiles.enabled": {"kind": "plan"}}
    snapshot.save()
    from saas_core.modules.shared.profiles.views import _catalog_state

    with tenant(owner):
        profile = organization_profile()
        assert profile.category == ""
        assert _catalog_state(None, profile)["suggested_category"] == wanted
        taken = update_profile(profile.id, expected_version=profile.version, category=wanted)
        # A card that has a category is told nothing.
        assert _catalog_state(None, taken)["suggested_category"] == ""


# --- what the company is -------------------------------------------------------


def test_a_company_that_lets_units_by_the_night_is_a_lodging_business() -> None:
    configured = form("katalog-noclegi", priced=False)
    owner: Membership = configured["owner"]
    entry = listed(owner, contact_address="ul. Jeziorna 1")
    organization_id = owner.organization_id

    with tenant(owner):
        # Whatever shelf of the catalogue the card stands on (ADR-071 pkt 16).
        facts = organization_facts(organization_id)
        assert facts is not None and facts.business_type == "LodgingBusiness"
        assert facts.as_snapshot()["business_type"] == "LodgingBusiness"
    assert card_of(entry)["business_type"] == "LodgingBusiness"

    # Switched off, the offer makes the company nothing: its category speaks.
    category = known_categories(owner)[entry.category]
    with tenant(owner):
        offer = Service.all_objects.get(pk=configured["service"].id)
        save_service(
            service_id=offer.id,
            data={"active": False},
            expected_version=offer.version,
            idempotency_key=key(),
        )
        assert catalog_card.business_type(organization_id) == ""
        facts = organization_facts(organization_id)
        assert facts is not None and facts.business_type == category.schema_type
    assert card_of(entry)["business_type"] == category.schema_type


def test_visits_and_day_rentals_make_no_lodging_business() -> None:
    owner = membership("katalog-nie-noclegi")
    configured = catalog(owner)
    with tenant(owner):
        save_service(
            service_id=None,
            data={
                "name": "Kajak na dzień",
                "time_model": "range",
                "range_unit": "day",
                "staff_count": 0,
                "resource_ids": [configured["resource"].id],
            },
            idempotency_key=key(),
        )
        assert catalog_card.business_type(owner.organization_id) == ""
