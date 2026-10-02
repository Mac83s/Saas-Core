"""Marks a module puts on a visit's card (ADR-067).

A product knows things about its visits that core does not — a herd visit
booked before anybody chose the farm, say. It registers a provider from its own
`AppConfig.ready` through `booking.api.register_appointment_flags`; the panel
shows each flag as a badge, worded by the product's messages
(`Calendar.flags.<flag>`). Without a provider a visit has no flags.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

#: Appointment ids → the flags of those it marks, e.g. ``["farm_missing"]``.
FlagProvider = Callable[[Sequence[UUID]], Mapping[UUID, Sequence[str]]]

_providers: dict[str, FlagProvider] = {}


def register_appointment_flags(name: str, provider: FlagProvider) -> None:
    _providers[name] = provider


def appointment_flags(ids: Sequence[UUID]) -> dict[UUID, list[str]]:
    """One call per provider for the whole list, like the places."""
    flags: dict[UUID, list[str]] = {}
    if not ids:
        return flags
    for provider in _providers.values():
        for key, values in provider(ids).items():
            flags.setdefault(key, []).extend(value for value in values if value)
    return flags
