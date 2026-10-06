"""Profiles' part of `seed_demo`: the demo companies have a business card.

A company that tells a story about bookings is found where customers look
for one. The seed fills its card — a town, a sentence about itself, a phone —
through the card's own services, as the panel's „Wizytówka” writes it, and
switches it on in the catalogue where the scenario places it: names both its
town and its category. A card the scenario gives no category waits for the
company's own choice, with the hint its offer's preset gives (ADR-072, slice
5h) — that is its story. The seed fills only what is empty and never moves a
card somebody already placed: a town or a category the company has stays.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.demo import DemoOrganization, DemoRun, DemoScenario

from .catalog import catalog_entry_for, publish_profile, publishable
from .catalog_contract import categories, cities
from .services import organization_profile, update_profile

#: The cards of the core's own Business scenario, by company. A product's
#: scenario brings its own under `profiles` in each company's data.
DEFAULTS: dict[str, dict[str, str]] = {
    "domki": {
        "headline": "Domki nad jeziorem na Mazurach — z sauną, pomostem i miejscem na ognisko",
        "bio": "Cztery domki nad samym jeziorem, kilka kilometrów od Mrągowa. Każdy z "
        "tarasem i w pełni wyposażoną kuchnią; do dyspozycji gości pomost, łódka i "
        "sauna. Rezerwacja online, z przedpłatą przelewem.",
        "city_slug": "mragowo",
        # No category: the card offers the one the „Nocleg” preset names, and
        # taking it — then switching the catalogue on — is the owner's click.
        "contact_phone": "+48 600 100 301",
        "contact_address": "ul. Jeziorna 12",
    },
    "kajaki": {
        "headline": "Wypożyczalnia kajaków na Krutyni — na dzień albo na cały spływ",
        "bio": "Kajaki jedno- i dwuosobowe z kamizelkami i workami wodoszczelnymi. "
        "Odbiór w Krutyni; rezerwacja online na wybrane dni.",
        "city_slug": "ruciane-nida",
        "category": "turystyka-i-noclegi",
        "contact_phone": "+48 600 100 302",
    },
}

#: What the seed may fill on a card, and only while it is empty.
FIELDS = ("headline", "bio", "city_slug", "category", "contact_phone", "contact_address")


def _data(scenario: DemoScenario, spec: DemoOrganization) -> dict[str, str] | None:
    data: dict[str, str] | None = spec.data.get("profiles")
    if data is None and scenario.default:
        data = DEFAULTS.get(spec.key)
    return data


def describe(scenario: DemoScenario, spec: DemoOrganization) -> list[str]:
    data = _data(scenario, spec)
    if not data:
        return []
    if _placed(data):
        return [f"wizytówka w katalogu firm: {data['city_slug']}, {data['category']}"]
    return [f"wizytówka: {data.get('city_slug', '—')}, kategoria do wyboru (podpowiedź z wzorca)"]


def _placed(data: Mapping[str, str]) -> bool:
    """The scenario says where the card stands: it is switched on."""
    return bool(data.get("city_slug") and data.get("category"))


def seed_cards(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = _data(run.scenario, spec)
        if not data or spec.key not in run.organizations:
            continue
        try:
            with run.setting_up(spec.key), run.acting(spec.key):
                _card(run, spec, data)
        except (APIException, DjangoValidationError) as error:
            run.log(f"! wizytówka {spec.name}: {getattr(error, 'detail', error)}")


def _card(run: DemoRun, spec: DemoOrganization, data: dict[str, str]) -> None:
    profile = organization_profile()
    organization = run.reload(spec.key)
    # A town or a category the product's dictionary lacks is left out, and a
    # card that cannot be placed stays out of the catalogue — without a word:
    # the scenario is one, the dictionaries are each product's own.
    known: dict[str, Mapping[str, Any]] = {
        "city_slug": cities(),
        "category": categories(organization.organization_type),
    }
    missing: dict[str, Any] = {
        field: data[field]
        for field in FIELDS
        if data.get(field)
        and not getattr(profile, field)
        and (field not in known or data[field] in known[field])
    }
    if missing:
        profile = update_profile(profile.id, expected_version=profile.version, **missing)
    if (
        _placed(data)
        and publishable(profile)
        and catalog_entry_for(profile.organization_id) is None
    ):
        entry = publish_profile()
        run.log(f"+ wizytówka {spec.name}: w katalogu pod /katalog/{entry.city_slug}/{entry.slug}/")
