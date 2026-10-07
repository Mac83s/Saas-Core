"""Reference exchange rates, for telling a guest roughly what a price is in
their own money (owner decision 16; ADR-072, „Rozstrzygnięcia plastra 5i").

A company keeps its prices in one currency and is paid in it. A page read in
another language may say beside a price „≈ 103 EUR": information, never the
amount of an order — nothing here touches a quote, an order or an e-mail, and
whoever shows the figure says so beside it.

- **Where the rates come from.** A central bank's daily reference table,
  free and without a key: NBP's table A (mid rates, in złoty) or the ECB's
  euro reference rates — the platform setting `exchange_rates.source`. Both
  are published once on a working day; `refresh` reads the chosen one and
  keeps it (`ExchangeRateTable`, one row per source and day of publication).
  The scheduler calls it every three hours and it asks the bank only while
  today's table is not here yet. It is the one request this module makes.
- **What a page gets.** `conversion(the company's currency, the reader's
  language)`: the reader's currency (`READER_CURRENCY`), how much of it one
  unit of the company's is, the table's day and whose table it is. None where
  the language has no currency here, where it is the company's own, and where
  the newest table is older than `MAX_AGE_DAYS` — no figure rather than an
  old one. The amount itself is worked out by whoever shows it, from the
  price it shows: one rate for a whole answer, and nothing to keep in step.

A product that composes only the core has this too: the table and the task
are the core's, and a module that shows prices asks `conversion`.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import ExchangeRateTable
from .options import currency_codes
from .permissions import SETTINGS_MANAGE
from .platform_settings import platform_setting
from .settings_registry import SettingArea, SettingGroup, SettingSpec

#: The currency most readers of a language count in. A language that is not
#: here gets no converted figure (Russian is read in too many currencies to
#: pick one); English reads euro, the currency of the markets the platform
#: enters.
READER_CURRENCY: Mapping[str, str] = {"pl": "PLN", "en": "EUR", "de": "EUR", "es": "EUR"}
#: What is kept of a table: the currencies companies price in and readers
#: count in. The banks publish thirty; nobody reads the rest.
RATE_CURRENCIES = tuple(sorted({*currency_codes(), *READER_CURRENCY.values()}))
#: A table older than this is not shown. The banks skip weekends and their
#: holidays: the longest gap is Thursday to Tuesday afternoon at Easter (ECB),
#: five days — one more and the figure would be a guess.
MAX_AGE_DAYS = 5
TIMEOUT_SECONDS = 10.0
#: NBP's table is about 3 kB, the ECB's about 2 kB.
MAX_BYTES = 200_000
_PLACES = Decimal("0.000001")


class RatesUnavailable(RuntimeError):
    """The source did not answer, or answered something that is not its table."""


def _nbp(raw: bytes) -> tuple[date, dict[str, Decimal]]:
    """`[{"effectiveDate": "2026-10-07", "rates": [{"code": "EUR", "mid": 4.3797}]}]`:
    what one unit costs in złoty."""
    table = json.loads(raw)[0]
    return date.fromisoformat(table["effectiveDate"]), {
        row["code"]: Decimal(str(row["mid"])) for row in table["rates"]
    }


_ECB_DAY = re.compile(rb"""time=["'](\d{4}-\d{2}-\d{2})["']""")
_ECB_RATE = re.compile(rb"""currency=["']([A-Z]{3})["']\s+rate=["']([0-9.]+)["']""")


def _ecb(raw: bytes) -> tuple[date, dict[str, Decimal]]:
    """`<Cube time="2026-10-07"><Cube currency="USD" rate="1.0876"/>…`: how
    much of each currency one euro is — turned over, to what one unit costs
    in euro. Read by pattern: the file is three kinds of line, and an XML
    parser would be the only thing here that follows what a document says."""
    day = _ECB_DAY.search(raw)
    if day is None:
        raise ValueError("no day")
    return date.fromisoformat(day[1].decode()), {
        found[1].decode(): 1 / Decimal(found[2].decode()) for found in _ECB_RATE.finditer(raw)
    }


@dataclass(frozen=True, slots=True)
class RateSource:
    key: str
    #: The currency its table counts in.
    base: str
    url: str
    #: The table's bytes → its day, and what one unit of each currency is
    #: worth in `base`.
    parse: Callable[[bytes], tuple[date, dict[str, Decimal]]]
    #: Whose table it is, as a page names it; another language reads `en`.
    names: Mapping[str, str]


SOURCES: Mapping[str, RateSource] = {
    "nbp": RateSource(
        key="nbp",
        base="PLN",
        url="https://api.nbp.pl/api/exchangerates/tables/A/?format=json",
        parse=_nbp,
        names={"en": "NBP"},
    ),
    "ecb": RateSource(
        key="ecb",
        base="EUR",
        url="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
        parse=_ecb,
        names={"en": "ECB", "pl": "EBC", "de": "EZB", "es": "BCE"},
    ),
}

SOURCE = SettingSpec(
    key="exchange_rates.source",
    type="enum",
    default="nbp",
    scopes=("platform",),
    values=(
        ("nbp", {"pl": "NBP — tabela A (kursy średnie)", "en": "NBP — table A (mid rates)"}),
        ("ecb", {"pl": "EBC — kursy referencyjne euro", "en": "ECB — euro reference rates"}),
    ),
    label={"pl": "Źródło kursów walut", "en": "Source of exchange rates"},
    model_description="Whose daily reference table gives the rate for the indicative "
    "converted price a guest sees beside a company's price on a page in another language: "
    "NBP (table A, in złoty) or the ECB (euro reference rates). Both are free and official. "
    "It never changes what a customer pays: orders stay in the company's currency.",
    help={
        "pl": "Z czyjej dziennej tabeli liczymy orientacyjną kwotę w walucie gościa, którą "
        "strona w innym języku pokazuje obok ceny firmy. Po zmianie nowa tabela pojawi się "
        "przy najbliższym odświeżeniu (co trzy godziny). Płatność zawsze w walucie firmy.",
        "en": "Whose daily table gives the indicative amount in the guest's currency that a "
        "page in another language shows beside the company's price. After a change the new "
        "table arrives with the next refresh (every three hours). Payment is always in the "
        "company's currency.",
    },
)

#: The core's own platform keys about money.
PLATFORM_AREA = SettingArea(
    key="pricing-platform",
    title={"pl": "Ceny i waluty", "en": "Prices and currencies"},
    description={
        "pl": "Co platforma ustawia dla cen pokazywanych gościom wszystkich firm.",
        "en": "What the platform sets for the prices every company's guests see.",
    },
    # Among the platform-only areas, after the companies' own.
    order=96,
)

RATES = SettingGroup(
    key="exchange_rates",
    module="core.organizations",
    title={"pl": "Kursy walut", "en": "Exchange rates"},
    description={
        "pl": "Skąd bierzemy dzienne kursy do orientacyjnych cen w walucie gościa.",
        "en": "Where the daily rates for indicative prices in the guest's currency come from.",
    },
    # A platform group: no company writes it; the registry only requires a
    # permission a composed module declares.
    permission=SETTINGS_MANAGE,
    area=PLATFORM_AREA.key,
    settings=(SOURCE,),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # type: ignore[no-untyped-def]
        return None


def _read(url: str) -> bytes:
    """The one request this module makes: the bank's table, as it sends it."""
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json, application/xml", "User-Agent": "saas-core"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            raw: bytes = response.read(MAX_BYTES)
            return raw
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RatesUnavailable("rates_unreachable") from error


def _source() -> RateSource:
    return SOURCES[platform_setting(SOURCE.key)]


def refresh(*, today: date | None = None) -> ExchangeRateTable:
    """The chosen source's newest table, kept. With today's table already here
    it asks nobody: a bank publishes one a day. `RatesUnavailable` when the
    bank does not answer with its table — what is kept stays as it is."""
    source = _source()
    day = today or timezone.localdate()
    kept = ExchangeRateTable.objects.filter(source=source.key).first()
    if kept is not None and kept.published_on >= day:
        return kept
    raw = _read(source.url)
    try:
        published_on, values = source.parse(raw)
        rates = {
            code: Decimal(1) if code == source.base else values[code].quantize(_PLACES)
            for code in RATE_CURRENCIES
        }
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        InvalidOperation,
        ZeroDivisionError,
    ) as error:
        raise RatesUnavailable(f"{source.key}_table_malformed") from error
    if any(value <= 0 for value in rates.values()):
        raise RatesUnavailable(f"{source.key}_table_malformed")
    table, _created = ExchangeRateTable.objects.update_or_create(
        source=source.key,
        published_on=published_on,
        defaults={
            "base_currency": source.base,
            "rates": {code: str(value) for code, value in rates.items()},
            "fetched_at": timezone.now(),
        },
    )
    return table


def conversion(currency: str, locale: str, *, today: date | None = None) -> dict[str, str] | None:
    """What a price in `currency` is roughly in the money of whoever reads
    `locale`: `{"currency", "rate", "date", "bank"}` — the reader's
    currency, how much of it one unit of `currency` is, the day of the table
    and whose it is, named in the reader's language. None: nothing to say
    (see the module note). Reads one row; asks no bank."""
    wanted = READER_CURRENCY.get(locale)
    if wanted is None or wanted == currency:
        return None
    source = _source()
    day = today or timezone.localdate()
    table = ExchangeRateTable.objects.filter(
        source=source.key, published_on__gte=day - timedelta(days=MAX_AGE_DAYS)
    ).first()
    if table is None:
        return None
    try:
        rate = (Decimal(table.rates[currency]) / Decimal(table.rates[wanted])).quantize(_PLACES)
    except (KeyError, InvalidOperation, ZeroDivisionError):
        return None
    if rate <= 0:
        return None
    return {
        "currency": wanted,
        "rate": str(rate),
        "date": table.published_on.isoformat(),
        "bank": source.names.get(locale, source.names["en"]),
    }
