"""Reference exchange rates for a guest's indicative price (ADR-072, slice
5i): one table a day from the chosen central bank, kept; a rate only while the
table is fresh; no request beyond the bank's table — and none in these tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from importlib import import_module
from io import StringIO
from typing import Any

import pytest
from celery.schedules import crontab
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError

from saas_core.modules.core.organizations import exchange_rates, platform_settings
from saas_core.modules.core.organizations.exchange_rates import (
    MAX_AGE_DAYS,
    RATE_CURRENCIES,
    SOURCE,
    RatesUnavailable,
    conversion,
    refresh,
)
from saas_core.modules.core.organizations.models import ExchangeRateTable
from saas_core.modules.core.organizations.settings_registry import setting_group
from saas_core.modules.core.organizations.tasks import refresh_exchange_rates

pytestmark = pytest.mark.django_db

#: NBP's table A as its API sends it (7 October 2026), cut to a few rows.
NBP = (
    b'[{"table":"A","no":"195/A/NBP/2026","effectiveDate":"2026-10-07","rates":['
    b'{"currency":"dolar ameryka\xc5\x84ski","code":"USD","mid":3.9111},'
    b'{"currency":"euro","code":"EUR","mid":4.3797},'
    b'{"currency":"korona czeska","code":"CZK","mid":0.1794}]}]'
)
#: The ECB's daily file, cut the same way.
ECB = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n<gesmes:Envelope '
    b'xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
    b'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">\n'
    b"<gesmes:subject>Reference rates</gesmes:subject>\n<Cube>\n"
    b"<Cube time='2026-10-07'>\n<Cube currency='USD' rate='1.1198'/>\n"
    b"<Cube currency='PLN' rate='4.3800'/>\n<Cube currency='CZK' rate='24.410'/>\n"
    b"</Cube>\n</Cube>\n</gesmes:Envelope>"
)
DAY = date(2026, 10, 7)


@pytest.fixture
def bank(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The bank's answer and what it was asked — the module's one request,
    replaced: no test reaches a bank. `source` is the operators' choice."""
    asked: dict[str, Any] = {"urls": [], "answer": NBP, "source": None}
    cache.clear()
    monkeypatch.setattr(
        platform_settings,
        "platform_overrides",
        lambda: {SOURCE.key: asked["source"]} if asked["source"] else {},
    )

    def read(url: str) -> bytes:
        asked["urls"].append(url)
        if isinstance(asked["answer"], Exception):
            raise asked["answer"]
        return asked["answer"]

    monkeypatch.setattr(exchange_rates, "_read", read)
    return asked


def test_the_source_is_the_platforms_choice_and_nbp_until_an_operator_says_otherwise() -> None:
    assert SOURCE.scopes == ("platform",)
    assert SOURCE.default == "nbp"
    assert [key for key, _label in SOURCE.values] == sorted(exchange_rates.SOURCES, reverse=True)
    assert setting_group(SOURCE.group).area == "pricing-platform"
    # Every company currency and every reader's currency is kept, nothing else.
    assert RATE_CURRENCIES == ("EUR", "PLN", "USD")


def test_the_nbp_table_is_kept_as_what_one_unit_costs_in_zloty(bank: dict[str, Any]) -> None:
    table = refresh(today=DAY)

    assert bank["urls"] == ["https://api.nbp.pl/api/exchangerates/tables/A/?format=json"]
    assert (table.source, table.base_currency, table.published_on) == ("nbp", "PLN", DAY)
    assert table.rates == {"EUR": "4.379700", "PLN": "1", "USD": "3.911100"}
    assert ExchangeRateTable.objects.count() == 1


def test_the_ecb_table_is_turned_over_to_what_one_unit_costs_in_euro(
    bank: dict[str, Any],
) -> None:
    bank["source"], bank["answer"] = "ecb", ECB

    table = refresh(today=DAY)

    assert bank["urls"] == ["https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"]
    assert (table.source, table.base_currency, table.published_on) == ("ecb", "EUR", DAY)
    assert table.rates["EUR"] == "1"
    assert Decimal(table.rates["PLN"]) == Decimal("0.228311")
    assert Decimal(table.rates["USD"]) == Decimal("0.893017")


def test_a_bank_is_asked_only_while_todays_table_is_not_here(bank: dict[str, Any]) -> None:
    refresh(today=DAY)
    refresh(today=DAY)
    assert len(bank["urls"]) == 1

    # The next day the bank has not published yet: asked, the same table again.
    refresh(today=date(2026, 10, 8))
    assert len(bank["urls"]) == 2
    assert ExchangeRateTable.objects.count() == 1


@pytest.mark.parametrize(
    "answer",
    [
        b"<html>503</html>",
        b"[]",
        b'[{"effectiveDate":"2026-10-07","rates":[{"code":"EUR","mid":4.3797}]}]',
        b'[{"effectiveDate":"2026-10-07","rates":[{"code":"EUR","mid":0},'
        b'{"code":"USD","mid":3.9}]}]',
        RatesUnavailable("rates_unreachable"),
    ],
)
def test_an_answer_that_is_not_the_table_changes_nothing(bank: dict[str, Any], answer: Any) -> None:
    refresh(today=date(2026, 10, 6))
    kept = ExchangeRateTable.objects.get()
    kept.published_on = date(2026, 10, 6)
    kept.save()
    bank["answer"] = answer

    with pytest.raises(RatesUnavailable):
        refresh(today=DAY)

    assert list(ExchangeRateTable.objects.values_list("published_on", "rates")) == [
        (date(2026, 10, 6), kept.rates)
    ]
    # The scheduled task says nothing came and leaves the next run to try.
    assert refresh_exchange_rates() == ""


def test_a_reader_gets_their_currency_the_rate_its_day_and_whose_it_is(
    bank: dict[str, Any],
) -> None:
    refresh(today=DAY)

    assert conversion("PLN", "de", today=DAY) == {
        "currency": "EUR",
        "rate": "0.228326",
        "date": "2026-10-07",
        "source": "NBP",
    }
    # A company that prices in euro, read in Polish: through the złoty table.
    assert conversion("EUR", "pl", today=DAY) == {
        "currency": "PLN",
        "rate": "4.379700",
        "date": "2026-10-07",
        "source": "NBP",
    }
    assert conversion("USD", "en", today=DAY)["rate"] == "0.893006"


def test_nothing_is_said_where_there_is_nothing_to_convert(bank: dict[str, Any]) -> None:
    refresh(today=DAY)

    # The reader's currency is the company's own.
    assert conversion("PLN", "pl", today=DAY) is None
    assert conversion("EUR", "de", today=DAY) is None
    # A language read in no one currency, and a code that is no language.
    assert conversion("PLN", "ru", today=DAY) is None
    assert conversion("PLN", "", today=DAY) is None
    # A currency the table does not keep.
    assert conversion("GBP", "de", today=DAY) is None


def test_an_old_table_gives_no_figure_rather_than_an_old_one(bank: dict[str, Any]) -> None:
    assert conversion("PLN", "de", today=DAY) is None  # no table at all
    refresh(today=DAY)

    last_day = date(2026, 10, 7 + MAX_AGE_DAYS)
    assert conversion("PLN", "de", today=last_day) is not None
    assert conversion("PLN", "de", today=date(2026, 10, 8 + MAX_AGE_DAYS)) is None


def test_another_banks_table_is_not_read_after_the_operator_changed_the_source(
    bank: dict[str, Any],
) -> None:
    refresh(today=DAY)
    bank["source"] = "ecb"

    assert conversion("PLN", "de", today=DAY) is None

    bank["answer"] = ECB
    refresh(today=DAY)
    found = conversion("PLN", "de", today=DAY)
    assert found is not None
    assert (found["rate"], found["source"]) == ("0.228311", "EZB")
    assert conversion("PLN", "en", today=DAY)["source"] == "ECB"


def test_the_task_keeps_the_table_and_is_scheduled_every_three_hours(
    bank: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exchange_rates.timezone, "localdate", lambda: DAY)

    assert refresh_exchange_rates() == "2026-10-07"

    base = import_module("saas_core.config.settings.base")
    entry = base._MODULE_BEAT_SCHEDULE["core.organizations"]["exchange-rates-refresh"]
    assert entry["task"] == refresh_exchange_rates.name
    assert entry["schedule"] == crontab(minute=20, hour="*/3")


def test_the_command_reads_the_table_now_and_fails_aloud(bank: dict[str, Any]) -> None:
    out = StringIO()
    call_command("refresh_exchange_rates", stdout=out)
    assert out.getvalue().startswith("nbp\t2026-10-07\t1 jednostka w PLN: EUR 4.379700")

    ExchangeRateTable.objects.all().delete()
    bank["answer"] = b"not a table"
    with pytest.raises(CommandError, match="nbp_table_malformed"):
        call_command("refresh_exchange_rates")
