"""The translation settings on the settings registry (ADR-078, R2b).

`translation.settings` is an entity group: its values live in this module's
`TranslationSettings` row, with its own endpoint, receipts, preview and
`translation.settings.update@1`; the registry declares the keys, checks the
profile's starting values (`settingsDefaults`) at start, lists them in the
schema with `api`, and resolves them through `read_explicit`.

`restrict` means the value in force is the strictest of the company's own,
the operator's override and the ceiling, which only this module knows; a
profile gives only the starting value, never a ceiling (ADR-069 pkt 12).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from saas_core.modules.core.organizations.api import SettingGroup, SettingSpec
from saas_core.modules.core.organizations.context import require_tenant_context

from .permissions import TRANSLATION_MANAGE

MODE = SettingSpec(
    key="translation.settings.mode",
    type="enum",
    default="automatic",
    scopes=("organization",),
    strategy="restrict",
    # Most permissive first: `restrict` picks the later one.
    values=(
        ("automatic", {"pl": "Automatycznie", "en": "Automatically"}),
        ("review", {"pl": "Po akceptacji", "en": "After approval"}),
    ),
    label={"pl": "Publikacja tłumaczeń", "en": "Publishing translations"},
    model_description="Whether AI translations go public at once (automatic) or wait for a "
    "person (review). The strictest of this, the operator's override and the deployment "
    "switch applies; legal documents always wait.",
    help={
        "pl": "Automatycznie: tłumaczenie wychodzi od razu. Po akceptacji: czeka na osobę. "
        "Dokumenty prawne zawsze czekają.",
        "en": "Automatically: a translation goes out at once. After approval: it waits for "
        "a person. Legal documents always wait.",
    },
)
AUTO_CHANGES = SettingSpec(
    key="translation.settings.auto_changes",
    type="bool",
    default=False,
    scopes=("organization",),
    # Turning it on is one person's consent, stored with who gave it
    # (ADR-069 pkt 14): a product cannot give it for them.
    product_default=False,
    label={"pl": "Tłumacz zmiany automatycznie", "en": "Translate changes automatically"},
    model_description="Refresh the translations of published content when it changes, within "
    "the monthly credit limit. Turning it on is the consent of the person who does it.",
    help={
        "pl": "Po zmianie opublikowanej treści jej tłumaczenia odświeżą się same, w "
        "miesięcznym limicie kredytów. Włączenie to zgoda osoby, która je włącza.",
        "en": "When published content changes, its translations refresh themselves within "
        "the monthly credit limit. Turning it on is the consent of whoever does it.",
    },
)
AUTO_MONTHLY_LIMIT = SettingSpec(
    key="translation.settings.auto_monthly_limit",
    type="int",
    default=100,
    scopes=("organization",),
    strategy="restrict",
    minimum=0,
    maximum=100_000,
    label={"pl": "Miesięczny limit automatu", "en": "Monthly limit of the automation"},
    model_description="Credits a month that translations without a click may spend; 0 turns "
    "the automation off. The operator may set a lower limit.",
    help={
        "pl": "Ile kredytów miesięcznie mogą wydać tłumaczenia bez kliknięcia. 0 wyłącza automat.",
        "en": "How many credits a month translations without a click may spend. 0 turns the "
        "automation off.",
    },
)
#: The operator's switch for the deployment, kept in `TranslationCeiling` and
#: set by `translation_ceiling`. Listed in the offer for the panel and the
#: assistant; not a group's key, so no profile may set it (organizations.E101).
CEILING = SettingSpec(
    key="translation.ceiling",
    type="enum",
    default="none",
    scopes=("platform",),
    strategy="restrict",
    values=(
        ("none", {"pl": "Bez ograniczeń", "en": "No limit"}),
        ("review", {"pl": "Wszystko po akceptacji", "en": "Everything after approval"}),
        ("off", {"pl": "Wyłączone", "en": "Off"}),
    ),
    label={"pl": "Wyłącznik tłumaczeń wdrożenia", "en": "Deployment translation switch"},
    model_description="The operator's switch for the whole deployment: none, review "
    "(everything waits for a person) or off. Read-only for companies.",
    help={
        "pl": "Ustawia operator poleceniem z powodem; obowiązuje każdą firmę.",
        "en": "Set by the operator with a reason; binds every company.",
    },
)

#: What a company sets through the API, in a stable order.
COMPANY_SETTINGS = (MODE, AUTO_CHANGES, AUTO_MONTHLY_LIMIT)
DECLARATIONS = {spec.key: spec for spec in (*COMPANY_SETTINGS, CEILING)}
MODE_VALUES = tuple(value for value, _ in MODE.values)


def _explicit() -> dict[str, Any]:
    """The company's own values in the current tenant, None where it has none."""
    from .models import TranslationSettings  # noqa: PLC0415 — models load after apps

    row = TranslationSettings.all_objects.filter(
        organization_id=require_tenant_context().organization_id
    ).first()
    if row is None:
        return {spec.field: None for spec in COMPANY_SETTINGS}
    return {
        MODE.field: row.mode or None,
        AUTO_CHANGES.field: row.auto_changes,
        AUTO_MONTHLY_LIMIT.field: row.auto_monthly_limit,
    }


SETTINGS = SettingGroup(
    key="translation.settings",
    module="shared.translation",
    title={"pl": "Tłumaczenia AI", "en": "AI translations"},
    description={
        "pl": "Czy tłumaczenia wychodzą od razu, czy czekają na osobę, i czy zmiany "
        "opublikowanych treści tłumaczą się same w miesięcznym limicie.",
        "en": "Whether translations go out at once or wait for a person, and whether "
        "changes to published content translate themselves within a monthly limit.",
    },
    permission=TRANSLATION_MANAGE,
    area="languages",
    api="/api/v1/translation/settings/",
    read_explicit=_explicit,
    settings=COMPANY_SETTINGS,
)

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


def profile_default(defaults: Mapping[str, Any], spec: SettingSpec) -> Any:
    """The profile's starting value for a key, else the code's."""
    return defaults.get(spec.key, spec.default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


#: The platform's own content (e.g. Puppily) is paid from the deployment's USD
#: budget, not credits; a job estimated above this waits for the operator's
#: `translation_confirm_job` (ADR-069 pkt 26). Class A: the environment until
#: the platform settings table.
PLATFORM_CONFIRM_USD_MICROS = int(_env_float("TRANSLATION_PLATFORM_CONFIRM_USD", 5.0) * 1_000_000)
