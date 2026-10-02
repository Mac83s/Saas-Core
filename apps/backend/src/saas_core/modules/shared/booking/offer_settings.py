"""What a company can set on an offer, declared once (ADR-072 §11, ADR-078).

The offer's keys are declarations of the settings registry (`OFFER`, an entity
group: the values are columns of `Service`, written by §11): bounds, variants,
today's defaults and labels. The input serializer takes its bounds from here
and `GET /booking/setup/options/` serves the registry's schema entries.
"""

from __future__ import annotations

from typing import Any

from saas_core.modules.core.organizations.api import SettingGroup, SettingSpec, schema_entry

from .models import RangeUnit, StaffChoice, TimeModel

_BUFFER_HELP = {
    "pl": "Czas na dojazd, przygotowanie albo sprzątanie — blokuje kalendarz, klient go nie widzi.",
    "en": "Time to travel, prepare or tidy up — it blocks the calendar, customers don't see it.",
}

OFFER_SETTINGS: tuple[SettingSpec, ...] = (
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.time_model",
        type="enum",
        default=TimeModel.SLOT.value,
        values=(
            (TimeModel.SLOT.value, {"pl": "Wizyta o godzinie", "en": "A visit at a time"}),
            (TimeModel.RANGE.value, {"pl": "Pobyt lub wynajem od–do", "en": "A stay or rental"}),
        ),
        label={"pl": "Jak się rezerwuje", "en": "How it is booked"},
        help={
            "pl": "Usługa z rezerwacjami nie zmienia sposobu rezerwacji.",
            "en": "A service with bookings keeps how it is booked.",
        },
        model_description=(
            "`slot`: a visit of a set length at a start the calendar offers (people's hours). "
            "`range`: a stay or rental from–to the customer picks, taking a unit (a cottage, "
            "a kayak) by nights or days. Set when the service is created; a service with "
            "bookings never changes it."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.range_unit",
        type="enum",
        default=RangeUnit.NIGHT.value,
        values=(
            (RangeUnit.NIGHT.value, {"pl": "Noce", "en": "Nights"}),
            (RangeUnit.DAY.value, {"pl": "Dni", "en": "Days"}),
        ),
        label={"pl": "Liczymy", "en": "Counted in"},
        model_description=(
            "For a `range` service: nights (check-in to check-out, a stay) or days (pickup on "
            "the first day to return on the last one, a rental)."
        ),
        depends_on="time_model == 'range'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.range_start_local",
        type="text",
        default="16:00",
        label={"pl": "Zameldowanie / odbiór", "en": "Check-in / pickup"},
        help={
            "pl": "Godzina, od której pobyt albo wynajem się zaczyna (dla dni domyślnie 9:00).",
            "en": "The time a stay or rental begins (for days 9:00 by default).",
        },
        model_description="HH:MM local time a `range` booking begins on its first day.",
        depends_on="time_model == 'range'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.range_end_local",
        type="text",
        default="11:00",
        label={"pl": "Wymeldowanie / zwrot", "en": "Check-out / return"},
        help={
            "pl": "Godzina, o której pobyt albo wynajem się kończy (dla dni domyślnie 18:00).",
            "en": "The time a stay or rental ends (for days 18:00 by default).",
        },
        model_description="HH:MM local time a `range` booking ends on its last day.",
        depends_on="time_model == 'range'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.duration_minutes",
        type="int",
        default=30,
        minimum=5,
        maximum=1440,
        unit="minute",
        label={"pl": "Czas trwania", "en": "Duration"},
        model_description="How long one visit of a `slot` service takes, in minutes.",
        depends_on="time_model == 'slot'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.buffer_before_minutes",
        type="int",
        default=0,
        minimum=0,
        maximum=1440,
        unit="minute",
        label={"pl": "Bufor przed", "en": "Buffer before"},
        help=_BUFFER_HELP,
        model_description=(
            "Minutes blocked in the calendar before each visit (travel, preparation); "
            "customers do not see them."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.buffer_after_minutes",
        type="int",
        default=0,
        minimum=0,
        maximum=1440,
        unit="minute",
        label={"pl": "Bufor po", "en": "Buffer after"},
        help=_BUFFER_HELP,
        model_description=(
            "Minutes blocked in the calendar after each visit (tidying up, travel); "
            "customers do not see them."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.minimum_notice_minutes",
        type="int",
        default=60,
        minimum=0,
        maximum=60 * 24 * 90,
        unit="minute",
        label={"pl": "Minimalne wyprzedzenie", "en": "Minimum notice"},
        help={
            "pl": "Ile minut przed wizytą najpóźniej można ją zarezerwować.",
            "en": "How many minutes before a visit it can be booked at the latest.",
        },
        model_description=(
            "How many minutes before its start a visit can still be booked; "
            "0 allows booking up to the start."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.staff_count",
        type="int",
        default=1,
        minimum=0,
        maximum=10,
        label={"pl": "Ile osób potrzeba", "en": "People needed"},
        help={
            "pl": "Tyle osób zablokujemy w kalendarzu przy każdej wizycie.",
            "en": "This many people are blocked in the calendar for every visit.",
        },
        model_description=(
            "How many of the company's people one visit needs; each is blocked. 0 only for "
            "a `range` service whose booking takes a unit and nobody (ADR-072 §2)."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.public_staff_choice",
        type="enum",
        default=StaffChoice.NONE.value,
        values=(
            (
                StaffChoice.NONE.value,
                {"pl": "Nic — osoby dobiera system", "en": "Nothing — the system picks the people"},
            ),
            (StaffChoice.TEAM.value, {"pl": "Zespół", "en": "A team"}),
            (StaffChoice.PERSON.value, {"pl": "Osobę", "en": "A person"}),
        ),
        label={"pl": "Klient może wybrać", "en": "The customer can choose"},
        help={
            "pl": "Konkretną osobę klient może wybrać tylko przy usługach jednoosobowych.",
            "en": "A customer can pick a person only for one-person services.",
        },
        model_description=(
            "What a customer picks on the public booking form: nobody (the system "
            "picks), a team by name, or a person — `person` only when staff_count is 1."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.active",
        type="bool",
        default=True,
        label={"pl": "Przyjmuje rezerwacje", "en": "Takes bookings"},
        model_description=(
            "Whether the service can be booked at all; a switched-off service keeps "
            "its booked visits."
        ),
    ),
)

#: The offer's keys as an entity group of the settings registry (ADR-078 pkt 7):
#: booking keeps the columns, the §11 writes, the preview and the commands.
OFFER = SettingGroup(
    key="booking.offer",
    module="shared.booking",
    title={"pl": "Usługa", "en": "Service"},
    description={
        "pl": "Jak przebiega rezerwacja usługi: model czasu, czas trwania, bufory, ile osób "
        "potrzebuje i co wybiera klient.",
        "en": "How a service is booked: the time model, duration, buffers, how many people "
        "it needs and what the customer chooses.",
    },
    permission="booking.appointment.manage",
    entitlement="booking.enabled",
    area="services",
    api="/api/v1/booking/setup/services/",
    settings=OFFER_SETTINGS,
)

_BY_FIELD = {setting.field: setting for setting in OFFER_SETTINGS}


def offer_setting(field: str) -> SettingSpec:
    return _BY_FIELD[field]


def offer_options() -> list[dict[str, Any]]:
    """The entries as the registry's schema lists them (ADR-078 pkt 11)."""
    return [schema_entry(setting) for setting in OFFER_SETTINGS]
