"""What a company sets for its bookings as a whole (ADR-078; plan R1, B5 and B1).

Two groups on core's settings registry:

- `booking.reminders` — whether the customer gets a reminder e-mail, how many
  hours before the visit (the platform's value until a company chooses: the
  `.env` value `BOOKING_REMINDER_LEAD_HOURS`), and how close to the start a
  booking may be made and still get one. A change re-plans the reminders not
  sent yet; switching them off drops the planned ones.
- `booking.online` — online booking paused: the form on the company's site says
  so and refuses new bookings (409 `booking_paused`), while the team books in
  the panel as before; optionally until a day, when it resumes by itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.api import (
    Effect,
    SettingArea,
    SettingGroup,
    SettingSpec,
    group_commands,
    register_command,
    register_setting_area,
    register_setting_group,
    setting,
    settings_snapshot,
)
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.permissions import SETTINGS_MANAGE

from .models import Appointment, AppointmentStatus

BOOKING_ENABLED = "booking.enabled"


class BookingPaused(APIException):
    status_code = 409
    default_detail = "Rezerwacje online są chwilowo wstrzymane. Skontaktuj się z firmą."
    default_code = "booking_paused"


def _pending_reminders() -> Any:
    """Confirmed visits still ahead whose reminder has not gone out."""
    return Appointment.all_objects.filter(
        organization_id=require_tenant_context().organization_id,
        status=AppointmentStatus.CONFIRMED,
        starts_at__gt=timezone.now(),
        reminder_sent_at__isnull=True,
    )


def _reminder_effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    count = _pending_reminders().count()
    if not count:
        return ()
    if not after["enabled"]:
        summary = {
            "pl": f"Odwoła zaplanowane przypomnienia {count} wizyt.",
            "en": f"Drops the planned reminders of {count} visits.",
        }
    else:
        summary = {
            "pl": f"Przeliczy przypomnienia {count} wizyt, które jeszcze nie wyszły.",
            "en": f"Re-plans the reminders of {count} visits not sent yet.",
        }
    return (
        Effect(kind="rearmed", resource="booking.appointment", resource_id="", summary=summary),
    )


def _rearm(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    from .services import arm_reminder  # noqa: PLC0415 — services read these settings

    with settings_snapshot():
        for appointment in _pending_reminders().select_for_update(of=("self",)):
            arm_reminder(appointment)


def online_paused(zone: str) -> tuple[bool, str | None]:
    """Whether online booking is paused now, and the day it resumes."""
    if not setting("booking.online.paused"):
        return False, None
    resume_on = setting("booking.online.resume_on")
    if resume_on and timezone.localdate(timezone=ZoneInfo(zone)) >= date.fromisoformat(resume_on):
        return False, None
    return True, resume_on


def refuse_when_paused(zone: str) -> None:
    paused, resume_on = online_paused(zone)
    if paused:
        raise BookingPaused(
            detail=(
                f"Rezerwacje online są wstrzymane do {resume_on}. Skontaktuj się z firmą."
                if resume_on
                else BookingPaused.default_detail
            )
        )


REMINDERS = SettingGroup(
    key="booking.reminders",
    module="shared.booking",
    title={"pl": "Przypomnienia o wizycie", "en": "Visit reminders"},
    description={
        "pl": "Czy i kiedy klient dostaje e-mail z przypomnieniem przed potwierdzoną wizytą.",
        "en": "Whether and when the customer gets a reminder e-mail before a confirmed visit.",
    },
    permission=SETTINGS_MANAGE,
    entitlement=BOOKING_ENABLED,
    area="bookings",
    settings=(
        SettingSpec(
            key="booking.reminders.enabled",
            type="bool",
            default=True,
            scopes=("organization",),
            label={"pl": "Wysyłaj przypomnienia", "en": "Send reminders"},
            model_description="Whether customers get a reminder e-mail before a confirmed "
            "visit. Off: no reminder is sent and the planned ones are dropped.",
        ),
        SettingSpec(
            key="booking.reminders.lead_hours",
            type="int",
            minimum=1,
            maximum=168,
            unit="hour",
            default=24,
            platform_env="BOOKING_REMINDER_LEAD_HOURS",
            depends_on="enabled",
            label={"pl": "Ile godzin przed wizytą", "en": "Hours before the visit"},
            help={
                "pl": "Zmiana przelicza przypomnienia, które jeszcze nie wyszły.",
                "en": "A change re-plans the reminders not sent yet.",
            },
            model_description="How many hours before the visit the reminder goes out, 1 to "
            "168. A change re-plans the reminders not sent yet; a visit closer than that "
            "gets its reminder at once.",
        ),
        SettingSpec(
            key="booking.reminders.min_notice_hours",
            type="int",
            minimum=0,
            maximum=168,
            unit="hour",
            default=0,
            scopes=("organization",),
            depends_on="enabled",
            label={
                "pl": "Bez przypomnienia, gdy do wizyty zostało mniej niż (godz.)",
                "en": "No reminder when the visit is less than (hours) away",
            },
            help={
                "pl": "0 — przypomnienie wychodzi zawsze, także od razu po rezerwacji na dziś.",
                "en": "0 — a reminder always goes out, even at once for a booking for today.",
            },
            model_description="A visit less than this many hours away when its reminder is "
            "planned gets none (a booking for this afternoon needs no reminder). 0 keeps "
            "today's behaviour: the reminder goes out at once.",
        ),
    ),
    effects=_reminder_effects,
    on_changed=_rearm,
    commands=("booking.settings_reminders.read@1", "booking.settings_reminders.update@1"),
)

ONLINE = SettingGroup(
    key="booking.online",
    module="shared.booking",
    title={"pl": "Rezerwacja online", "en": "Online booking"},
    description={
        "pl": "Czy klienci rezerwują przez formularz na stronie firmy. Wstrzymanie nie "
        "dotyczy wizyt dodawanych w panelu ani zmian istniejących rezerwacji.",
        "en": "Whether customers book through the form on the company's site. A pause does "
        "not affect visits added in the panel or changes to existing bookings.",
    },
    permission=SETTINGS_MANAGE,
    entitlement=BOOKING_ENABLED,
    area="bookings",
    settings=(
        SettingSpec(
            key="booking.online.paused",
            type="bool",
            default=False,
            scopes=("organization",),
            label={"pl": "Wstrzymaj rezerwacje online", "en": "Pause online booking"},
            model_description="Paused: the booking form on the company's site says online "
            "booking is paused and refuses new bookings; the team still adds visits in the "
            "panel and customers can still change or cancel theirs.",
        ),
        SettingSpec(
            key="booking.online.resume_on",
            type="date",
            default=None,
            scopes=("organization",),
            depends_on="paused",
            label={"pl": "Wznów od dnia", "en": "Resume on"},
            help={
                "pl": "Puste — wstrzymane, dopóki ktoś nie wyłączy pauzy.",
                "en": "Empty — paused until someone switches the pause off.",
            },
            model_description="The day online booking resumes by itself, in the company's "
            "time zone (YYYY-MM-DD). Empty: paused until switched off.",
        ),
    ),
    commands=("booking.settings_online.read@1", "booking.settings_online.update@1"),
)


SERVICES_AREA = SettingArea(
    key="services",
    title={"pl": "Usługi i grafik", "en": "Services & schedule"},
    description={
        "pl": "Usługi, ich czas i ceny, grafik osób, miejsca, sezony i dni zamknięte.",
        "en": "Services with their length and prices, people's hours, places, seasons and "
        "closed days.",
    },
    order=40,
    page="/panel/settings/services",
)
BOOKINGS_AREA = SettingArea(
    key="bookings",
    title={"pl": "Rezerwacje", "en": "Bookings"},
    description={
        "pl": "Przypomnienia o wizytach i rezerwacja online na stronie firmy.",
        "en": "Visit reminders and online booking on the company's site.",
    },
    order=50,
    page="/panel/settings/bookings",
)


def register_company_settings() -> None:
    from .offer_settings import OFFER  # noqa: PLC0415

    register_setting_area(SERVICES_AREA)
    register_setting_area(BOOKINGS_AREA)
    for group in (REMINDERS, ONLINE):
        register_setting_group(group)
        for command in group_commands(group):
            register_command(command)
    # The offer's keys: an entity group, its writes are §11's (ADR-078 pkt 17).
    register_setting_group(OFFER)


def reminder_due(starts_at: Any) -> Any:
    """When the reminder of a visit starting at `starts_at` goes out, or None
    when it does not (switched off, or booked too close to the start)."""
    if not setting("booking.reminders.enabled"):
        return None
    now = timezone.now()
    if starts_at - now < timedelta(hours=setting("booking.reminders.min_notice_hours")):
        return None
    return max(now, starts_at - timedelta(hours=setting("booking.reminders.lead_hours")))
