"""The translation settings as named declarations (ADR-078, the interim rule in AGENTS.md).

Until the settings registry (phase R1) takes them over without a change to
the API or the commands, each setting a company or the operator could want
otherwise lives here, once: its key, value type, bounds, variants, default,
strategy and labels — and the API reads them from here, so the panel and the
assistant learn the allowed values and the defaults from the server.

`restrict` means the effective value is the strictest of the company's own,
the operator's override and the ceiling; a profile gives only the starting
value (`settingsDefaults`), never a ceiling (ADR-069 pkt 12).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SettingDeclaration:
    key: str
    kind: str  # "enum" | "bool" | "int"
    default: Any
    labels: Mapping[str, str]
    help: Mapping[str, str]
    scope: str = "organization"  # "organization" | "platform"
    strategy: str = "override"  # "override" | "restrict"
    # Enum values, most permissive first: `restrict` picks the later one.
    variants: tuple[str, ...] = ()
    variant_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    minimum: int | None = None
    maximum: int | None = None
    # What the setting does, in English, for the assistant.
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        """An entry of the settings registry's schema (ADR-078 pkt 11), as
        `organizations.options` and the booking offer options answer it."""
        return {
            "key": self.key,
            "type": self.kind,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "unit": None,
            "values": [
                {"value": value, "label": dict(self.variant_labels[value])}
                for value in self.variants
            ]
            or None,
            "default": self.default,
            "label": dict(self.labels),
            "help": dict(self.help),
            "description": self.description,
            "scopes": [self.scope],
            "depends_on": None,
        }


MODE = SettingDeclaration(
    key="translation.settings.mode",
    kind="enum",
    default="automatic",
    strategy="restrict",
    variants=("automatic", "review"),
    variant_labels={
        "automatic": {"pl": "Automatycznie", "en": "Automatically"},
        "review": {"pl": "Po akceptacji", "en": "After approval"},
    },
    labels={"pl": "Publikacja tłumaczeń", "en": "Publishing translations"},
    description="Whether AI translations go public at once (automatic) or wait for a person "
    "(review). The strictest of this, the operator's override and the deployment switch "
    "applies; legal documents always wait.",
    help={
        "pl": "Automatycznie: tłumaczenie wychodzi od razu. Po akceptacji: czeka na osobę. "
        "Dokumenty prawne zawsze czekają.",
        "en": "Automatically: a translation goes out at once. After approval: it waits for "
        "a person. Legal documents always wait.",
    },
)
AUTO_CHANGES = SettingDeclaration(
    key="translation.settings.auto_changes",
    kind="bool",
    default=False,
    labels={"pl": "Tłumacz zmiany automatycznie", "en": "Translate changes automatically"},
    description="Refresh the translations of published content when it changes, within the "
    "monthly credit limit. Turning it on is the consent of the person who does it.",
    help={
        "pl": "Po zmianie opublikowanej treści jej tłumaczenia odświeżą się same, w "
        "miesięcznym limicie kredytów. Włączenie to zgoda osoby, która je włącza.",
        "en": "When published content changes, its translations refresh themselves within "
        "the monthly credit limit. Turning it on is the consent of whoever does it.",
    },
)
AUTO_MONTHLY_LIMIT = SettingDeclaration(
    key="translation.settings.auto_monthly_limit",
    kind="int",
    default=100,
    strategy="restrict",
    minimum=0,
    maximum=100_000,
    labels={"pl": "Miesięczny limit automatu", "en": "Monthly limit of the automation"},
    description="Credits a month that translations without a click may spend; 0 turns the "
    "automation off. The operator may set a lower limit.",
    help={
        "pl": "Ile kredytów miesięcznie mogą wydać tłumaczenia bez kliknięcia. 0 wyłącza automat.",
        "en": "How many credits a month translations without a click may spend. 0 turns the "
        "automation off.",
    },
)
CEILING = SettingDeclaration(
    key="translation.ceiling",
    kind="enum",
    default="none",
    scope="platform",
    strategy="restrict",
    variants=("none", "review", "off"),
    variant_labels={
        "none": {"pl": "Bez ograniczeń", "en": "No limit"},
        "review": {"pl": "Wszystko po akceptacji", "en": "Everything after approval"},
        "off": {"pl": "Wyłączone", "en": "Off"},
    },
    labels={"pl": "Wyłącznik tłumaczeń wdrożenia", "en": "Deployment translation switch"},
    description="The operator's switch for the whole deployment: none, review (everything "
    "waits for a person) or off. Read-only for companies.",
    help={
        "pl": "Ustawia operator poleceniem z powodem; obowiązuje każdą firmę.",
        "en": "Set by the operator with a reason; binds every company.",
    },
)

#: What a company sets through the API, in a stable order.
COMPANY_SETTINGS = (MODE, AUTO_CHANGES, AUTO_MONTHLY_LIMIT)
DECLARATIONS = {declaration.key: declaration for declaration in (*COMPANY_SETTINGS, CEILING)}

#: Strictness of a publication mode, for `restrict`.
MODE_ORDER = ("automatic", "review", "off")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


#: Objects one job without a click may publish before the rest waits as one
#: `mass_publication` review item (ADR-069 pkt 16.7). Class A: the operator's
#: value from the environment until the platform settings table (pkt 30).
MASS_PUBLICATION_CAP = _env_int("TRANSLATION_MASS_PUBLICATION_CAP", 20)


def strictest(*modes: str) -> str:
    return max(modes, key=MODE_ORDER.index)


def profile_default(defaults: Mapping[str, Any], declaration: SettingDeclaration) -> Any:
    """The profile's starting value for a key, else the code's."""
    return defaults.get(declaration.key, declaration.default)
