"""What a company can set on an offer, declared once (ADR-072 §11, ADR-078).

Until the settings registry exists (plan `saas-core-ustawienia-firmy`, R1) the
offer's keys live in this one constant: bounds, variants, today's defaults and
labels. The input serializer takes its bounds from here and
`GET /booking/setup/options/` serves the entries in the shape of the
registry's schema, so R1 moves them into declarations without changing the
API or the assistant's commands.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import RangeUnit, StaffChoice, TimeModel


@dataclass(frozen=True, slots=True)
class OfferSetting:
    key: str
    #: `int`, `bool` or `enum`, as the registry names them.
    type: str
    #: What a new offer gets when the caller says nothing — today's form.
    default: Any
    label: Mapping[str, str]
    #: English, for the model: what the value does and when to change it.
    description: str
    help: Mapping[str, str] | None = None
    minimum: int | None = None
    maximum: int | None = None
    unit: str | None = None
    values: tuple[tuple[str, Mapping[str, str]], ...] | None = None
    scopes: tuple[str, ...] = ("offer",)
    depends_on: str | None = None

    @property
    def field(self) -> str:
        """The offer's column: `booking.offer.staff_count` → `staff_count`."""
        return self.key.rsplit(".", 1)[1]


_BUFFER_HELP = {
    "pl": "Czas na dojazd, przygotowanie albo sprzątanie — blokuje kalendarz, klient go nie widzi.",
    "en": "Time to travel, prepare or tidy up — it blocks the calendar, customers don't see it.",
}

OFFER_SETTINGS: tuple[OfferSetting, ...] = (
    OfferSetting(
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
        description=(
            "`slot`: a visit of a set length at a start the calendar offers (people's hours). "
            "`range`: a stay or rental from–to the customer picks, taking a unit (a cottage, "
            "a kayak) by nights or days. Set when the service is created; a service with "
            "bookings never changes it."
        ),
    ),
    OfferSetting(
        key="booking.offer.range_unit",
        type="enum",
        default=RangeUnit.NIGHT.value,
        values=(
            (RangeUnit.NIGHT.value, {"pl": "Noce", "en": "Nights"}),
            (RangeUnit.DAY.value, {"pl": "Dni", "en": "Days"}),
        ),
        label={"pl": "Liczymy", "en": "Counted in"},
        description=(
            "For a `range` service: nights (check-in to check-out, a stay) or days (pickup on "
            "the first day to return on the last one, a rental)."
        ),
        depends_on="booking.offer.time_model == 'range'",
    ),
    OfferSetting(
        key="booking.offer.range_start_local",
        type="text",
        default="16:00",
        label={"pl": "Zameldowanie / odbiór", "en": "Check-in / pickup"},
        help={
            "pl": "Godzina, od której pobyt albo wynajem się zaczyna (dla dni domyślnie 9:00).",
            "en": "The time a stay or rental begins (for days 9:00 by default).",
        },
        description="HH:MM local time a `range` booking begins on its first day.",
        depends_on="booking.offer.time_model == 'range'",
    ),
    OfferSetting(
        key="booking.offer.range_end_local",
        type="text",
        default="11:00",
        label={"pl": "Wymeldowanie / zwrot", "en": "Check-out / return"},
        help={
            "pl": "Godzina, o której pobyt albo wynajem się kończy (dla dni domyślnie 18:00).",
            "en": "The time a stay or rental ends (for days 18:00 by default).",
        },
        description="HH:MM local time a `range` booking ends on its last day.",
        depends_on="booking.offer.time_model == 'range'",
    ),
    OfferSetting(
        key="booking.offer.duration_minutes",
        type="int",
        default=30,
        minimum=5,
        maximum=1440,
        unit="minute",
        label={"pl": "Czas trwania", "en": "Duration"},
        description="How long one visit of a `slot` service takes, in minutes.",
        depends_on="booking.offer.time_model == 'slot'",
    ),
    OfferSetting(
        key="booking.offer.buffer_before_minutes",
        type="int",
        default=0,
        minimum=0,
        maximum=1440,
        unit="minute",
        label={"pl": "Bufor przed", "en": "Buffer before"},
        help=_BUFFER_HELP,
        description=(
            "Minutes blocked in the calendar before each visit (travel, preparation); "
            "customers do not see them."
        ),
    ),
    OfferSetting(
        key="booking.offer.buffer_after_minutes",
        type="int",
        default=0,
        minimum=0,
        maximum=1440,
        unit="minute",
        label={"pl": "Bufor po", "en": "Buffer after"},
        help=_BUFFER_HELP,
        description=(
            "Minutes blocked in the calendar after each visit (tidying up, travel); "
            "customers do not see them."
        ),
    ),
    OfferSetting(
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
        description=(
            "How many minutes before its start a visit can still be booked; "
            "0 allows booking up to the start."
        ),
    ),
    OfferSetting(
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
        description=(
            "How many of the company's people one visit needs; each is blocked. 0 only for "
            "a `range` service whose booking takes a unit and nobody (ADR-072 §2)."
        ),
    ),
    OfferSetting(
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
        description=(
            "What a customer picks on the public booking form: nobody (the system "
            "picks), a team by name, or a person — `person` only when staff_count is 1."
        ),
    ),
    OfferSetting(
        key="booking.offer.active",
        type="bool",
        default=True,
        label={"pl": "Przyjmuje rezerwacje", "en": "Takes bookings"},
        description=(
            "Whether the service can be booked at all; a switched-off service keeps "
            "its booked visits."
        ),
    ),
)

_BY_FIELD = {setting.field: setting for setting in OFFER_SETTINGS}


def offer_setting(field: str) -> OfferSetting:
    return _BY_FIELD[field]


def offer_options() -> list[dict[str, Any]]:
    """The entries as the registry's schema will list them (ADR-078 pkt 11)."""
    return [
        {
            "key": setting.key,
            "type": setting.type,
            "minimum": setting.minimum,
            "maximum": setting.maximum,
            "unit": setting.unit,
            "values": (
                [{"value": value, "label": dict(label)} for value, label in setting.values]
                if setting.values
                else None
            ),
            "default": setting.default,
            "label": dict(setting.label),
            "help": dict(setting.help) if setting.help else None,
            "description": setting.description,
            "scopes": list(setting.scopes),
            "depends_on": setting.depends_on,
        }
        for setting in OFFER_SETTINGS
    ]
