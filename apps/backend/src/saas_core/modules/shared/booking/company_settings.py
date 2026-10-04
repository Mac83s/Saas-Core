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
  Also what the form asks of a customer: which contact, and whether it shows
  the marketing consent (`booking.online.marketing_consent`, on by default).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

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


SELF_SERVICE_MODE = "booking.self_service.mode"
SELF_SERVICE_CUTOFF = "booking.self_service.cutoff_hours"
HORIZON_DAYS = "booking.online.horizon_days"
CONTACT = "booking.online.contact"
MARKETING_CONSENT = "booking.online.marketing_consent"
OFFICE_NOTICES = "booking.notices.office"


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
        SettingSpec(
            key=HORIZON_DAYS,
            type="int",
            minimum=1,
            # One search window of the public form (BOOKING_SLOT_HORIZON_DAYS).
            maximum=62,
            unit="day",
            default=15,
            scopes=("organization",),
            label={"pl": "Na ile dni naprzód", "en": "How many days ahead"},
            help={
                "pl": "Licząc z dzisiejszym: 15 to dziś i dwa kolejne tygodnie. Zespół w panelu "
                "zapisuje na dowolny termin.",
                "en": "Counting today: 15 is today and the next two weeks. The team books any "
                "date in the panel.",
            },
            model_description="How many days of the calendar, today included, the booking "
            "form on the company's site offers (1 to 62); a start beyond them is refused "
            "online. The panel is not limited.",
        ),
        SettingSpec(
            key=CONTACT,
            type="enum",
            default="email",
            scopes=("organization",),
            values=(
                ("email", {"pl": "E-mail", "en": "E-mail"}),
                ("phone", {"pl": "Telefon", "en": "Phone"}),
                ("email_or_phone", {"pl": "E-mail albo telefon", "en": "E-mail or phone"}),
                ("email_and_phone", {"pl": "E-mail i telefon", "en": "E-mail and phone"}),
            ),
            label={
                "pl": "Kontakt wymagany od klienta",
                "en": "Contact required from the customer",
            },
            help={
                "pl": "Bez e-maila klient nie dostanie potwierdzenia ani linku do zmiany "
                "terminu — firma zadzwoni.",
                "en": "Without an e-mail the customer gets no confirmation and no link to "
                "change the time — the company phones.",
            },
            model_description="What the booking form on the company's site requires: an "
            "e-mail, a phone, either, or both. Without an e-mail the customer gets no "
            "confirmation or self-service link.",
        ),
        SettingSpec(
            key=MARKETING_CONSENT,
            type="bool",
            default=True,
            scopes=("organization",),
            label={
                "pl": "Pytaj o zgodę na oferty i promocje",
                "en": "Ask for consent to offers and promotions",
            },
            help={
                "pl": "Formularz pokazuje nieobowiązkowe pole „Chcę otrzymywać oferty i "
                "promocje od (nazwa firmy) e-mailem.”, domyślnie odznaczone. Każda zgoda "
                "trafia do dziennika zgód.",
                "en": "The form shows an optional box “I want to receive offers and "
                "promotions from (company name) by e-mail.”, unticked by default. Every "
                "consent goes to the consent journal.",
            },
            model_description="On: the booking form on the company's site shows one optional "
            "box, unticked by default, asking the customer whether they want the company's "
            "offers and promotions by e-mail; a ticked box is a line of the consent journal. "
            "Off: the form does not ask.",
        ),
    ),
    commands=("booking.settings_online.read@1", "booking.settings_online.update@1"),
)

SELF_SERVICE = SettingGroup(
    key="booking.self_service",
    module="shared.booking",
    title={"pl": "Zmiana i odwołanie przez klienta", "en": "Changes by the customer"},
    description={
        "pl": "Co klient może zrobić linkiem z potwierdzenia rezerwacji. Obowiązuje dla "
        "rezerwacji zrobionych po zmianie — wcześniejsze zostają na swoich zasadach.",
        "en": "What the customer may do with the link in the booking confirmation. It "
        "holds for bookings made after a change — earlier ones keep their terms.",
    },
    permission=SETTINGS_MANAGE,
    entitlement=BOOKING_ENABLED,
    area="bookings",
    settings=(
        SettingSpec(
            key=SELF_SERVICE_MODE,
            type="enum",
            default="change_and_cancel",
            scopes=("organization",),
            values=(
                (
                    "change_and_cancel",
                    {"pl": "Zmiana terminu i odwołanie", "en": "Change the time and cancel"},
                ),
                ("cancel_only", {"pl": "Tylko odwołanie", "en": "Cancel only"}),
                ("none", {"pl": "Nic — kontakt z firmą", "en": "Nothing — contact the company"}),
            ),
            label={"pl": "Klient linkiem może", "en": "With the link the customer may"},
            model_description="What the customer's self-service link allows: change the "
            "time and cancel, cancel only, or nothing (the customer contacts the company). "
            "Frozen into each booking when it is made.",
        ),
        SettingSpec(
            key=SELF_SERVICE_CUTOFF,
            type="int",
            minimum=0,
            maximum=168,
            unit="hour",
            default=0,
            scopes=("organization",),
            label={
                "pl": "Najpóźniej (godzin przed wizytą)",
                "en": "At the latest (hours before the visit)",
            },
            help={
                "pl": "0 — aż do rozpoczęcia wizyty. Później klient dzwoni do firmy.",
                "en": "0 — until the visit starts. After that the customer phones the company.",
            },
            model_description="How many hours before the start the link stops allowing "
            "changes (0 to 168; 0: until the start). Frozen into each booking.",
        ),
    ),
    commands=(
        "booking.settings_self_service.read@1",
        "booking.settings_self_service.update@1",
    ),
)

NOTICES = SettingGroup(
    key="booking.notices",
    module="shared.booking",
    title={"pl": "Powiadomienia zespołu", "en": "Team notices"},
    description={
        "pl": "Kto w firmie dowiaduje się o nowej rezerwacji online, wizycie czekającej na "
        "przydział i odwołaniu przez klienta. Przypisane osoby wiedzą zawsze.",
        "en": "Who in the company hears about a new online booking, a visit waiting for "
        "someone and a customer's cancellation. The people on the visit always do.",
    },
    permission=SETTINGS_MANAGE,
    entitlement=BOOKING_ENABLED,
    area="bookings",
    settings=(
        SettingSpec(
            key=OFFICE_NOTICES,
            type="bool",
            default=False,
            scopes=("organization",),
            label={
                "pl": "Powiadamiaj też osoby zarządzające rezerwacjami",
                "en": "Also tell the people who manage bookings",
            },
            help={
                "pl": "Np. recepcję albo biuro: każdy z prawem zarządzania wizytami dostaje "
                "e-mail i powiadomienie w panelu.",
                "en": "E.g. the front desk or the office: everyone allowed to manage visits "
                "gets an e-mail and a notice in the panel.",
            },
            model_description="On: everyone who may manage visits (booking.appointment."
            "manage) also hears about a new online booking, a visit waiting for someone to "
            "be assigned and a customer's cancellation by link. Off: only the people on the "
            "visit, as before.",
        ),
    ),
    commands=("booking.settings_notices.read@1", "booking.settings_notices.update@1"),
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


def _price_effects(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[Effect, ...]:
    from .models import Extra, ExtraKind, PriceRule  # noqa: PLC0415 — nothing imports back

    organization_id = require_tenant_context().organization_id
    # An extra's amount is read the same way; a deposit carries no tax.
    count = (
        PriceRule.all_objects.filter(organization_id=organization_id).count()
        + Extra.all_objects.filter(organization_id=organization_id, kind=ExtraKind.CHARGE).count()
    )
    if not count:
        return ()
    gross = after["amounts"] == "gross"
    return (
        Effect(
            kind="updated",
            resource="booking.price",
            resource_id="",
            summary={
                "pl": f"Zmieni znaczenie {count} cen i dopłat w cenniku: kwoty zostają, a "
                + (
                    "podatek będzie wyliczany z kwoty."
                    if gross
                    else "podatek będzie do nich doliczany."
                ),
                "en": f"Changes what {count} prices and extras in the price list mean: the amounts "
                "stay, and the tax is "
                + ("worked out from the amount." if gross else "added on top of them."),
            },
        ),
    )


#: Whoever holds prices reads this: booking now, `shared.customers` from the
#: phase that makes it (ADR-073) — the keys and the companies' values stay.
PRICING = SettingGroup(
    key="pricing.entry",
    module="shared.booking",
    title={"pl": "Ceny i podatek", "en": "Prices and tax"},
    description={
        "pl": "Jak czytamy kwoty w cenniku usług, pobytów i dopłat. Klient zawsze widzi "
        "cenę brutto.",
        "en": "How the amounts in the price list of services, stays and extras are read. "
        "A customer always sees the gross price.",
    },
    permission=SETTINGS_MANAGE,
    entitlement=BOOKING_ENABLED,
    # One switch changes every price a customer sees.
    risk="publish",
    area="bookings",
    settings=(
        SettingSpec(
            key="pricing.entry.amounts",
            type="enum",
            default="gross",
            scopes=("organization",),
            values=(
                ("gross", {"pl": "brutto (z VAT)", "en": "gross (with VAT)"}),
                ("net", {"pl": "netto (bez VAT)", "en": "net (without VAT)"}),
            ),
            label={"pl": "Ceny w cenniku wpisujesz", "en": "You enter prices in the price list"},
            help={
                "pl": "Klient zawsze widzi cenę brutto. Zmiana nie przelicza wpisanych kwot — "
                "zmienia tylko to, czy podatek jest w nich, czy doliczamy go do nich. Ceny "
                "produktów w magazynie są zawsze netto.",
                "en": "A customer always sees the gross price. A change does not recalculate "
                "the amounts entered — only whether the tax is in them or added to them. "
                "Product prices in the warehouse are always net.",
            },
            model_description="Whether the amounts in the company's price list of services, "
            "stays and extras include VAT (gross) or not (net). What a customer sees is "
            "always gross, whatever this says. Changing it recalculates nothing: every "
            "amount stays as entered and is read the other way, so every price a customer "
            "sees changes. It does not cover product sale prices in the warehouse, which "
            "are always net.",
        ),
    ),
    effects=_price_effects,
    commands=("pricing.settings_entry.read@1", "pricing.settings_entry.update@1"),
)


def register_company_settings() -> None:
    from .offer_settings import OFFER  # noqa: PLC0415

    register_setting_area(SERVICES_AREA)
    register_setting_area(BOOKINGS_AREA)
    for group in (REMINDERS, ONLINE, SELF_SERVICE, NOTICES, PRICING):
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


class BeyondHorizon(APIException):
    status_code = 409
    default_detail = "Tak odległego terminu nie można zarezerwować online. Skontaktuj się z firmą."
    default_code = "beyond_booking_horizon"


def online_last_day(zone: str) -> date:
    """The last day the company's online form offers (B3): today counts."""
    today = timezone.localdate(timezone=ZoneInfo(zone))
    return today + timedelta(days=int(setting(HORIZON_DAYS)) - 1)


def refuse_beyond_horizon(starts_at: Any, zone: str) -> None:
    if timezone.localtime(starts_at, ZoneInfo(zone)).date() > online_last_day(zone):
        raise BeyondHorizon


def refuse_missing_contact(customer: Mapping[str, Any]) -> None:
    """What the company requires of an online customer (B9); the panel books
    whoever the team knows."""
    rule = setting(CONTACT)
    email = bool((customer.get("email") or "").strip())
    phone = bool((customer.get("phone") or "").strip())
    missing: dict[str, list[str]] = {}
    if rule in {"email", "email_and_phone"} and not email:
        missing["email"] = ["Podaj e-mail."]
    if rule in {"phone", "email_and_phone"} and not phone:
        missing["phone"] = ["Podaj telefon."]
    if rule == "email_or_phone" and not (email or phone):
        missing["email"] = ["Podaj e-mail albo telefon."]
    if missing:
        raise ValidationError({"customer": missing})


def self_service_terms() -> dict[str, Any]:
    """The company's self-service terms now, for a booking being made (B4)."""
    return {
        "self_service_mode": setting(SELF_SERVICE_MODE),
        "self_service_cutoff_hours": setting(SELF_SERVICE_CUTOFF),
    }


def self_service_allows(appointment: Any, action: str, now: Any) -> bool:
    """Whether the booking's own terms let its link `cancel` or `reschedule`
    now: never once it started, never past its cutoff."""
    mode = appointment.self_service_mode
    if mode == "none" or (action == "reschedule" and mode == "cancel_only"):
        return False
    return bool(
        appointment.starts_at - timedelta(hours=appointment.self_service_cutoff_hours) > now
    )
