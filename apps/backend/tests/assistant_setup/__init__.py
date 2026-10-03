"""What the configurator's tests (`test_assistant_configurator.py`) stand on.

The example profiles are the contract's own
(`packages/contracts/assistant/examples/`). The catalogues here are frozen
copies, small on purpose: the golden tests assert the configurator's rules, so
they must not move when a preset becomes ready or a town joins the directory.
What the product can do today is asserted once, against the real contract, in
`test_what_the_product_can_do_today`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings

from saas_core.modules.shared.assistant.configurator import (
    CARD,
    CARD_OPTIONS,
    LANGUAGES,
    ORGANIZATION,
    PRESETS,
    PRICES,
    SEASONS,
    SETUP,
)

CONTRACTS = Path(settings.BASE_DIR).parent.parent / "packages" / "contracts"
EXAMPLES = ("hairdresser", "plumber", "cottages", "kayak-rental")

#: The registry the golden outputs are written against: a place and a person
#: can be added, an offer starts from its preset, a stay gets its units and its
#: seasons, an offer its price, and a draft the notes dropped is taken back. A
#: test of what happens without a command takes it out.
COMMANDS = frozenset({
    "organization.update@1",
    "organization.public_locales.update@1",
    "profiles.organization.update@1",
    "booking.location.save@1",
    "booking.staff.add@1",
    "booking.preset.apply@1",
    "booking.offer.create@1",
    "booking.offer.update@1",
    "booking.staff.hours.set@1",
    "booking.offer.units.set@1",
    "booking.price.save@1",
    "booking.season.save@1",
    "booking.offer.discard@1",
})
SEASON_FIELDS = (
    "season_id",
    "service_id",
    "group_id",
    "resource_id",
    "name",
    "starts_on",
    "ends_on",
    "min_length",
    "max_length",
    "length_multiple",
    "start_weekdays",
    "end_weekdays",
    "notice_hours",
    "window_days",
    "closed",
    "buffer_after_minutes",
    "active",
)
PERSON_FIELDS = ("name", "phone", "service_ids", "hours", "invitation")
PRICE_FIELDS = (
    "price_id",
    "service_id",
    "group_id",
    "resource_id",
    "name",
    "starts_on",
    "ends_on",
    "weekdays",
    "local_from",
    "local_to",
    "basis",
    "amount_minor",
    "vat_code",
    "included_people",
    "extra_person_amount_minor",
    "extra_person_per_time_unit",
    "category_prices",
    "length_discounts",
    "active",
)
VAT_OPTIONS = [
    {"value": "23", "label": {"pl": "23%", "en": "23%"}},
    {"value": "8", "label": {"pl": "8%", "en": "8%"}},
    {"value": "5", "label": {"pl": "5%", "en": "5%"}},
    {"value": "0", "label": {"pl": "0%", "en": "0%"}},
    {"value": "zw", "label": {"pl": "zwolnione z VAT", "en": "VAT exempt"}},
    {"value": "np", "label": {"pl": "nie podlega VAT", "en": "outside VAT"}},
]
CARD_FIELDS = (
    "display_name",
    "headline",
    "bio",
    "contact_email",
    "contact_phone",
    "contact_address",
    "city_slug",
    "category",
)
SERVICE_FIELDS = (
    "name",
    "duration_minutes",
    "buffer_before_minutes",
    "buffer_after_minutes",
    "minimum_notice_minutes",
    "staff_count",
    "public_staff_choice",
    "slot_step_minutes",
    "staff_ids",
    "location_ids",
    "resource_ids",
)


def example(name: str) -> dict[str, Any]:
    path = CONTRACTS / "assistant" / "examples" / f"{name}.json"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _preset(
    preset_id: str,
    readiness: str,
    time_model: str,
    name: tuple[str, str],
    *,
    staff: str = "none",
    subject: str = "unit",
    place: str = "business",
    required_inputs: tuple[str, ...] = (),
    catalog_category: str | None = None,
    range_unit: str | None = None,
) -> dict[str, Any]:
    """An entry of `booking.preset.list@1`, in its shape."""
    return {
        "id": preset_id,
        "version": 1,
        "readiness": readiness,
        "labels": {
            "pl": {"name": name[0], "description": ""},
            "en": {"name": name[1], "description": ""},
        },
        "time_model": time_model,
        "range_unit": range_unit,
        "booked_subject": subject,
        "booked_staff": staff,
        "place": place,
        "required_inputs": list(required_inputs),
        "catalog_category": catalog_category,
        # Only a visit at the company's place is booked through the site.
        "online_booking": readiness if (time_model, place) == ("slot", "business") else "soon",
    }


PRESET_LIST = {
    "presets": [
        _preset(
            "core.specialist_visit",
            "ready",
            "slot",
            ("Wizyta u specjalisty", "Appointment with a specialist"),
            staff="required",
            subject="staff",
        ),
        _preset(
            "core.service_at_customer",
            "soon",
            "slot",
            ("Usługa u klienta", "Service at the customer's"),
            staff="required",
            subject="staff",
            place="customer",
        ),
        _preset(
            "core.lodging",
            "soon",
            "range",
            ("Nocleg", "Stay"),
            required_inputs=("season_dates", "min_length", "photos"),
            catalog_category="turystyka-i-noclegi",
            range_unit="night",
        ),
        _preset(
            "core.rental",
            "soon",
            "range",
            ("Wypożyczalnia", "Rental"),
            staff="optional",
            subject="unit_group",
            place="pickup_return",
            range_unit="day",
        ),
    ]
}


def kinds(presets: dict[str, Any], *, ready: bool) -> list[dict[str, Any]]:
    """The kinds of booking a question offers (`ready`), or names as coming."""
    return [
        {
            "value": preset["id"],
            "label": {language: words["name"] for language, words in preset["labels"].items()},
        }
        for preset in presets["presets"]
        if (preset["readiness"] == "ready") is ready
    ]


CATALOG_OPTIONS = {
    "categories": [
        {
            "key": "uroda-i-zdrowie",
            "label": {"pl": "Uroda i zdrowie", "en": "Beauty and health"},
            "keywords": {"pl": ["fryzjer", "kosmetyczka"], "en": ["hairdresser"]},
        },
        {
            "key": "uslugi-dla-domu",
            "label": {"pl": "Usługi dla domu", "en": "Home services"},
            "keywords": {"pl": ["hydraulik", "elektryk"], "en": ["plumber"]},
        },
        {
            "key": "turystyka-i-noclegi",
            "label": {"pl": "Turystyka i noclegi", "en": "Travel and stays"},
            "keywords": {"pl": ["noclegi", "wypożyczalnia kajaków"], "en": ["kayak rental"]},
        },
    ],
    "cities": [
        {"slug": "mragowo", "name": "Mrągowo", "voivodeship": "warmińsko-mazurskie"},
        {"slug": "olsztyn", "name": "Olsztyn", "voivodeship": "warmińsko-mazurskie"},
    ],
}
CATEGORY_OPTIONS = [
    {"value": category["key"], "label": category["label"]}
    for category in CATALOG_OPTIONS["categories"]
]


def new_company(name: str) -> dict[str, dict[str, Any]]:
    """The reads of a company right after it registered: a name, one language,
    no card, nothing to book."""
    return {
        ORGANIZATION: {
            "name": name,
            "slug": "firma",
            "organization_type": "business",
            "default_locale": "pl",
            "timezone": "Europe/Warsaw",
            "currency": "PLN",
            "version": 1,
        },
        LANGUAGES: {
            "public_locales": ["pl"],
            "version": 1,
            "offered": ["pl", "en", "de"],
            "additional_max": 1,
            "adding_allowed": True,
            "protected": [],
        },
        CARD: {
            "exists": False,
            "in_catalog": False,
            "version": 0,
            **dict.fromkeys(CARD_FIELDS, ""),
            "cities": [city["slug"] for city in CATALOG_OPTIONS["cities"]],
            "categories": [category["key"] for category in CATALOG_OPTIONS["categories"]],
        },
        CARD_OPTIONS: CATALOG_OPTIONS,
        SETUP: {"services": [], "locations": [], "resources": [], "groups": [], "staff": []},
        PRESETS: PRESET_LIST,
        PRICES: {
            "currency": "PLN",
            "amounts": "gross",
            "prices": [],
            "extras": [],
            "categories": [],
        },
        SEASONS: {"seasons": []},
    }


def catalog_from_contract() -> dict[str, Any]:
    """The real directory of a `business` company, in the shape of
    `profiles.catalog_options.read@1`."""
    manifest = json.loads((CONTRACTS / "catalog" / "manifest.json").read_text(encoding="utf-8"))
    return {
        "categories": [
            {
                "key": category["key"],
                "label": category["label"],
                "keywords": category.get("keywords") or {},
            }
            for category in manifest["categories"]["business"]
        ],
        "cities": [
            {"slug": city["slug"], "name": city["name"], "voivodeship": city["voivodeship"]}
            for city in manifest["cities"]
        ],
    }
