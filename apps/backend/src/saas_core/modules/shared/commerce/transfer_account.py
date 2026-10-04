"""The company's bank account for its customers' transfers (ADR-073 §5).

A group on core's settings registry (ADR-078): who the account belongs to, its
number and, when the company wants it said, the bank. A customer who is to pay
by a transfer gets these with the order's number as the transfer's title.

A change asks for a fresh code from the authenticator app: an account number
changed by somebody who took over a session is where customers' money goes.
For the same reason the group has no assistant command — the account is typed
by a person.

A module whose offers ask for a transfer says so
(`register_transfer_account_use`), and the account is not cleared while one
does: the customers of that offer would be told to pay to nowhere.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
    register_setting_area,
    register_setting_group,
    setting,
)
from saas_core.modules.core.organizations.context import require_tenant_context

from .models import Payment, PaymentMethod, PaymentStatus
from .names import COMMERCE_ENABLED, PAYMENTS_MANAGE

HOLDER = "commerce.transfer.account_holder"
NUMBER = "commerce.transfer.account_number"
BANK = "commerce.transfer.bank_name"

#: A number without a country is Polish: 26 digits (NRB).
_DEFAULT_COUNTRY = "PL"
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


@dataclass(frozen=True, slots=True)
class TransferAccount:
    holder: str
    #: As a person reads it: the country, then groups of four.
    number: str
    bank: str


#: (organization) -> whether something of a module asks customers for a
#: transfer right now.
type AccountUse = Callable[[UUID], bool]

_uses: list[AccountUse] = []


def register_transfer_account_use(use: AccountUse) -> None:
    """From the `AppConfig.ready` of a module whose offers may ask for a
    transfer: while `use` answers true, the company's account stays."""
    if use not in _uses:
        _uses.append(use)


def transfer_account() -> TransferAccount | None:
    """The account the current company's customers pay to, or None while the
    company has given none."""
    number = normalized(str(setting(NUMBER) or ""))
    if not number:
        return None
    return TransferAccount(
        holder=str(setting(HOLDER) or "").strip(),
        number=" ".join([number[:4], *re.findall(r".{1,4}", number[4:])]),
        bank=str(setting(BANK) or "").strip(),
    )


def normalized(value: str) -> str:
    """The number as an IBAN without spaces; Polish where no country is
    given. Empty for an empty one; what a person typed, upper-cased, when it
    is no account number (the check says so)."""
    compact = re.sub(r"[\s-]", "", value).upper()
    return _DEFAULT_COUNTRY + compact if compact.isdigit() else compact


def valid(number: str) -> bool:
    """An IBAN by its shape and its check digits (ISO 13616, mod 97)."""
    if not _IBAN.fullmatch(number):
        return False
    moved = number[4:] + number[:4]
    return int("".join(str(int(sign, 36)) for sign in moved)) % 97 == 1


def _check(before: Mapping[str, Any], after: Mapping[str, Any]) -> Mapping[str, tuple[str, str]]:
    number = normalized(str(after["account_number"] or ""))
    if not number:
        organization_id = require_tenant_context().organization_id
        if Payment.all_objects.filter(
            organization_id=organization_id,
            status=PaymentStatus.REQUIRES_PAYMENT,
            method=PaymentMethod.TRANSFER,
        ).exists():
            return {
                "account_number": (
                    "Na ten rachunek czekają jeszcze wpłaty klientów.",
                    "transfer_account_in_use",
                )
            }
        if any(use(organization_id) for use in _uses):
            return {
                "account_number": (
                    "Z tego rachunku korzysta oferta opłacana przelewem. Najpierw zmień jej "
                    "sposób płatności.",
                    "transfer_account_in_use",
                )
            }
        return {}
    if not valid(number):
        return {
            "account_number": (
                "To nie jest poprawny numer rachunku. Wpisz 26 cyfr albo numer IBAN.",
                "invalid_account_number",
            )
        }
    if not str(after["account_holder"] or "").strip():
        return {
            "account_holder": ("Podaj, do kogo należy rachunek.", "required"),
        }
    return {}


CUSTOMER_PAYMENTS_AREA = SettingArea(
    key="customer-payments",
    title={"pl": "Płatności klientów", "en": "Customers' payments"},
    description={
        "pl": "Rachunek, na który klienci wpłacają przelewem.",
        "en": "The bank account your customers pay to by a transfer.",
    },
    order=65,
)

TRANSFER = SettingGroup(
    key="commerce.transfer",
    module="shared.commerce",
    title={"pl": "Rachunek do przelewów", "en": "Bank account for transfers"},
    description={
        "pl": "Klient, który ma zapłacić przelewem, dostaje ten rachunek razem z numerem "
        "zamówienia jako tytułem przelewu. Zmiana rachunku wymaga kodu z aplikacji "
        "uwierzytelniającej.",
        "en": "A customer who is to pay by a transfer gets this account with the order's "
        "number as the transfer's title. Changing the account needs a code from the "
        "authenticator app.",
    },
    permission=PAYMENTS_MANAGE,
    entitlement=COMMERCE_ENABLED,
    step_up_reason="commerce.transfer_account",
    area="customer-payments",
    check=_check,
    settings=(
        SettingSpec(
            key=HOLDER,
            type="text",
            default="",
            scopes=("organization",),
            product_default=False,
            # What a transfer's recipient line takes (two lines of 35).
            max_length=70,
            no_links=True,
            label={"pl": "Właściciel rachunku", "en": "Account holder"},
            help={
                "pl": "Nazwa firmy albo imię i nazwisko, tak jak w banku.",
                "en": "The company's or the person's name, as the bank has it.",
            },
            model_description="Who the company's bank account for customers' transfers "
            "belongs to, as customers read it in the transfer details.",
        ),
        SettingSpec(
            key=NUMBER,
            type="text",
            default="",
            scopes=("organization",),
            product_default=False,
            max_length=42,
            label={"pl": "Numer rachunku", "en": "Account number"},
            help={
                "pl": "26 cyfr albo numer IBAN. Pusty: klienci nie płacą przelewem.",
                "en": "26 digits or an IBAN. Empty: customers do not pay by a transfer.",
            },
            model_description="The number of the bank account customers pay to by a "
            "transfer: 26 digits (a Polish account) or an IBAN. Empty: no offer may ask "
            "for a transfer.",
        ),
        SettingSpec(
            key=BANK,
            type="text",
            default="",
            scopes=("organization",),
            product_default=False,
            max_length=80,
            no_links=True,
            label={"pl": "Bank (opcjonalnie)", "en": "Bank (optional)"},
            model_description="The bank's name shown beside the account, when the company "
            "wants it said.",
        ),
    ),
)


def register_transfer_settings() -> None:
    """From `CommerceConfig.ready`."""
    register_setting_area(CUSTOMER_PAYMENTS_AREA)
    register_setting_group(TRANSFER)
