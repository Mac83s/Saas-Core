"""Modules watch appointment changes; Booking never imports a consumer.

The same shape as `core.organizations.erasure_checks`: the registry is empty
until something registers itself from its own `AppConfig.ready`, so a
deployment without that module has nothing to call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

logger = logging.getLogger(__name__)

CREATED = "created"
RESCHEDULED = "rescheduled"
CANCELED = "canceled"
COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AppointmentChange:
    """What an appointment looked like before the change and after it.

    `previous_starts_at` is None only for `created`, where there is no before.
    A change that does not move the visit repeats its time on both sides, so an
    observer can compare the two fields without knowing which change it is.
    """

    change: str
    organization_id: UUID
    appointment_id: UUID
    previous_starts_at: datetime | None
    starts_at: datetime
    previous_status: str
    status: str
    timezone: str


_observers: dict[str, Callable[[AppointmentChange], None]] = {}


def register_appointment_observer(
    name: str, observer: Callable[[AppointmentChange], None]
) -> None:
    _observers[name] = observer


def notify_appointment_change(change: AppointmentChange) -> None:
    """Runs every observer and swallows what they raise.

    An observer writes into a *different* tenant through this door. Its failure
    is not the customer's problem: the booking is already committed and the
    calendar is the source of truth, so a broken bookkeeper must never surface
    as a 500 on a reschedule the customer just made. Swallowing is also the only
    option left at this point — the caller runs this from `on_commit`, after the
    transaction that changed the appointment is gone.
    """
    for name, observer in _observers.items():
        try:
            observer(change)
        except Exception:
            logger.exception(
                "Obserwator rezerwacji zawiódł.",
                extra={"observer": name, "change": change.change},
            )
