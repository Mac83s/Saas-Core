"""What a company may choose for its basic settings, as the API offers it.

Until the settings registry exists (ADR-078 pkt 16), a rule lives in one named
constant of its module and reaches the panel and the assistant through the
API, never through a list in a form. Each entry has the shape of an entry of
the registry's schema, so R1 moves these into declarations and
`GET /api/v1/organizations/options/` keeps answering the same.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

#: The registry's types and units (ADR-078 pkt 2) as an option entry names
#: them — one enum name each in the contract, for every module's options.
SETTING_TYPES = ("int", "decimal", "bool", "enum", "text", "date")
SETTING_UNITS = ("minute", "hour", "day", "percent")

#: The currencies a company keeps its prices and stock values in (owner
#: decision 16, ADR-073 §8). A platform value once the platform settings exist.
CURRENCIES: tuple[tuple[str, dict[str, str]], ...] = (
    ("PLN", {"pl": "Złoty polski", "en": "Polish złoty"}),
    ("EUR", {"pl": "Euro", "en": "Euro"}),
    ("USD", {"pl": "Dolar amerykański", "en": "US dollar"}),
)
DEFAULT_CURRENCY = "PLN"

_PANEL_LOCALES = {
    "pl": {"pl": "Polski", "en": "Polish"},
    "en": {"pl": "Angielski", "en": "English"},
}


def currency_codes() -> tuple[str, ...]:
    return tuple(code for code, _ in CURRENCIES)


def organization_options() -> dict[str, Any]:
    return {
        "keys": [
            _enum(
                "organization.currency",
                list(CURRENCIES),
                default=DEFAULT_CURRENCY,
                label={"pl": "Waluta", "en": "Currency"},
                help_text={
                    "pl": "Waluta cen i wyceny magazynu. Pozycja magazynu zachowuje walutę, "
                    "w której ją założono.",
                    "en": "The currency of prices and stock values. A stock item keeps the "
                    "currency it was created in.",
                },
                description="The ISO 4217 currency the company keeps its prices and stock "
                "values in. A stock item keeps the currency it was created in.",
            ),
            _enum(
                "organization.default_locale",
                [(code, _PANEL_LOCALES[code]) for code in settings.APP_LOCALES],
                default="pl",
                label={"pl": "Język panelu", "en": "Panel language"},
                help_text={
                    "pl": "Język panelu i e-maili do zespołu, gdy osoba nie wybrała swojego.",
                    "en": "The language of the panel and of e-mails to the team when a "
                    "person has not chosen their own.",
                },
                description="The language of the panel and of e-mails to the team (pl or en); "
                "not the language of the company's customers.",
            ),
        ]
    }


def _enum(
    key: str,
    values: list[tuple[str, dict[str, str]]],
    *,
    default: str,
    label: dict[str, str],
    help_text: dict[str, str],
    description: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "type": "enum",
        "minimum": None,
        "maximum": None,
        "unit": None,
        "values": [{"value": value, "label": dict(names)} for value, names in values],
        "default": default,
        "label": label,
        "help": help_text,
        "description": description,
        "scopes": ["organization"],
        "depends_on": None,
    }
