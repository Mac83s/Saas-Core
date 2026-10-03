"""A company with amounts in its currency keeps that currency (ADR-073 §8).

Nobody converts a price list or an order, so a change of
`Organization.currency` is refused with `currency_in_use` while a module holds
amounts in it. Modules say so from `AppConfig.ready`, without Core importing
them: `register_currency_use(check)`, `check(organization_id)` → whether that
company has such amounts.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from rest_framework.exceptions import ErrorDetail, ValidationError

type CurrencyUse = Callable[[UUID], bool]

_uses: list[CurrencyUse] = []


def register_currency_use(check: CurrencyUse) -> None:
    if check not in _uses:
        _uses.append(check)


def refuse_currency_in_use(organization_id: UUID) -> None:
    if any(check(organization_id) for check in _uses):
        raise ValidationError({
            "currency": [
                ErrorDetail(
                    "Firma ma ceny w dotychczasowej walucie. Nikt ich nie przeliczy, "
                    "więc waluta zostaje.",
                    code="currency_in_use",
                )
            ]
        })
