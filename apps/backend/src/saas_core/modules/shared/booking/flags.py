"""Marks a module puts on a visit's card (ADR-067).

A product knows things about its visits that core does not — a herd visit
booked before anybody chose the farm, say. It registers a provider from its own
`AppConfig.ready` through `booking.api.register_appointment_flags`; the panel
shows each flag as a badge, worded by the product's messages
(`Calendar.flags.<flag>`). Without a provider a visit has no flags. A provider answers without its
module's permission with nothing; one that fails anyway is logged and skipped
inside a savepoint, so a change already made stands.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from django.db import transaction

#: The visits as id → `appointment_kind` → the flags of those it marks, e.g.
#: ``["farm_missing"]``. The kind comes with the id, so a product picks its own
#: visits without reading booking's tables.
FlagProvider = Callable[[Mapping[UUID, str]], Mapping[UUID, Sequence[str]]]

_providers: dict[str, FlagProvider] = {}

logger = logging.getLogger(__name__)


def register_appointment_flags(name: str, provider: FlagProvider) -> None:
    _providers[name] = provider


def appointment_flags(kinds: Mapping[UUID, str]) -> dict[UUID, list[str]]:
    """One call per provider for the whole list, like the places."""
    flags: dict[UUID, list[str]] = {}
    if not kinds:
        return flags
    for name, provider in _providers.items():
        try:
            with transaction.atomic():
                answer = provider(kinds)
        except Exception:
            logger.exception("Dostawca znaczników wizyty zawiódł.", extra={"provider": name})
            continue
        for key, values in answer.items():
            flags.setdefault(key, []).extend(value for value in values if value)
    return flags
