"""What a visit is called on the calendar, when a module knows better than the
customer's name (UX plan W2, 03.10).

A herd visit is the farm's: the office and the trimmer know it as „Gospodarstwo
Mazur”, while the booking's customer is the person who answers the phone. A
module registers from its own `AppConfig.ready` through
`booking.api.register_appointment_title`; the panel shows the title first and
the customer's name after it. Without a provider the customer's name is the
visit's name, as before.

A provider answers without its module's permission with nothing; one that
fails anyway is logged and skipped inside a savepoint, like the places.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from django.db import transaction

#: Appointment ids → the visit's name for those the module knows.
TitleProvider = Callable[[Sequence[UUID]], Mapping[UUID, str]]

_providers: dict[str, TitleProvider] = {}

logger = logging.getLogger(__name__)


def register_appointment_title(name: str, provider: TitleProvider) -> None:
    _providers[name] = provider


def appointment_titles(ids: Sequence[UUID]) -> dict[UUID, str]:
    """One call per provider for the whole list; the first answer wins."""
    titles: dict[UUID, str] = {}
    if not ids:
        return titles
    for name, provider in _providers.items():
        try:
            with transaction.atomic():
                answer = provider(ids)
        except Exception:
            logger.exception("Dostawca nazwy wizyty zawiódł.", extra={"provider": name})
            continue
        for key, value in answer.items():
            if value:
                titles.setdefault(key, value)
    return titles
