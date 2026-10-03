"""The closed dictionary the public catalogue filters and addresses by.

ADR-053 §7. City and category are not free text: `city_slug` is a segment of a
public URL and both are filter buckets, so three spellings of one town would be
three addresses and three buckets. The list is deliberately incomplete and grows
with sales reach — adding an entry is a contract change visible in a diff,
because each entry is a public address.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class City:
    slug: str
    name: str
    voivodeship: str
    #: The town's centre. Distance in the catalogue is centre to centre: an
    #: entry has a town, not an address, so a finer point would be invented.
    lat: float = 0.0
    lng: float = 0.0


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    label: dict[str, str]
    #: Words search finds the category by — trades the label does not name.
    keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: The schema.org subtype of LocalBusiness every company here is; "" when
    #: the category is too wide to name one (ADR-071 pkt 16).
    schema_type: str = ""


@cache
def _manifest() -> dict[str, object]:
    path = Path(settings.CATALOG_CONTRACTS_PATH) / "manifest.json"
    try:
        manifest: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return manifest
    except (OSError, json.JSONDecodeError) as error:
        raise ImproperlyConfigured(f"Nie można odczytać kontraktu katalogu: {path}") from error


@cache
def cities() -> dict[str, City]:
    raw = _manifest().get("cities")
    if not isinstance(raw, list):
        raise ImproperlyConfigured("Kontrakt katalogu nie zawiera listy miast.")
    return {
        entry["slug"]: City(
            entry["slug"],
            entry["name"],
            entry["voivodeship"],
            float(entry.get("lat", 0.0)),
            float(entry.get("lng", 0.0)),
        )
        for entry in raw
    }


def distance_km(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    """Great-circle distance; a town-to-town answer needs nothing finer."""
    lat_a, lng_a, lat_b, lng_b = map(math.radians, (lat_a, lng_a, lat_b, lng_b))
    h = (
        math.sin((lat_b - lat_a) / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin((lng_b - lng_a) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def cities_within(lat: float, lng: float, radius_km: float) -> dict[str, float]:
    """Dictionary towns whose centre lies within the radius, with the distance.

    Both search paths filter by this list, so the engine and the database fallback
    agree on what "within 25 km" means.
    """
    found = {city.slug: distance_km(lat, lng, city.lat, city.lng) for city in cities().values()}
    return {slug: km for slug, km in found.items() if km <= radius_km}


def categories(organization_type: str) -> dict[str, Category]:
    """Categories for one organization type (ADR-050).

    Unknown type means an empty dictionary rather than a fallback to another
    type's list: a product that adds a type and forgets its categories should
    see "no categories", not somebody else's.
    """
    for configured in settings.ORGANIZATION_TYPES.values():
        if configured.key == organization_type and configured.catalog_categories is not None:
            return {
                category.key: Category(
                    category.key, category.label, category.keywords, category.schema_type
                )
                for category in configured.catalog_categories
            }
    raw = _manifest().get("categories")
    if not isinstance(raw, dict):
        raise ImproperlyConfigured("Kontrakt katalogu nie zawiera kategorii.")
    entries = raw.get(organization_type) or []
    return {
        entry["key"]: Category(
            entry["key"],
            entry["label"],
            {locale: tuple(words) for locale, words in (entry.get("keywords") or {}).items()},
            str(entry.get("schemaType") or ""),
        )
        for entry in entries
    }
