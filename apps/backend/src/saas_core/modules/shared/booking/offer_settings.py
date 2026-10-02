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

from .models import StaffChoice


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
        key="booking.offer.duration_minutes",
        type="int",
        default=30,
        minimum=5,
        maximum=1440,
        unit="minute",
        label={"pl": "Czas trwania", "en": "Duration"},
        description="How long one visit of this service takes, in minutes.",
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
        minimum=1,
        maximum=10,
        label={"pl": "Ile osób potrzeba", "en": "People needed"},
        help={
            "pl": "Tyle osób zablokujemy w kalendarzu przy każdej wizycie.",
            "en": "This many people are blocked in the calendar for every visit.",
        },
        description="How many of the company's people one visit needs; each is blocked.",
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
