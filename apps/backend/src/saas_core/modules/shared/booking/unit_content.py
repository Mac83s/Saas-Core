"""A unit as content (ADR-072 §3, phase 5c): what a guest sees of a cottage, a
room or a kayak beyond its name — its pictures, what it has and where it is.

The company sets it on the unit (`setup.save_resource`): whether the unit is
shown at all (`public`), its address segment (`public_slug`), what it has (keys
of `UNIT_AMENITIES`), its town from the catalogue's dictionary, coordinates
that leave the server towards a guest only where the company said so
(`show_exact_location`, and then only as the map's place — `place_of`), and
its pictures from the media library, in order. A guest gets the content of
public units only — in the form's catalogue and, for a picture, at the form's
own address (`public_photo`), because the form lives on the platform's host,
where no published site vouches for a picture.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from rest_framework.exceptions import ErrorDetail, ValidationError

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.media.api import read_public_variant, unavailable_asset_ids
from saas_core.modules.shared.profiles.api import cities

from .models import Resource

#: How many pictures one unit shows: a gallery, not an archive.
MAX_UNIT_PHOTOS = 12
#: The copies of a picture a guest may be served — ours, never the original.
PHOTO_VARIANTS = ("thumbnail", "preview")

#: What a unit may have, in the order shown. A closed list with its words in
#: the guests' languages: a guest filters and compares by it, and a company's
#: own wording would be one more text to translate. A language without a word
#: reads the English one. Anything else belongs to the unit's description.
UNIT_AMENITIES: tuple[tuple[str, dict[str, str]], ...] = (
    ("wifi", {"pl": "Wi-Fi", "en": "Wi-Fi", "de": "WLAN"}),
    ("parking", {"pl": "Parking", "en": "Parking", "de": "Parkplatz"}),
    ("kitchen", {"pl": "Kuchnia", "en": "Kitchen", "de": "Küche"}),
    ("kitchenette", {"pl": "Aneks kuchenny", "en": "Kitchenette", "de": "Kochnische"}),
    ("fridge", {"pl": "Lodówka", "en": "Fridge", "de": "Kühlschrank"}),
    ("dishwasher", {"pl": "Zmywarka", "en": "Dishwasher", "de": "Geschirrspüler"}),
    ("washing_machine", {"pl": "Pralka", "en": "Washing machine", "de": "Waschmaschine"}),
    ("bathroom", {"pl": "Łazienka", "en": "Private bathroom", "de": "Eigenes Bad"}),
    ("bed_linen", {"pl": "Pościel", "en": "Bed linen", "de": "Bettwäsche"}),
    ("towels", {"pl": "Ręczniki", "en": "Towels", "de": "Handtücher"}),
    ("tv", {"pl": "Telewizor", "en": "TV", "de": "Fernseher"}),
    ("air_conditioning", {"pl": "Klimatyzacja", "en": "Air conditioning", "de": "Klimaanlage"}),
    ("heating", {"pl": "Ogrzewanie", "en": "Heating", "de": "Heizung"}),
    ("fireplace", {"pl": "Kominek", "en": "Fireplace", "de": "Kamin"}),
    (
        "terrace",
        {"pl": "Taras lub balkon", "en": "Terrace or balcony", "de": "Terrasse oder Balkon"},
    ),
    ("garden", {"pl": "Ogród", "en": "Garden", "de": "Garten"}),
    ("grill", {"pl": "Grill", "en": "Barbecue", "de": "Grill"}),
    ("sauna", {"pl": "Sauna", "en": "Sauna", "de": "Sauna"}),
    ("hot_tub", {"pl": "Balia lub jacuzzi", "en": "Hot tub", "de": "Badefass oder Whirlpool"}),
    ("lake_access", {"pl": "Dostęp do jeziora", "en": "Lake access", "de": "Seezugang"}),
    ("pier", {"pl": "Pomost", "en": "Pier", "de": "Steg"}),
    ("bikes", {"pl": "Rowery", "en": "Bikes", "de": "Fahrräder"}),
    ("playground", {"pl": "Plac zabaw", "en": "Playground", "de": "Spielplatz"}),
    ("crib", {"pl": "Łóżeczko dla dziecka", "en": "Cot", "de": "Kinderbett"}),
    (
        "pets_allowed",
        {"pl": "Zwierzęta mile widziane", "en": "Pets welcome", "de": "Haustiere willkommen"},
    ),
    ("accessible", {"pl": "Bez barier", "en": "Step-free access", "de": "Barrierefrei"}),
    ("smoke_free", {"pl": "Dla niepalących", "en": "Non-smoking", "de": "Nichtraucher"}),
)
_KEYS = tuple(key for key, _label in UNIT_AMENITIES)
#: The fields of a unit that are its content, as the history keeps them.
CONTENT_FIELDS = (
    "public",
    "public_slug",
    "amenities",
    "city_slug",
    "latitude",
    "longitude",
    "show_exact_location",
    "photos",
)


def unit_options() -> dict[str, Any]:
    """What a unit's content may be set to, for whoever sets units up: the
    amenities with their words and how many pictures a unit takes. The towns
    are the catalogue's dictionary (`GET /catalog/dictionary/`)."""
    return {
        "amenities": [{"key": key, "label": dict(label)} for key, label in UNIT_AMENITIES],
        "max_photos": MAX_UNIT_PHOTOS,
    }


def amenities_in(keys: Iterable[str], locale: str) -> list[dict[str, str]]:
    """What a unit has, in the dictionary's order and the guest's words."""
    wanted = set(keys)
    return [
        {"key": key, "label": label.get(locale, label["en"])}
        for key, label in UNIT_AMENITIES
        if key in wanted
    ]


def town_of(unit: Resource) -> dict[str, str] | None:
    """The unit's town as a guest reads it; never its coordinates."""
    city = cities().get(unit.city_slug) if unit.city_slug else None
    return {"slug": city.slug, "name": city.name} if city else None


def place_of(unit: Resource) -> dict[str, Any] | None:
    """Where the unit is, as much as the company shows: its own point once
    the company switched „Pokaż dokładne położenie” on, otherwise the centre
    of its town — the dictionary's, the same for every company there — and
    nothing for a unit with neither. The one reading of a unit's coordinates
    towards a guest: the map on the company's site and what the unit's own
    page tells a search engine ask here, nothing else carries them."""
    town = town_of(unit)
    if unit.show_exact_location and unit.latitude is not None and unit.longitude is not None:
        return {
            "town": town,
            "exact": True,
            "latitude": float(unit.latitude),
            "longitude": float(unit.longitude),
        }
    city = cities().get(unit.city_slug) if unit.city_slug else None
    if city is None or not (city.lat or city.lng):
        return None
    return {"town": town, "exact": False, "latitude": city.lat, "longitude": city.lng}


def _refuse(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(message, code=code)]})


def check_content(organization: Organization, unit: Resource | None, data: dict[str, Any]) -> None:
    """Validates what a write sets of a unit's content and puts it in the
    shape the unit keeps: amenities in the dictionary's order, pictures once
    each under `photos`. Refuses with the field and a code."""
    if "amenities" in data:
        given = set(data["amenities"] or ())
        if given - set(_KEYS):
            raise _refuse("amenities", "Nie ma takiego wyposażenia na liście.", "amenity_unknown")
        data["amenities"] = [key for key in _KEYS if key in given]
    if data.get("city_slug") and data["city_slug"] not in cities():
        raise _refuse("city_slug", "Nie ma takiej miejscowości w słowniku.", "city_unknown")
    latitude = data.get("latitude", unit.latitude if unit else None)
    longitude = data.get("longitude", unit.longitude if unit else None)
    if (latitude is None) != (longitude is None):
        raise _refuse(
            "latitude" if latitude is None else "longitude",
            "Podaj obie współrzędne albo żadnej.",
            "coordinates_incomplete",
        )
    # A point nobody gave cannot be shown; taking the point away takes the
    # switch with it only when the caller says so.
    if latitude is None and data.get(
        "show_exact_location", unit.show_exact_location if unit else False
    ):
        raise _refuse(
            "show_exact_location",
            "Podaj współrzędne jednostki, zanim pokażesz jej dokładne położenie.",
            "coordinates_missing",
        )
    if "photo_ids" in data:
        photos = list(dict.fromkeys(data.pop("photo_ids") or ()))
        if len(photos) > MAX_UNIT_PHOTOS:
            raise _refuse(
                "photo_ids", f"Jednostka ma najwyżej {MAX_UNIT_PHOTOS} zdjęć.", "photos_too_many"
            )
        # A picture the unit already shows stays; a new one has to be in the
        # library, scanned and not deleted.
        added = set(photos) - set(unit.photos if unit else ())
        if unavailable_asset_ids(organization_id=organization.id, asset_ids=added):
            raise _refuse(
                "photo_ids", "Tego zdjęcia nie ma w bibliotece mediów.", "photo_unavailable"
            )
        data["photos"] = photos


def shown_photo_ids(organization_id: UUID) -> set[UUID]:
    """Every picture a unit of the company shows now, public or not: media
    keeps their objects while a unit lists them (the registry of public
    sources, ADR-074 pkt 7). The caller holds the company's tenant."""
    shown: set[UUID] = set()
    for photos in Resource.all_objects.filter(organization_id=organization_id).values_list(
        "photos", flat=True
    ):
        shown.update(photos)
    return shown


def public_photo_ids(organization_id: UUID) -> set[UUID]:
    """The pictures a guest may be served: those of the units the company
    shows — public and switched on."""
    served: set[UUID] = set()
    for photos in Resource.all_objects.filter(
        organization_id=organization_id, public=True, active=True
    ).values_list("photos", flat=True):
        served.update(photos)
    return served


def photo_urls(public_slug: str, asset_id: UUID) -> dict[str, Any]:
    """Where a guest's browser gets a unit's picture: the form's own address
    on the platform's host, one for each of its copies."""
    base = f"/api/v1/booking/public/{public_slug}/photos/{asset_id}"
    return {
        "id": asset_id,
        **{f"{variant}_url": f"{base}/{variant}/" for variant in PHOTO_VARIANTS},
    }


def public_photo(asset_id: UUID, variant: str) -> bytes | None:
    """The bytes of a picture a guest asked for, or None for anything that is
    not one: another company's file, a unit that is not shown or is switched
    off, a file no unit lists, an unknown copy. The caller holds the tenant
    the form's address names (its public context is enough)."""
    organization_id = require_tenant_context().organization_id
    if variant not in PHOTO_VARIANTS or asset_id not in public_photo_ids(organization_id):
        return None
    return read_public_variant(asset_id=asset_id, variant=variant)
