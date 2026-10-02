"""The allowed values behind the company's basic settings, and the registry's
types and units (ADR-078). The settings themselves are declared in
`basic_settings.py`; `GET /api/v1/organizations/options/` serves them."""

from __future__ import annotations

#: The registry's types and units (ADR-078 pkt 2) as an option entry names
#: them — one enum name each in the contract, for every module's options.
SETTING_TYPES = ("int", "decimal", "bool", "enum", "text", "date")
SETTING_UNITS = ("minute", "hour", "day", "percent")
SETTING_STRATEGIES = ("override", "restrict")

#: The currencies a company keeps its prices and stock values in (owner
#: decision 16, ADR-073 §8). A platform value once the platform settings exist.
CURRENCIES: tuple[tuple[str, dict[str, str]], ...] = (
    ("PLN", {"pl": "Złoty polski", "en": "Polish złoty"}),
    ("EUR", {"pl": "Euro", "en": "Euro"}),
    ("USD", {"pl": "Dolar amerykański", "en": "US dollar"}),
)
DEFAULT_CURRENCY = "PLN"

PANEL_LOCALES = {
    "pl": {"pl": "Polski", "en": "Polish"},
    "en": {"pl": "Angielski", "en": "English"},
}


def currency_codes() -> tuple[str, ...]:
    return tuple(code for code, _ in CURRENCIES)
