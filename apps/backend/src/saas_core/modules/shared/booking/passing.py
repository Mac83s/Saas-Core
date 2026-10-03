"""When a visit has passed, and whether that means it took place (UX-031).

One rule for the API, the panel and the statistics: a confirmed visit whose
planned end is behind us has passed. Nobody closed it — neither „Zakończ” nor
a no-show — so the panel shows it apart from the visits still ahead, and a
vacancy on it is no longer work for anybody. Nothing is stored: the clock
decides, so there is no sweep to fall behind.

Whether a passed visit took place is a second question. By default it did
(decision 3A: most companies never press „Zakończ”). A module that closes the
visits of its kinds itself — HoofCare, when the field work ends — declares them
in `appointmentKindsCompletedExplicitly`; for those only a completed visit took
place, and a passed one is merely not finished.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import AppointmentStatus


def closes_explicitly(kind: str) -> bool:
    """Whether visits of this kind took place only once completed. "" is the
    plain service, which a product may list too."""
    return kind in getattr(settings, "APPOINTMENT_KINDS_COMPLETED_EXPLICITLY", ())


def has_passed(appointment: Any, now: datetime | None = None) -> bool:
    return appointment.status == AppointmentStatus.CONFIRMED and appointment.ends_at <= (
        now or timezone.now()
    )


def took_place_q(now: datetime, prefix: str = "") -> Q:
    """The visits that took place by `now`: completed, or passed and of a kind
    whose passing counts (3A). `prefix` reaches the appointment from another
    model, e.g. ``"appointment__"``."""
    explicit = tuple(getattr(settings, "APPOINTMENT_KINDS_COMPLETED_EXPLICITLY", ()))
    passed = Q(**{f"{prefix}status": AppointmentStatus.CONFIRMED, f"{prefix}ends_at__lte": now})
    if explicit:
        passed &= ~Q(**{f"{prefix}service__appointment_kind__in": explicit})
    return passed | Q(**{f"{prefix}status": AppointmentStatus.COMPLETED})
