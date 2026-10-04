"""Stays on a company's own site (ADR-072, „Rozstrzygnięcia plastra 5d”): a
block of the page carries a choice and the published page says what it shows
now — the offers, what a guest chooses of each, the content of the units the
company shows — the site's host serves those units' pictures in our copies,
and the block's browser reads free days from the form's API at that host."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid7

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.api import live_site_blocks, served_media_ids
from saas_core.modules.core.organizations.models import Membership, Organization
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.booking.models import PublicBookingRoute, Service
from saas_core.modules.shared.booking.setup import save_service
from saas_core.modules.shared.booking.site_blocks import SITE_BLOCK_TYPES, site_blocks
from saas_core.modules.shared.sites.models import (
    Domain,
    DomainKind,
    DomainStatus,
    DomainTlsStatus,
    Publication,
    Site,
)
from test_booking import _no_delivery, tenant
from test_booking_prices import key
from test_booking_public_stays import form
from test_booking_unit_content import change, picture
from test_media_api import MemoryStorage

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.clear()
    _no_delivery(monkeypatch)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> MemoryStorage:
    """Where the pictures' bytes are, in place of the object store."""
    memory = MemoryStorage()
    for module in ("media.services", "sites.public_media"):
        monkeypatch.setattr(f"saas_core.modules.shared.{module}.get_object_storage", lambda: memory)
    return memory


def block(kind: str, **data: Any) -> dict[str, Any]:
    return {"block_type": f"core.{kind}", "schema_version": 1, "data": {"title": "T", **data}}


def published(owner: Membership, blocks: list[dict[str, Any]], *, locale: str = "pl") -> str:
    """The company's site with one page of `blocks`, published; its host."""
    organization = owner.organization
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    snapshot.features = {**snapshot.features, "sites.enabled": True}
    snapshot.sources = {**snapshot.sources, "sites.enabled": {"kind": "plan"}}
    snapshot.save()
    slug = f"witryna-{uuid7().hex[-8:]}"
    site = Site.all_objects.create(
        organization=organization,
        name="Domki",
        slug=slug,
        default_locale=locale,
        created_by=owner.user,
        idempotency_key=slug,
        request_hash="0" * 64,
    )
    host = f"{slug}.example.test"
    Domain.all_objects.create(
        organization=organization,
        site=site,
        hostname=host,
        kind=DomainKind.PLATFORM,
        status=DomainStatus.VERIFIED,
        tls_status=DomainTlsStatus.ELIGIBLE,
        is_canonical=True,
        verification_name=f"_saas.{host}",
        verification_token="token",
        created_by=owner.user,
        idempotency_key=slug,
        request_hash="0" * 64,
    )
    publication = Publication.all_objects.create(
        organization=organization,
        site=site,
        sequence=1,
        snapshot={
            "site_id": str(site.id),
            "site_slug": site.slug,
            "default_locale": locale,
            "design_tokens": {
                "schemaVersion": 1,
                "palette": "neutral",
                "typography": "sans",
                "radius": "medium",
                "spacing": "comfortable",
            },
            "pages": [
                {
                    "page_id": str(uuid7()),
                    "key": "home",
                    "page_type": "homepage",
                    "version_id": str(uuid7()),
                    "version": 1,
                    "blocks": blocks,
                    "media_asset_ids": [],
                    "locales": [
                        {
                            "locale": locale,
                            "path": "/",
                            "canonical_path": "/",
                            "title": "Domki",
                            "description": "Domki nad jeziorem",
                            "social_title": "Domki",
                            "social_description": "Domki nad jeziorem",
                        }
                    ],
                    "hreflang": {locale: "/"},
                    "x_default": "/",
                }
            ],
        },
        snapshot_hash="",
        created_by=owner.user,
        idempotency_key="published",
    )
    Site.all_objects.filter(pk=site.pk).update(current_publication=publication)
    return host


def page(host: str) -> Any:
    answer = APIClient().get("/api/v1/public/site/", {"path": "/"}, HTTP_HOST=host)
    assert answer.status_code == 200, answer.content
    return answer.json()


def test_a_published_page_says_what_its_stay_blocks_show_now() -> None:
    configured = form("bloki-pobytu")
    owner: Membership = configured["owner"]
    (first,) = configured["units"]
    photo = picture(owner)
    change(
        owner,
        first,
        public=True,
        photo_ids=[photo.id],
        amenities=["sauna", "wifi"],
        city_slug="mragowo",
        latitude="53.864000",
        longitude="21.305000",
    )
    offer = str(configured["service"].id)
    host = published(
        owner,
        [
            {"block_type": "core.hero", "schema_version": 1, "data": {"heading": "Domki"}},
            block("stay_units"),
            block("stay_search", offer=offer),
            # An offer that is not the company's: the block shows nothing.
            block("stay_calendar", offer=str(uuid7())),
        ],
    )

    answer = page(host)
    live = answer["live"]

    # By the block's position, and only for the blocks that have something.
    assert sorted(live) == ["1", "2"]
    units, search = live["1"], live["2"]
    assert units["slug"] == "bloki-pobytu"
    assert units["form_url"].endswith("/book/bloki-pobytu")
    assert (units["timezone"], units["paused"]) == ("Europe/Warsaw", False)
    (listed,) = units["offers"]
    assert (listed["id"], listed["range_unit"]) == (offer, "night")
    (group,) = listed["choices"]
    # A group speaks with the first unit the company shows: its picture by
    # id — the site serves it — its town and what it has, in the page's words.
    assert (group["kind"], group["id"]) == ("group", str(configured["group"].id))
    assert group["photos"] == [str(photo.id)]
    assert group["amenities"] == [
        {"key": "wifi", "label": "Wi-Fi"},
        {"key": "sauna", "label": "Sauna"},
    ]
    assert group["town"] == {"slug": "mragowo", "name": "Mrągowo"}
    assert group["from_price"] == {"gross_minor": 30000, "currency": "PLN", "per": "night"}
    # The widget and the calendar ask for no content.
    assert search["offers"][0]["choices"] == [
        {
            "kind": "group",
            "id": str(configured["group"].id),
            "name": group["name"],
            "capacity": group["capacity"],
        }
    ]
    # Coordinates are the company's and the server's, on a site too.
    assert "53.864" not in json.dumps(answer) and "latitude" not in json.dumps(live)


def test_a_page_without_stay_blocks_asks_booking_nothing() -> None:
    configured = form("bloki-bez", priced=False)
    host = published(
        configured["owner"],
        [{"block_type": "core.hero", "schema_version": 1, "data": {"heading": "Domki"}}],
    )

    assert page(host)["live"] == {}
    assert (
        live_site_blocks(
            configured["owner"].organization_id, "pl", [{"block_type": "core.hero", "data": {}}]
        )
        == {}
    )


def test_a_company_without_a_form_or_the_plan_shows_no_stay_block(settings: Any) -> None:
    configured = form("bloki-plan", priced=False)
    owner: Membership = configured["owner"]
    host = published(owner, [block("stay_units")])
    assert sorted(page(host)["live"]) == ["0"]

    # The offer taken off the form: nothing booked from–to online.
    with tenant(owner):
        offer = Service.all_objects.get(pk=configured["service"].id)
        save_service(
            service_id=offer.id,
            data={"online": False},
            expected_version=offer.version,
            idempotency_key=key(),
        )
    assert page(host)["live"] == {}
    Service.all_objects.filter(pk=offer.id).update(online=True)
    assert sorted(page(host)["live"]) == ["0"]

    # The plan without booking: the form answers 403, the site draws nothing.
    snapshot = EntitlementSnapshot.all_objects.get(organization=owner.organization)
    kept = dict(snapshot.features)
    snapshot.features = {**kept, "booking.enabled": False}
    snapshot.save()
    cache.clear()
    assert page(host)["live"] == {}
    snapshot.features = kept
    snapshot.save()
    cache.clear()

    # The form's address switched off, and a product without public booking.
    PublicBookingRoute.objects.filter(organization_id=owner.organization_id).update(active=False)
    assert page(host)["live"] == {}
    PublicBookingRoute.objects.filter(organization_id=owner.organization_id).update(active=True)
    settings.PUBLIC_BOOKING_ENABLED = False
    assert page(host)["live"] == {}


def test_the_form_is_linked_in_a_language_it_speaks(settings: Any) -> None:
    configured = form("bloki-jezyk", priced=False)
    owner: Membership = configured["owner"]
    (unit,) = configured["units"]
    change(owner, unit, public=True, amenities=["sauna", "kitchen"])
    blocks = {"0": ("core.stay_units", {})}

    def shown(locale: str) -> Any:
        return site_blocks(owner.organization_id, locale, blocks)["0"]

    def words(answer: Any) -> list[str]:
        return [item["label"] for item in answer["offers"][0]["choices"][0]["amenities"]]

    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=["pl", "de"])
    # The company's language: the form in it, the dictionary's words too.
    german = shown("de")
    assert german["form_url"].endswith("/de/book/bloki-jezyk")
    assert words(german) == ["Küche", "Sauna"]
    # A page in a language the company does not have: the form in the
    # company's first — never a link to a form that is not there — and the
    # dictionary's words still in the page's language.
    english = shown("en")
    assert english["form_url"].endswith("/book/bloki-jezyk")
    assert "/en/" not in english["form_url"]
    assert words(english) == ["Kitchen", "Sauna"]

    # A company whose languages the deployment serves none of: the form is in
    # the product's first language, as a booking is.
    Organization.objects.filter(pk=owner.organization_id).update(public_locales=["de"])
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en")
    settings.SITES_DEFAULT_LOCALE = "pl"
    foreign = shown("en")
    assert foreign["form_url"].endswith("/book/bloki-jezyk")
    assert "/en/" not in foreign["form_url"] and "/de/" not in foreign["form_url"]
    assert words(foreign) == ["Kitchen", "Sauna"]
    # A language the dictionary has no words in reads English.
    assert words(shown("es")) == ["Kitchen", "Sauna"]


def test_the_sites_host_serves_a_shown_units_picture_in_our_copies(
    storage: MemoryStorage,
) -> None:
    configured = form("bloki-foto", priced=False, units=2)
    other = form("bloki-foto-cudze", priced=False)
    owner: Membership = configured["owner"]
    shown, hidden = configured["units"]
    cover, private, loose = (picture(owner, storage, name) for name in ("a", "b", "c"))
    foreign = picture(other["owner"], storage, "cudze")
    change(owner, shown, public=True, photo_ids=[cover.id])
    change(owner, hidden, photo_ids=[private.id])
    change(other["owner"], other["units"][0], public=True, photo_ids=[foreign.id])
    host = published(owner, [block("stay_units")])
    elsewhere = published(other["owner"], [block("stay_units")])
    client = APIClient()

    def get(asset: Any, variant: str = "preview/", at: str = host) -> Any:
        return client.get(f"/api/v1/public/site/media/{asset}/{variant}", HTTP_HOST=at)

    with tenant(owner):
        assert served_media_ids(owner.organization_id) == {cover.id}
    for variant in ("preview", "thumbnail"):
        served = get(cover.id, f"{variant}/")
        assert (served.status_code, served["Content-Type"]) == (200, "image/webp")
        assert served.content == variant.encode()
    # Never the original: no publication names this picture.
    assert get(cover.id, "").status_code == 404
    assert get(cover.id, "original/").status_code == 404
    # A unit that is not shown, a file no unit lists, another company's
    # picture, and this one at another company's host.
    for asset in (private.id, loose.id, foreign.id, uuid7()):
        assert get(asset).status_code == 404
    assert get(cover.id, at=elsewhere).status_code == 404
    assert get(foreign.id, at=elsewhere).status_code == 200
    # Switched off, the unit's picture is nobody's to see.
    change(owner, shown, active=False)
    assert get(cover.id).status_code == 404


def test_the_forms_reads_answer_at_a_sites_host_and_nothing_else_does() -> None:
    configured = form("bloki-host", priced=False)
    host = published(configured["owner"], [block("stay_calendar")])
    client = APIClient()
    first = configured["first"]
    query = {**configured["target"], "from": first.isoformat(), "to": first.isoformat()}

    catalogue = client.get(f"{configured['url']}/", HTTP_HOST=host)
    starts = client.get(f"{configured['url']}/stays/starts/", query, HTTP_HOST=host)
    assert (catalogue.status_code, starts.status_code) == (200, 200)
    assert starts.json()["items"] == [first.isoformat()]
    # A booking is made on the form, at the platform's host: no write here,
    # and nothing of the panel.
    quoted = client.post(
        f"{configured['url']}/stays/quote/",
        {**configured["target"], **configured["dates"]},
        format="json",
        HTTP_HOST=host,
    )
    panel = client.get("/api/v1/booking/setup/", HTTP_HOST=host)
    assert (quoted.status_code, panel.status_code) == (400, 400)


def test_the_blocks_booking_fills_are_registered_block_types() -> None:
    from saas_core.modules.shared.sites.block_contracts import site_block_contracts

    assert set(site_block_contracts().validators) >= SITE_BLOCK_TYPES
    for block_type in SITE_BLOCK_TYPES:
        validate = site_block_contracts().validate
        validate(block_type=block_type, schema_version=1, data={"title": "Domki"})
        validate(
            block_type=block_type,
            schema_version=1,
            data={"title": "Domki", "text": "…", "offer": str(uuid7()), "action_label": "Rezerwuj"},
        )
