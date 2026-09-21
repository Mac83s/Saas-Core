"""The closed dictionary the public catalogue filters and addresses by.

ADR-053 §7. City and category are not free text: `city_slug` is a segment of a
public URL and both are filter buckets, so three spellings of one town would be
three addresses and three buckets. The list is deliberately incomplete and grows
with sales reach — adding an entry is a contract change visible in a diff,
because each entry is a public address.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class City:
    slug: str
    name: str
    voivodeship: str


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    label: dict[str, str]


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
        entry["slug"]: City(entry["slug"], entry["name"], entry["voivodeship"]) for entry in raw
    }


@cache
def categories(organization_type: str) -> dict[str, Category]:
    """Categories for one organization type (ADR-050).

    Unknown type means an empty dictionary rather than a fallback to another
    type's list: a product that adds a type and forgets its categories should
    see "no categories", not somebody else's.
    """
    raw = _manifest().get("categories")
    if not isinstance(raw, dict):
        raise ImproperlyConfigured("Kontrakt katalogu nie zawiera kategorii.")
    entries = raw.get(organization_type) or []
    return {entry["key"]: Category(entry["key"], entry["label"]) for entry in entries}
