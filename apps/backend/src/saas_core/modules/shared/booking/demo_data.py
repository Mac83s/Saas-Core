"""What the core scenario's own companies book (`demo.py` reads `DEFAULTS` by
the company's key): three companies that tell different stories.

- `studio` — visits: a price list with a Saturday price and an extra, payment
  on site, one offer taken „na prośbę” and one paid ahead by a transfer;
- `domki` — stays by the night: the offer started from the „Nocleg” preset,
  four units with what a guest sees of them, seasons, a price per night with
  people included and a discount for length, a prepayment, refund thresholds;
- `kajaki` — rentals by the day: a pool of identical units, a deposit held.

The bookings are a function of the calendar, not of the run: every day and
every week has the same bookings whenever the seed runs, so a second run finds
them and adds only those of days that have come into reach. Each is made at
the moment its story says (three days before, six weeks before) and is then
paid, accepted or called off at its own moments — which is why the screens show
a past, a present and a future, and orders in every state.

Customers of the past come by phone and have no e-mail, so nothing is mailed
about what is over; the few who book for themselves on the public form (and
tick the documents and the marketing consent) book ahead and get the mails a
real customer gets.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .demo import Plan, _mailbox

OWNER, MANAGER, STAFF = "wlasciciel@saas.test", "kierownik@saas.test", "pracownik@saas.test"
LODGING_OWNER, RECEPTION = "domki@saas.test", "recepcja.domki@saas.test"
RENTAL_OWNER = "kajaki@saas.test"

_DAY = timedelta(days=1)

#: Who phones to book: a name and a number, never an address.
_CALLERS = (
    "Joanna Nowak",
    "Piotr Zieliński",
    "Katarzyna Wiśniewska",
    "Tomasz Lewandowski",
    "Agnieszka Kamińska",
    "Ewa Kowalczyk",
    "Marcin Szymański",
    "Barbara Woźniak",
    "Michał Wójcik",
    "Magdalena Kozłowska",
    "Krzysztof Jankowski",
    "Aleksandra Mazur",
)
#: Who books for themselves on the public form.
_GUESTS = (
    "Natalia Krawczyk",
    "Jakub Piotrowski",
    "Zofia Grabowska",
    "Adam Pawłowski",
    "Julia Michalska",
    "Mateusz Król",
    "Oliwia Wieczorek",
    "Szymon Jabłoński",
)


def _caller(index: int, series: int = 1) -> dict[str, str]:
    """A customer the team knows by phone. The numbers are plainly made up."""
    slot = index % len(_CALLERS)
    return {
        "display_name": _CALLERS[slot],
        "phone": f"+48 600 00{series} {slot:03d}",
        "locale": "pl",
    }


def _guest(index: int) -> dict[str, str]:
    name = _GUESTS[index % len(_GUESTS)]
    return {"display_name": name, "email": _mailbox(name), "locale": "pl"}


# --- Studio Testowe: visits --------------------------------------------------------


def studio_stories(plan: Plan) -> None:
    for day in plan.days(7, 7):
        if day in plan.catalogue.closed:
            continue
        n, weekday = day.toordinal(), day.weekday()
        # The morning consultation: booked by the person who takes it, paid at
        # the desk afterwards. On a Saturday it costs the Saturday price.
        plan.visit(
            f"rano:{day}",
            day,
            "10:00",
            offer="Konsultacja",
            staff=[STAFF],
            by=STAFF,
            booked=plan.at(day - 3 * _DAY, "14:10"),
            customer=_caller(n),
            agreed=n % 2 == 0,
        ).then("commerce.pay", plan.at(day, "11:05"), method="cash", by=MANAGER)
        # Noon: with the extra every other day; one customer in seven does not
        # come, one visit in five is still to be paid for.
        noon = plan.visit(
            f"poludnie:{day}",
            day,
            "12:00",
            offer="Konsultacja",
            staff=[MANAGER],
            by=MANAGER,
            booked=plan.at(day - 5 * _DAY, "09:30"),
            customer=_caller(n + 4),
            extras=("Materiały szkoleniowe",) if n % 2 == 0 else (),
        )
        if n % 7 == 3:
            noon.then("booking.no_show", plan.at(day, "12:20"), by=MANAGER)
        elif n % 5:
            noon.then("commerce.pay", plan.at(day, "13:05"), method="cash", by=MANAGER)
        if weekday in (0, 2, 4):
            # A service for two with one person named: the other place waits
            # in „Do przydzielenia” until somebody takes it.
            plan.visit(
                f"we-dwoje:{day}",
                day,
                "15:00",
                offer="Sesja we dwoje",
                staff=[OWNER],
                by=OWNER,
                booked=plan.at(day - 4 * _DAY, "16:00"),
                customer=_caller(n + 7),
            ).then("commerce.pay", plan.at(day, "16:05"), method="transfer")
        if weekday in (1, 3):
            evening = plan.visit(
                f"wieczor:{day}",
                day,
                "17:00",
                offer="Konsultacja",
                staff=[MANAGER],
                by=MANAGER,
                booked=plan.at(day - 2 * _DAY, "11:00"),
                customer=_caller(n + 9),
            )
            if n % 4 == 0:
                # The company calls it off the day before.
                evening.then("booking.cancel", plan.at(day - _DAY, "15:00"), by=MANAGER)
            else:
                evening.then("commerce.pay", plan.at(day, "18:05"), method="cash", by=MANAGER)
    for day in plan.days(2, 0):
        # Every day one customer asks for the offer taken „na prośbę”. The
        # company has 48 hours: it accepts one, declines another with a reason
        # and leaves the third unanswered — today's still waits.
        n = day.toordinal()
        visit = day + 6 * _DAY
        if visit in plan.catalogue.closed:
            continue
        request = plan.visit(
            f"prosba:{day}",
            visit,
            "16:00",
            offer="Warsztat indywidualny",
            booked=plan.at(day, "06:00"),
            customer=_guest(n),
            marketing=n % 2 == 0,
            notes="Proszę o salę z rzutnikiem.",
        )
        if n % 3 == 0:
            request.then("booking.accept", plan.at(day + _DAY, "09:00"), by=OWNER)
            request.then("commerce.pay", plan.at(visit, "17:35"), method="cash")
        elif n % 3 == 1:
            request.then(
                "booking.decline",
                plan.at(day + _DAY, "09:00"),
                by=OWNER,
                reason="W tym terminie prowadzimy szkolenie zamknięte. Zapraszamy w innym dniu.",
            )
        else:
            request.then("booking.expire", plan.at(day + 2 * _DAY, "06:01"))
    for day in plan.days(3, 0):
        # And one books the offer paid ahead by a transfer: three days to pay.
        # Every other one pays the next morning; the rest let the date pass.
        n = day.toordinal()
        visit = day + 8 * _DAY
        if visit in plan.catalogue.closed:
            continue
        prepaid = plan.visit(
            f"przelew:{day}",
            visit,
            "08:00",
            offer="Pakiet startowy",
            booked=plan.at(day, "07:00"),
            customer=_guest(n + 3),
            marketing=n % 3 == 0,
        )
        if n % 2 == 0:
            prepaid.then(
                "commerce.pay", plan.at(day + _DAY, "10:00"), method="transfer", amount="awaited"
            )
        else:
            prepaid.then("commerce.lapse", plan.at(day + 3 * _DAY, "07:01"))
    _studio_once(plan)


def _studio_once(plan: Plan) -> None:
    """What happened once: a booking given up early and paid back, one given
    up late and settled by the terms, three customers of long ago (what the
    removal of customers' data after a time would take, switched off as it
    is) and one customer anonymised at their own request."""
    today = plan.today
    # Paid, given up eleven days before: everything goes back, and went.
    begun = today - 10 * _DAY
    plan.visit(
        "zwrot",
        begun + 14 * _DAY,
        "13:00",
        offer="Pakiet startowy",
        booked=plan.at(begun, "18:20"),
        customer=_guest(6),
    ).then(
        "commerce.pay", plan.at(begun + _DAY, "09:15"), method="transfer", amount="awaited"
    ).then("booking.cancel", plan.at(begun + 3 * _DAY, "20:00")).then(
        "commerce.refund", plan.at(begun + 4 * _DAY, "10:00"), method="transfer"
    )
    # Paid, given up four days before: half goes back — and is still owed.
    begun = today - 9 * _DAY
    plan.visit(
        "rezygnacja",
        begun + 12 * _DAY,
        "13:00",
        offer="Pakiet startowy",
        booked=plan.at(begun, "12:00"),
        customer=_guest(7),
    ).then(
        "commerce.pay", plan.at(begun + _DAY, "08:30"), method="transfer", amount="awaited"
    ).then("booking.cancel", plan.at(begun + 8 * _DAY, "19:00"))
    for index, (name, ago) in enumerate((
        ("Halina Borkowska", 400),
        ("Zbigniew Sadowski", 460),
        ("Teresa Rutkowska", 800),
    )):
        day = today - ago * _DAY
        plan.visit(
            f"dawny-klient:{index}",
            day,
            "10:00",
            offer="Konsultacja",
            staff=[OWNER],
            by=OWNER,
            booked=plan.at(day - 2 * _DAY, "12:00"),
            customer={"display_name": name, "phone": f"+48 600 009 00{index}", "locale": "pl"},
        ).then("commerce.pay", plan.at(day, "11:05"), method="cash")
    day = today - 20 * _DAY
    plan.visit(
        "zapomniany",
        day,
        "14:00",
        offer="Konsultacja",
        staff=[STAFF],
        by=STAFF,
        booked=plan.at(day - 3 * _DAY, "10:00"),
        customer={"display_name": "Ryszard Pawlak", "phone": "+48 600 009 010", "locale": "pl"},
    ).then("commerce.pay", plan.at(day, "15:05"), method="cash", by=MANAGER).then(
        "booking.anonymize", plan.at(today - 6 * _DAY, "12:00"), by=OWNER
    )


_VISIT_REFUNDS = [
    {"min_days_before": 7, "refund_percent": 100},
    {"min_days_before": 2, "refund_percent": 50},
]

STUDIO: dict[str, Any] = {
    "location": {"name": "Studio — sala 1", "address": "ul. Testowa 1, Warszawa"},
    "staff": [OWNER, MANAGER, STAFF],
    "hours": {"weekdays": [0, 1, 2, 3, 4, 5, 6], "local_start": "07:00", "local_end": "21:00"},
    "services": [
        {
            "name": "Konsultacja",
            "words": {"en": {"name": "Consultation"}},
            "settings": {"duration_minutes": 60, "staff_count": 1, "payment_policy": "on_site"},
            "prices": [
                {"basis": "per_booking", "amount_minor": 15000, "vat_code": "23"},
                {
                    "name": "Sobota",
                    "weekdays": [5],
                    "basis": "per_booking",
                    "amount_minor": 18000,
                    "vat_code": "23",
                },
            ],
            "extras": [
                {
                    "name": "Materiały szkoleniowe",
                    "amount_minor": 4000,
                    "vat_code": "23",
                    "words": {"en": {"name": "Training materials"}},
                }
            ],
        },
        {
            "name": "Sesja we dwoje",
            "words": {"en": {"name": "Session with two consultants"}},
            "settings": {"duration_minutes": 60, "staff_count": 2, "payment_policy": "on_site"},
            "prices": [{"basis": "per_booking", "amount_minor": 26000, "vat_code": "23"}],
        },
        {
            "name": "Warsztat indywidualny",
            "words": {"en": {"name": "Individual workshop"}},
            "staff": [OWNER],
            "settings": {
                "duration_minutes": 90,
                "staff_count": 1,
                "confirmation": "on_request",
                "response_hours": 48,
                "payment_policy": "on_site",
            },
            "prices": [{"basis": "per_booking", "amount_minor": 32000, "vat_code": "23"}],
        },
        {
            "name": "Pakiet startowy",
            "words": {"en": {"name": "Starter package"}},
            "staff": [MANAGER],
            "settings": {
                "duration_minutes": 120,
                "staff_count": 1,
                "payment_policy": "transfer",
                "transfer_due_days": 3,
                "cancellation_refunds": _VISIT_REFUNDS,
            },
            "prices": [{"basis": "per_booking", "amount_minor": 60000, "vat_code": "23"}],
        },
    ],
    "closures": [{"day": (11, 11), "note": "Narodowe Święto Niepodległości"}],
    # „Wzorce ofert”: a sign-up for a preset that is only announced.
    "interests": [
        {
            "preset": "core.group_class",
            "note": "Warsztaty dla 6–8 osób raz w tygodniu: limit miejsc, lista uczestników "
            "i lista rezerwowa, gdy ktoś zrezygnuje.",
        }
    ],
    "stories": studio_stories,
}


# --- Domki nad Jeziorem: stays by the night ------------------------------------------

STAY = "Pobyt nad jeziorem"
PINE, BIRCH = "Domek Sosnowy", "Domek Brzozowy"
FLAT, CABIN = "Apartament na piętrze", "Chata przy pomoście"


def lodging_stories(plan: Plan) -> None:
    """Every week the same guests' rhythm: two stays in one cottage, one in
    the other, a weekend in the apartment, a longer stay in the cabin — booked
    weeks before, the prepayment by a transfer, the rest two weeks before
    arrival. Three more bookings are made each week for eight weeks ahead and
    wait for their transfer: at any moment one of them still does."""
    for monday in plan.weeks(4, 9):
        week = monday.toordinal() // 7
        key = monday.isoformat()
        plan.stay(
            f"sosnowy-pon:{key}",
            monday,
            monday + 3 * _DAY,
            offer=STAY,
            unit=PINE,
            by=RECEPTION,
            booked=plan.at(monday - 45 * _DAY, "10:00"),
            customer=_caller(week, 2),
            people={"": 2, "Dziecko": 1},
        ).then(
            "commerce.pay",
            plan.at(monday - 44 * _DAY, "12:00"),
            method="transfer",
            amount="awaited",
        ).then("commerce.pay", plan.at(monday - 15 * _DAY, "09:00"), method="transfer")
        plan.stay(
            f"sosnowy-czw:{key}",
            monday + 3 * _DAY,
            monday + 6 * _DAY,
            offer=STAY,
            unit=PINE,
            by=RECEPTION,
            booked=plan.at(monday - 30 * _DAY, "13:30"),
            customer=_caller(week + 3, 2),
            people={"": 4, "Pies": 1},
            extras=("Pościel",),
            # Everything at once, the day after booking.
        ).then("commerce.pay", plan.at(monday - 29 * _DAY, "11:00"), method="transfer")
        birch = plan.stay(
            f"brzozowy:{key}",
            monday + _DAY,
            monday + 5 * _DAY,
            offer=STAY,
            unit=BIRCH,
            by=LODGING_OWNER,
            booked=plan.at(monday - 40 * _DAY, "16:30"),
            customer=_caller(week + 6, 2),
            people={"": 5},
            agreed=True,
        ).then(
            "commerce.pay",
            plan.at(monday - 38 * _DAY, "10:30"),
            method="transfer",
            amount="awaited",
        )
        if week % 3:
            birch.then("commerce.pay", plan.at(monday - 14 * _DAY, "08:45"), method="transfer")
        else:
            # The rest was not paid by its date: late until the guests pay on
            # arrival, at the desk.
            birch.then("commerce.pay", plan.at(monday + _DAY, "15:20"), method="cash")
        plan.stay(
            f"apartament-weekend:{key}",
            monday + 4 * _DAY,
            monday + 7 * _DAY,
            offer=STAY,
            unit=FLAT,
            by=RECEPTION,
            booked=plan.at(monday - 20 * _DAY, "09:10"),
            customer=_caller(week + 9, 2),
            people={"": 2},
        ).then(
            "commerce.pay",
            plan.at(monday - 19 * _DAY, "14:00"),
            method="transfer",
            amount="awaited",
        ).then("commerce.pay", plan.at(monday - 11 * _DAY, "09:40"), method="transfer")
        _cabin(plan, monday, week, key)
        _awaited(plan, monday, week, key)


def _cabin(plan: Plan, monday: date, week: int, key: str) -> None:
    """Every other week the cabin is booked by guests themselves, on the
    company's site: one gives it up early and gets the prepayment back, the
    next one late — and half of it stays with the company. The weeks between
    are booked by phone."""
    first, last = monday + 2 * _DAY, monday + 6 * _DAY
    turn = week % 4
    lead = 50 if turn in (0, 2) else 35
    cabin = plan.stay(
        f"chata:{key}",
        first,
        last,
        offer=STAY,
        unit=CABIN,
        booked=plan.at(first - lead * _DAY, "19:40"),
        by="" if turn in (0, 2) else RECEPTION,
        customer=_guest(week) if turn in (0, 2) else _caller(week + 2, 3),
        people={"": 2, "Dziecko": 1} if turn == 3 else {"": 2},
        marketing=turn == 0,
        notes="Przyjedziemy wieczorem, po 19:00." if turn == 1 else "",
    ).then(
        "commerce.pay",
        plan.at(first - (lead - 1) * _DAY, "10:00"),
        method="transfer",
        amount="awaited",
    )
    if turn == 0:
        cabin.then("booking.cancel", plan.at(first - 35 * _DAY, "18:00")).then(
            "commerce.refund", plan.at(first - 34 * _DAY, "09:00"), method="transfer"
        )
    elif turn == 2:
        cabin.then("booking.cancel", plan.at(first - 20 * _DAY, "21:10"))
    else:
        cabin.then("commerce.pay", plan.at(first - 15 * _DAY, "08:20"), method="transfer")


def _awaited(plan: Plan, monday: date, week: int, key: str) -> None:
    """Booked eight weeks before, on a Monday, a Wednesday and a Friday: two
    pay their prepayment two days later, the third lets its three days pass."""
    booked = monday - 56 * _DAY
    plan.stay(
        f"apartament-pon:{key}",
        monday,
        monday + 2 * _DAY,
        offer=STAY,
        unit=FLAT,
        by=RECEPTION,
        booked=plan.at(booked, "06:30"),
        customer=_caller(week + 1, 3),
        people={"": 2},
    ).then(
        "commerce.pay", plan.at(booked + 2 * _DAY, "08:00"), method="transfer", amount="awaited"
    ).then("commerce.pay", plan.at(monday - 15 * _DAY, "10:10"), method="transfer")
    # One week in four this one is booked by the guest, on the company's site.
    online = week % 4 == 1
    midweek = (
        plan.stay(
            f"apartament-sr:{key}",
            monday + 2 * _DAY,
            monday + 4 * _DAY,
            offer=STAY,
            unit=FLAT,
            by="" if online else RECEPTION,
            booked=plan.at(booked + 2 * _DAY, "07:00"),
            customer=_guest(week + 4) if online else _caller(week + 8, 3),
            people={"": 2},
            marketing=online,
        )
        .then(
            "commerce.pay", plan.at(booked + 4 * _DAY, "08:00"), method="transfer", amount="awaited"
        )
        .then("commerce.pay", plan.at(monday - 13 * _DAY, "10:10"), method="transfer")
    )
    if online:
        # Closed when the guest leaves, so no reminder follows a stay of the past.
        midweek.then("booking.complete", plan.at(monday + 4 * _DAY, "11:00"))
    plan.stay(
        f"brzozowy-weekend:{key}",
        monday + 5 * _DAY,
        monday + 7 * _DAY,
        offer=STAY,
        unit=BIRCH,
        by=RECEPTION,
        booked=plan.at(booked + 4 * _DAY, "07:00"),
        customer=_caller(week + 5, 3),
        people={"": 4},
    ).then("commerce.lapse", plan.at(booked + 7 * _DAY, "07:01"))


def _per_night(amount: int, name: str = "", season: Any = None, **more: Any) -> dict[str, Any]:
    return {
        **({"name": name} if name else {}),
        **({"season": season} if season else {}),
        "basis": "per_time_unit",
        "amount_minor": amount,
        "vat_code": "8",
        **more,
    }


_COTTAGE_PEOPLE: dict[str, Any] = {
    "included_people": 4,
    "extra_person_amount_minor": 6000,
    "extra_person_per_time_unit": True,
    "category_prices": [
        {"category": "Dziecko", "amount_minor": 3000},
        {"category": "Pies", "amount_minor": 2500},
    ],
    "length_discounts": [{"min_length": 3, "percent": 5}, {"min_length": 7, "percent": 12}],
}
_SUMMER, _HOLIDAYS = ((7, 1), (8, 31)), ((12, 23), (1, 2))
_COTTAGE_AMENITIES = [
    "wifi",
    "parking",
    "kitchen",
    "fridge",
    "bathroom",
    "bed_linen",
    "towels",
    "fireplace",
    "terrace",
    "grill",
    "lake_access",
    "pier",
    "pets_allowed",
]

LODGING: dict[str, Any] = {
    "location": {"name": "Domki nad Jeziorem", "address": "ul. Leśna 3, Mikołajki"},
    "categories": [
        {
            "name": "Dziecko",
            "counts": True,
            "words": {"en": {"name": "Child"}, "de": {"name": "Kind"}},
        },
        {
            "name": "Pies",
            "counts": False,
            "words": {"en": {"name": "Dog"}, "de": {"name": "Hund"}},
        },
    ],
    "groups": [
        {
            "name": "Domek nad jeziorem",
            "description": "Dwie sypialnie, salon z kominkiem, taras i własny pomost. Dla 6 osób.",
            "words": {
                "en": {
                    "name": "Lakeside cottage",
                    "description": "Two bedrooms, a living room with a fireplace, a terrace "
                    "and a private pier. For 6 guests.",
                },
                "de": {
                    "name": "Ferienhaus am See",
                    "description": "Zwei Schlafzimmer, Wohnzimmer mit Kamin, Terrasse und "
                    "eigener Steg. Für 6 Gäste.",
                },
            },
            "prices": [
                _per_night(42000, **_COTTAGE_PEOPLE),
                _per_night(56000, "Sezon letni", _SUMMER, **_COTTAGE_PEOPLE),
                _per_night(62000, "Święta i sylwester", _HOLIDAYS, **_COTTAGE_PEOPLE),
            ],
        }
    ],
    "units": [
        {
            "name": PINE,
            "capacity": 6,
            "group": "Domek nad jeziorem",
            "description": "Domek wśród sosen, 40 m od wody. Dwie sypialnie, salon z kominkiem, "
            "taras od strony jeziora. Zdjęcia poglądowe.",
            "amenities": _COTTAGE_AMENITIES,
            "town": "mikolajki",
            "photos": ["business", "agriculture"],
            "words": {
                "en": {
                    "name": "Pine Cottage",
                    "description": "A cottage among the pines, 40 m from the water. Two "
                    "bedrooms, a living room with a fireplace, a terrace facing the lake. "
                    "Illustrative photos.",
                },
                "de": {
                    "name": "Kiefernhaus",
                    "description": "Ein Haus zwischen Kiefern, 40 m vom Wasser. Zwei "
                    "Schlafzimmer, Wohnzimmer mit Kamin, Terrasse zum See. Beispielfotos.",
                },
            },
        },
        {
            "name": BIRCH,
            "capacity": 6,
            "group": "Domek nad jeziorem",
            "description": "Domek przy brzozowym zagajniku, z dużym tarasem i grillem. "
            "Dwie sypialnie, salon z kominkiem. Zdjęcia poglądowe.",
            "amenities": [*_COTTAGE_AMENITIES, "playground"],
            "town": "mikolajki",
            "photos": ["agriculture", "business"],
            "words": {
                "en": {
                    "name": "Birch Cottage",
                    "description": "A cottage by the birch grove, with a large terrace and "
                    "a barbecue. Two bedrooms, a living room with a fireplace. Illustrative "
                    "photos.",
                },
                "de": {
                    "name": "Birkenhaus",
                    "description": "Ein Haus am Birkenhain, mit großer Terrasse und Grill. "
                    "Zwei Schlafzimmer, Wohnzimmer mit Kamin. Beispielfotos.",
                },
            },
        },
        {
            "name": FLAT,
            "capacity": 2,
            "description": "Apartament dla dwojga nad recepcją: sypialnia, aneks kuchenny, "
            "balkon z widokiem na jezioro. Zdjęcie poglądowe.",
            "amenities": [
                "wifi",
                "parking",
                "kitchenette",
                "fridge",
                "bathroom",
                "bed_linen",
                "towels",
                "tv",
                "heating",
                "terrace",
                "smoke_free",
            ],
            "town": "mikolajki",
            "photos": ["business"],
            "words": {
                "en": {
                    "name": "Upstairs apartment",
                    "description": "An apartment for two above the reception: a bedroom, "
                    "a kitchenette, a balcony with a view of the lake. Illustrative photo.",
                },
                "de": {
                    "name": "Apartment im Obergeschoss",
                    "description": "Ein Apartment für zwei über der Rezeption: Schlafzimmer, "
                    "Kochnische, Balkon mit Seeblick. Beispielfoto.",
                },
            },
            "prices": [
                _per_night(26000, length_discounts=[{"min_length": 3, "percent": 5}]),
                _per_night(34000, "Sezon letni", _SUMMER),
            ],
        },
        {
            "name": CABIN,
            "capacity": 4,
            "description": "Drewniana chata tuż przy pomoście, z sauną i rowerami dla gości. "
            "Jedna sypialnia i antresola. Zdjęcie poglądowe.",
            "amenities": [
                "wifi",
                "parking",
                "kitchenette",
                "fridge",
                "bathroom",
                "bed_linen",
                "towels",
                "sauna",
                "lake_access",
                "pier",
                "bikes",
                "grill",
            ],
            "town": "mikolajki",
            # The one unit whose company shows its exact point on the map.
            "point": ("53.796800", "21.590100"),
            "show_point": True,
            "photos": ["agriculture"],
            "words": {
                "en": {
                    "name": "Cabin by the pier",
                    "description": "A wooden cabin right by the pier, with a sauna and bikes "
                    "for guests. One bedroom and a mezzanine. Illustrative photo.",
                },
                "de": {
                    "name": "Hütte am Steg",
                    "description": "Eine Holzhütte direkt am Steg, mit Sauna und Fahrrädern "
                    "für die Gäste. Ein Schlafzimmer und eine Galerie. Beispielfoto.",
                },
            },
            "prices": [
                _per_night(
                    34000,
                    included_people=2,
                    extra_person_amount_minor=5000,
                    extra_person_per_time_unit=True,
                    category_prices=[
                        {"category": "Dziecko", "amount_minor": 2500},
                        {"category": "Pies", "amount_minor": 2500},
                    ],
                    length_discounts=[{"min_length": 4, "percent": 8}],
                ),
                _per_night(
                    45000,
                    "Sezon letni",
                    _SUMMER,
                    included_people=2,
                    extra_person_amount_minor=6000,
                    extra_person_per_time_unit=True,
                ),
            ],
        },
    ],
    "services": [
        {
            "name": STAY,
            "words": {"en": {"name": "Lakeside stay"}, "de": {"name": "Aufenthalt am See"}},
            "preset": "core.lodging",
            "groups": ["Domek nad jeziorem"],
            "units": [FLAT, CABIN],
            # The preset brings the terms: 30% ahead within 3 days, the rest
            # 14 days before, the prepayment back in full up to 30 days and by
            # half up to 14 days before. The company only chooses to take it.
            "settings": {"payment_policy": "deposit"},
            "extras": [
                {
                    "name": "Sprzątanie końcowe",
                    "amount_minor": 15000,
                    "vat_code": "23",
                    "mandatory": True,
                    "words": {"en": {"name": "Final cleaning"}, "de": {"name": "Endreinigung"}},
                },
                {
                    "name": "Opłata miejscowa",
                    "amount_minor": 300,
                    "basis": "per_person_per_time_unit",
                    "vat_code": "np",
                    "mandatory": True,
                    "words": {"en": {"name": "Local tourist tax"}, "de": {"name": "Kurtaxe"}},
                },
                {
                    "name": "Pościel",
                    "amount_minor": 3000,
                    "basis": "per_person",
                    "vat_code": "23",
                    "words": {"en": {"name": "Bed linen"}, "de": {"name": "Bettwäsche"}},
                },
                {
                    "name": "Kaucja",
                    "amount_minor": 50000,
                    "kind": "security_deposit",
                    "words": {"en": {"name": "Security deposit"}, "de": {"name": "Kaution"}},
                },
            ],
            "seasons": [
                {"name": "Cały rok — co najmniej dwie noce", "min_length": 2},
                {
                    "name": "Sezon letni — rezerwacja najpóźniej dobę przed przyjazdem",
                    "season": _SUMMER,
                    "min_length": 2,
                    "notice_hours": 24,
                },
            ],
        }
    ],
    "stories": lodging_stories,
}


# --- Kajaki Krutynia: rentals by the day ----------------------------------------------

RENTAL = "Wypożyczenie kajaka"
KAYAKS, CANOE = "Kajak 2-os.", "Canoe rodzinne"


def rental_stories(plan: Plan) -> None:
    for day in plan.days(7, 7):
        n, weekday = day.toordinal(), day.weekday()
        # A kayak for the day, any free one of the pool; paid when it is handed out.
        plan.stay(
            f"dzien:{day}",
            day,
            day,
            offer=RENTAL,
            group=KAYAKS,
            by=RENTAL_OWNER,
            booked=plan.at(day - 2 * _DAY, "17:00"),
            customer=_caller(n, 4),
        ).then("commerce.pay", plan.at(day, "09:10"), method="cash")
        if weekday in (1, 3):
            plan.stay(
                f"drugi:{day}",
                day,
                day,
                offer=RENTAL,
                group=KAYAKS,
                by=RENTAL_OWNER,
                booked=plan.at(day - _DAY, "12:15"),
                customer=_caller(n + 5, 4),
                extras=("Dowóz kajaka na start",),
            ).then("commerce.pay", plan.at(day, "09:25"), method="cash")
        if weekday == 2:
            # Called off by the company the day before — the weather.
            plan.stay(
                f"odwolany:{day}",
                day,
                day,
                offer=RENTAL,
                group=KAYAKS,
                by=RENTAL_OWNER,
                booked=plan.at(day - 4 * _DAY, "18:40"),
                customer=_caller(n + 8, 4),
            ).then("booking.cancel", plan.at(day - _DAY, "16:00"), by=RENTAL_OWNER)
        if weekday == 4:
            # Three days from Friday: the discount for length.
            plan.stay(
                f"weekend:{day}",
                day,
                day + 2 * _DAY,
                offer=RENTAL,
                group=KAYAKS,
                by=RENTAL_OWNER,
                booked=plan.at(day - 10 * _DAY, "12:00"),
                customer=_caller(n + 2, 4),
            ).then("commerce.pay", plan.at(day, "09:20"), method="cash")
        if weekday == 5:
            # The family canoe for the weekend, booked on the company's site.
            plan.stay(
                f"canoe:{day}",
                day,
                day + _DAY,
                offer=RENTAL,
                unit=CANOE,
                booked=plan.at(day - 5 * _DAY, "20:30"),
                customer=_guest(n // 7 + 2),
                marketing=(n // 7) % 2 == 0,
            ).then("commerce.pay", plan.at(day, "09:30"), method="cash").then(
                "booking.complete", plan.at(day + _DAY, "18:00")
            )


def _per_day(amount: int, **more: Any) -> dict[str, Any]:
    return {"basis": "per_time_unit", "amount_minor": amount, "vat_code": "23", **more}


RENTALS: dict[str, Any] = {
    "location": {"name": "Przystań Krutyń", "address": "Krutyń 12, Ruciane-Nida"},
    "groups": [
        {
            "name": KAYAKS,
            "description": "Kajak turystyczny z dwoma wiosłami i kamizelkami.",
            "words": {
                "en": {
                    "name": "Two-person kayak",
                    "description": "A touring kayak with two paddles and life jackets.",
                }
            },
            "prices": [_per_day(8000, length_discounts=[{"min_length": 3, "percent": 10}])],
        }
    ],
    "units": [
        *(
            {
                "name": f"Kajak {number}",
                "capacity": 2,
                "group": KAYAKS,
                "town": "ruciane-nida",
                "words": {"en": {"name": f"Kayak {number}"}},
            }
            for number in (1, 2, 3)
        ),
        {
            "name": CANOE,
            "capacity": 4,
            "description": "Stabilne canoe dla dwojga dorosłych i dwojga dzieci.",
            "town": "ruciane-nida",
            "words": {
                "en": {
                    "name": "Family canoe",
                    "description": "A stable canoe for two adults and two children.",
                }
            },
            "prices": [_per_day(12000)],
        },
    ],
    "services": [
        {
            "name": RENTAL,
            "words": {"en": {"name": "Kayak rental"}},
            "preset": "core.rental",
            "groups": [KAYAKS],
            "units": [CANOE],
            "extras": [
                {
                    "name": "Kaucja",
                    "amount_minor": 20000,
                    "kind": "security_deposit",
                    "words": {"en": {"name": "Security deposit"}},
                },
                {
                    "name": "Dowóz kajaka na start",
                    "amount_minor": 4000,
                    "vat_code": "23",
                    "words": {"en": {"name": "Kayak delivery to the start"}},
                },
            ],
        }
    ],
    "stories": rental_stories,
}

DEFAULTS: dict[str, dict[str, Any]] = {"studio": STUDIO, "domki": LODGING, "kajaki": RENTALS}
