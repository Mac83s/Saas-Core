"""What a company can set on an offer, declared once (ADR-072 §11, ADR-078).

The offer's keys are declarations of the settings registry (`OFFER`, an entity
group: the values are columns of `Service`, written by §11): bounds, variants,
today's defaults and labels. The input serializer takes its bounds from here
and `GET /booking/setup/options/` serves the registry's schema entries.
"""

from __future__ import annotations

from typing import Any

from saas_core.modules.core.organizations.api import SettingGroup, SettingSpec, schema_entry

from .models import Confirmation, PaymentPolicy, RangeUnit, RefundBasis, StaffChoice, TimeModel

#: The starts a service may be offered at, in minutes (B6, ADR-058 §5): every
#: one divides an hour, so a grid never drifts across a person's day.
SLOT_STEPS = (5, 10, 15, 20, 30, 60)

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
        key="booking.offer.booking_window_days",
        type="int",
        default=None,
        minimum=1,
        # The widest window a period calendar spans (BOOKING_PERIOD_HORIZON_DAYS).
        maximum=731,
        unit="day",
        depends_on="time_model == 'range'",
        label={"pl": "Okno rezerwacji", "en": "Booking window"},
        help={
            "pl": "Na ile dni naprzód można zarezerwować. Puste — bez własnego limitu. "
            "Sezon z własnym oknem ma pierwszeństwo.",
            "en": "How many days ahead it can be booked. Empty — no limit of its own. "
            "A season with its own window comes first.",
        },
        model_description=(
            "For a `range` service: how many days ahead of its first day a stay or a rental "
            "can be booked at most; a later one is refused (`rule_window`). Null: only the "
            "platform's bound applies. A season's own window (`window_days` of a booking "
            "rule) is used instead where it is set."
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
        key="booking.offer.slot_step_minutes",
        type="int",
        minimum=5,
        maximum=60,
        unit="minute",
        default=5,
        label={"pl": "Wizyty zaczynają się co", "en": "Visits start every"},
        help={
            "pl": "5, 10, 15, 20, 30 albo 60 minut, licząc od początku godzin pracy osoby.",
            "en": "5, 10, 15, 20, 30 or 60 minutes, counted from the start of a person's hours.",
        },
        model_description=(
            "How often a visit of this service may start, counted from the start of a "
            "person's working hours: 5, 10, 15, 20, 30 or 60 minutes. Free times and a "
            "booked start follow the same grid."
        ),
        depends_on="time_model == 'slot'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.online",
        type="bool",
        default=True,
        label={"pl": "W rezerwacji online", "en": "In online booking"},
        help={
            "pl": "Wyłączona: nie ma jej w formularzu na stronie, zespół zapisuje na nią w panelu.",
            "en": "Off: it is not on the site's form; the team books it in the panel.",
        },
        model_description=(
            "Whether the service is on the booking form on the company's site. Off: only "
            "the team books it, in the panel; its booked visits stay."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.confirmation",
        type="enum",
        default=Confirmation.INSTANT.value,
        values=(
            (Confirmation.INSTANT.value, {"pl": "Od razu", "en": "At once"}),
            (
                Confirmation.ON_REQUEST.value,
                {"pl": "Na prośbę — firma odpowiada", "en": "On request — the company answers"},
            ),
        ),
        label={"pl": "Potwierdzenie rezerwacji", "en": "Confirming a booking"},
        help={
            "pl": "Na prośbę: rezerwacja klienta trzyma termin i czeka, aż ją przyjmiesz albo "
            "odmówisz. Bez odpowiedzi w terminie wygasa. Rezerwacje wpisane przez zespół "
            "są potwierdzone od razu.",
            "en": "On request: a customer's booking holds its time and waits for you to "
            "accept or decline it. Unanswered in time, it expires. Bookings the team "
            "enters are confirmed at once.",
        },
        model_description=(
            "Who confirms a booking a customer makes on the company's site: `instant` — it "
            "is confirmed when booked; `on_request` — it holds its time as "
            "`pending_request` until the company accepts or declines it, and expires after "
            "`response_hours` without an answer. A booking the team enters in the panel "
            "never waits for an answer."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.response_hours",
        type="int",
        default=24,
        minimum=1,
        maximum=168,
        unit="hour",
        label={"pl": "Czas na odpowiedź", "en": "Time to answer"},
        help={
            "pl": "Ile godzin firma ma na odpowiedź, zanim prośba wygaśnie. Nigdy dłużej niż "
            "do początku rezerwacji.",
            "en": "How many hours the company has to answer before the request expires. "
            "Never past the booking's start.",
        },
        model_description=(
            "With `confirmation` `on_request`: how many hours the company has to accept or "
            "decline a customer's request before it expires (1–168), never past the "
            "booking's start."
        ),
        depends_on="confirmation == 'on_request'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.payment_policy",
        type="enum",
        default=PaymentPolicy.NONE.value,
        values=(
            (PaymentPolicy.NONE.value, {"pl": "Nie mówimy o płatności", "en": "Nothing said"}),
            (PaymentPolicy.ON_SITE.value, {"pl": "Płatność na miejscu", "en": "Pay on site"}),
            (
                PaymentPolicy.TRANSFER.value,
                {"pl": "Całość przelewem przed wizytą", "en": "The whole by transfer ahead"},
            ),
            (
                PaymentPolicy.DEPOSIT.value,
                {"pl": "Przedpłata, reszta na miejscu", "en": "A prepayment, the rest on site"},
            ),
            (PaymentPolicy.FULL.value, {"pl": "Całość z góry", "en": "The whole ahead"}),
        ),
        label={"pl": "Płatność", "en": "Payment"},
        help={
            "pl": "Klient widzi to przy cenie. Przy płatności z góry rezerwacja czeka na "
            "wpłatę i wygasa, gdy wpłata nie dotrze w terminie. Wpłatę z góry klient robi "
            "przelewem na rachunek firmy (Ustawienia › Płatności klientów); bez rachunku "
            "płaci na miejscu.",
            "en": "The customer sees it next to the price. With a payment ahead the booking "
            "waits for the money and expires when it does not arrive in time. A payment "
            "ahead is a transfer to the company's account (Settings › Customers' "
            "payments); without an account the customer pays on site.",
        },
        model_description=(
            "How the customer pays for the service, shown next to its price and frozen in "
            "each booking: `none` says nothing, `on_site` says the customer pays at the "
            "visit. `transfer` (the whole by a bank transfer), `deposit` (a part ahead, "
            "`deposit_percent`, the rest on site) and `full` (the whole ahead) ask for money "
            "before the booking is confirmed: the booking waits (`pending_payment`) and "
            "expires after `transfer_due_days` without it. They need orders in the "
            "company's plan (`orders_required`); `transfer` also needs the company's bank "
            "account (`transfer_account_missing`). `deposit` and `full` without an account "
            "are paid on site and confirmed at once."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.deposit_percent",
        type="int",
        default=30,
        minimum=1,
        maximum=99,
        unit="percent",
        label={"pl": "Przedpłata", "en": "Prepayment"},
        help={
            "pl": "Jaka część ceny jest przedpłatą. Resztę klient płaci na miejscu.",
            "en": "The part of the price paid ahead. The customer pays the rest on site.",
        },
        model_description=(
            "With `payment_policy` `deposit`: the percent of the booking's price the "
            "customer pays before the booking is confirmed (1–99), rounded to a whole "
            "minor unit. The rest is paid on site."
        ),
        depends_on="payment_policy == 'deposit'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.transfer_due_days",
        type="int",
        default=3,
        minimum=1,
        maximum=30,
        unit="day",
        label={"pl": "Termin przelewu", "en": "Days to transfer"},
        help={
            "pl": "Ile dni klient ma na przelew, zanim rezerwacja wygaśnie. Nigdy dłużej "
            "niż do początku rezerwacji.",
            "en": "How many days the customer has to transfer before the booking expires. "
            "Never past the booking's start.",
        },
        model_description=(
            "With a payment before confirmation: how many days the customer has to pay by "
            "a transfer before the booking expires (1–30), never past the booking's start."
        ),
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.balance_due_days_before",
        type="int",
        default=None,
        minimum=0,
        maximum=365,
        unit="day",
        label={"pl": "Dopłata reszty przelewem", "en": "The rest by a transfer"},
        help={
            "pl": "Ile dni przed początkiem rezerwacji klient ma dopłacić resztę przelewem. "
            "Puste: resztę płaci na miejscu. Spóźniona dopłata niczego nie odwołuje — "
            "klient dostaje przypomnienie, a firma powiadomienie.",
            "en": "How many days before the booking starts the customer transfers the "
            "rest. Empty: the rest is paid on site. A late balance calls nothing off — "
            "the customer is reminded and the company is told.",
        },
        model_description=(
            "With `payment_policy` `deposit`: how many days before the booking's start "
            "the rest of the price is due by a bank transfer (0–365). Null: the rest is "
            "paid on site. A balance not paid by its date cancels nothing: the customer "
            "gets reminders, the company a notice, and only the company calls the booking "
            "off."
        ),
        depends_on="payment_policy == 'deposit'",
    ),
    SettingSpec(
        scopes=("offer",),
        key="booking.offer.cancellation_applies_to",
        type="enum",
        default=RefundBasis.DEPOSIT.value,
        values=(
            (
                RefundBasis.DEPOSIT.value,
                {"pl": "Tylko przedpłaty", "en": "The prepayment only"},
            ),
            (
                RefundBasis.PAID.value,
                {"pl": "Wszystkich wpłat, także dopłaty", "en": "Everything paid, the rest too"},
            ),
        ),
        label={"pl": "Progi zwrotu dotyczą", "en": "Refund thresholds cover"},
        help={
            "pl": "Domyślnie progi zwrotu dotyczą tylko przedpłaty, a dopłata wraca do "
            "klienta w całości. Włącz „także dopłaty”, jeśli klient ma tracić również jej "
            "część.",
            "en": "By default the thresholds cover the prepayment only and the rest the "
            "customer paid goes back whole. Choose „the rest too” when the customer is to "
            "lose a part of that as well.",
        },
        model_description=(
            "With `payment_policy` `deposit`: what the refund thresholds "
            "(`cancellation_refunds`) are counted on when a customer gives a booking up — "
            "`deposit`: the prepayment only, anything else paid goes back whole (the "
            "default); `paid`: everything the customer paid. Without a prepayment that is "
            "a part of the price the thresholds always cover everything paid."
        ),
        depends_on="payment_policy == 'deposit'",
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
