"""Where a visit takes place, said by the module that knows it.

A visit is booked at one of the company's locations, but a field visit happens
somewhere else — at a farm, at a customer's house — and only the module that
hangs its detail on the appointment knows where. Core knows no product by name,
so a module registers a provider from its own `AppConfig.ready` through
`booking.api.register_appointment_place`; without one the calendar has no place
to show and says nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

#: Appointment ids → the town (or the nearest name of the place) for those it knows.
PlaceProvider = Callable[[Sequence[UUID]], Mapping[UUID, str]]

_providers: dict[str, PlaceProvider] = {}


def register_appointment_place(name: str, provider: PlaceProvider) -> None:
    _providers[name] = provider


def appointment_places(ids: Sequence[UUID]) -> dict[UUID, str]:
    """One call per provider for the whole list, so a calendar of a month
    costs a query, not a query per visit; the first answer wins."""
    places: dict[UUID, str] = {}
    if not ids:
        return places
    for provider in _providers.values():
        for key, value in provider(ids).items():
            if value:
                places.setdefault(key, value)
    return places
