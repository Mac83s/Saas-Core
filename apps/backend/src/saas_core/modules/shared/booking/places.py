"""Where a visit takes place (ADR-066).

A visit is booked at one of the company's locations, but a field visit happens
somewhere else — at a farm, at a customer's house. The visit's own „Miejsce
wizyty” (`Appointment.place_town`, `place_address`) says it first; where it is
empty, the module that hangs its detail on the appointment may still know.

Core knows no product by name, so a module registers from its own
`AppConfig.ready` through `booking.api`:

- `register_appointment_place`: the town of visits it knows (a herd visit's
  farm), shown where the visit's own place is empty;
- `register_place_search`: places the company keeps, offered in the visit
  form as „Zapisane miejsce”, so choosing one fills the town and the address.
  (HoofCare offers its farms in its own section of the form instead, ADR-067.)

A provider answers without its module's permission with nothing, never with an
error; one that fails anyway is logged and skipped, inside a savepoint, so the
change the caller has just made and the rest of the list stand.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .services import BOOKING_ENABLED, BOOKING_MANAGE

#: Appointment ids → the town (or the nearest name of the place) for those it knows.
PlaceProvider = Callable[[Sequence[UUID]], Mapping[UUID, str]]


@dataclass(frozen=True, slots=True)
class PlaceSuggestion:
    """A place the company keeps, as the visit form offers it."""

    #: What the office knows it by, e.g. a farm's name.
    name: str
    town: str
    address: str = ""


#: A search text ("" for all) → the company's places that match, at most `limit`.
PlaceSearch = Callable[[str, int], Sequence[PlaceSuggestion]]

_providers: dict[str, PlaceProvider] = {}
_searches: dict[str, PlaceSearch] = {}

logger = logging.getLogger(__name__)


def register_appointment_place(name: str, provider: PlaceProvider) -> None:
    _providers[name] = provider


def register_place_search(name: str, search: PlaceSearch) -> None:
    _searches[name] = search


def appointment_places(ids: Sequence[UUID]) -> dict[UUID, str]:
    """One call per provider for the whole list, so a calendar of a month
    costs a query, not a query per visit; the first answer wins."""
    places: dict[UUID, str] = {}
    if not ids:
        return places
    for name, provider in _providers.items():
        try:
            with transaction.atomic():
                answer = provider(ids)
        except Exception:
            logger.exception("Dostawca miejsca wizyty zawiódł.", extra={"provider": name})
            continue
        for key, value in answer.items():
            if value:
                places.setdefault(key, value)
    return places


def has_place_search() -> bool:
    return bool(_searches)


def search_places(query: str = "", limit: int = 200) -> list[PlaceSuggestion]:
    """Every registered search, in turn, until `limit`. A search checks its
    own module's read permission and answers nothing without it; the list is
    for whoever books visits."""
    authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    limit = max(1, min(limit, 500))
    found: list[PlaceSuggestion] = []
    for name, search in _searches.items():
        try:
            with transaction.atomic():
                found.extend(search(query.strip(), limit - len(found)))
        except Exception:
            logger.exception("Wyszukiwanie miejsc zawiodło.", extra={"provider": name})
            continue
        if len(found) >= limit:
            break
    return found[:limit]
