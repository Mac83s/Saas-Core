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

from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from saas_core.modules.core.organizations.api import SettingArea, SettingGroup, SettingSpec
from saas_core.modules.core.organizations.context import require_tenant_context

from .permissions import TRANSLATION_MANAGE

if TYPE_CHECKING:
    from .quality import QualityThresholds

MODE = SettingSpec(
    key="translation.settings.mode",
    type="enum",
    default="automatic",
    # The platform's value is the default for companies that chose none and
    # whose product names none (ADR-078 pkt 3; TL22).
    scopes=("platform", "organization"),
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
    scopes=("platform", "organization"),
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


LANGUAGES_AREA = SettingArea(
    key="languages",
    title={"pl": "Języki", "en": "Languages"},
    description={
        "pl": "Języki strony i wizytówki oraz jak powstają tłumaczenia.",
        "en": "The languages of the site and the business card, and how translations are made.",
    },
    order=20,
    page="/panel/settings/languages",
)


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

#: The price of `translation.characters` (TL22; answer 54a of 03.10): credits
#: for 1,000 visible source characters in one target language. Class A — only
#: the platform sets it (`platform_setting`, later the „Platforma” panel);
#: billing reads it through `register_credit_cost`, and a reservation keeps
#: the price it was made at, so a change never rewrites a charge.
PRICE = SettingSpec(
    key="translation.pricing.characters",
    type="int",
    default=1,
    minimum=0,
    maximum=100,
    scopes=("platform",),
    label={
        "pl": "Cena tłumaczenia (kredyty za 1000 znaków)",
        "en": "Translation price (credits per 1,000 characters)",
    },
    model_description="Credits a company pays for 1,000 visible source characters "
    "translated into one target language. Applies to new quotes; reservations keep "
    "their price.",
    help={
        "pl": "Ile kredytów kosztuje 1000 znaków tekstu źródłowego w jednym języku. Dotyczy "
        "nowych wycen; złożone zlecenia zachowują swoją cenę.",
        "en": "Credits for 1,000 characters of source text in one language. Applies to new "
        "quotes; orders already placed keep their price.",
    },
)

PRICING = SettingGroup(
    key="translation.pricing",
    module="shared.translation",
    title={"pl": "Cena tłumaczeń AI", "en": "AI translation price"},
    description={
        "pl": "Ile kredytów płacą firmy za tłumaczenie AI.",
        "en": "How many credits companies pay for AI translation.",
    },
    permission=TRANSLATION_MANAGE,
    area="ai",
    settings=(PRICE,),
)

#: Strictness of a publication mode, for `restrict`.
MODE_ORDER = ("automatic", "review", "off")


def strictest(*modes: str) -> str:
    return max(modes, key=MODE_ORDER.index)


# --- The engine's own values (TL22) ------------------------------------------------
#
# Class A: only the platform sets them, in the „Platforma” panel or with
# `platform_setting`. The waits and the quality thresholds are operational
# tuning (operator level 1); what changes money or what goes out stays at 2.
# Readers below ask at use time, so a change needs no restart.

DEMAND_WAIT_MINUTES = SettingSpec(
    key="translation.engine.demand_wait_minutes",
    type="int",
    default=5,
    minimum=1,
    maximum=60,
    unit="minute",
    scopes=("platform",),
    operator_level=1,
    label={
        "pl": "Odczekanie po zmianie (minuty)",
        "en": "Wait after a change (minutes)",
    },
    model_description="Minutes a published change waits for the next one before the "
    "automation starts its translation job; each further change restarts the wait.",
    help={
        "pl": "Ile minut automat czeka po zmianie treści, zanim zleci tłumaczenie. Każda "
        "kolejna zmiana tego samego obiektu liczy czas od nowa.",
        "en": "How many minutes the automation waits after a content change before it "
        "orders the translation. Each further change of the same object restarts the wait.",
    },
)

DEMAND_MAX_WAIT_MINUTES = SettingSpec(
    key="translation.engine.demand_max_wait_minutes",
    type="int",
    default=30,
    minimum=5,
    maximum=240,
    unit="minute",
    scopes=("platform",),
    operator_level=1,
    label={
        "pl": "Najdłuższe odczekanie (minuty)",
        "en": "Longest wait (minutes)",
    },
    model_description="However often an object changes, its automatic translation job "
    "starts at most this many minutes after the first change.",
    help={
        "pl": "Choćby obiekt zmieniał się co chwilę, tłumaczenie ruszy najpóźniej po tylu "
        "minutach od pierwszej zmiany.",
        "en": "However often an object changes, its translation starts at most this many "
        "minutes after the first change.",
    },
)

MASS_PUBLICATION_CAP = SettingSpec(
    key="translation.engine.mass_publication_cap",
    type="int",
    default=20,
    minimum=1,
    maximum=1000,
    scopes=("platform",),
    operator_level=1,
    platform_env="TRANSLATION_MASS_PUBLICATION_CAP",
    label={
        "pl": "Próg publikacji masowej (obiekty)",
        "en": "Mass publication threshold (objects)",
    },
    model_description="Objects one job without a click may publish; from this many on, "
    "the rest waits as one review item for a person (ADR-069 pkt 16.7).",
    help={
        "pl": "Ile obiektów jedno zlecenie bez kliknięcia może opublikować samo. Powyżej "
        "progu reszta czeka na decyzję osoby jako jedna pozycja przeglądu.",
        "en": "How many objects one job without a click may publish by itself. Above the "
        "threshold the rest waits for a person as one review item.",
    },
)

LEFTOVER_THRESHOLD_PERCENT = SettingSpec(
    key="translation.engine.leftover_threshold_percent",
    type="int",
    default=30,
    minimum=5,
    maximum=100,
    unit="percent",
    scopes=("platform",),
    operator_level=1,
    label={
        "pl": "Kontrola jakości: słowa źródła w tłumaczeniu (%)",
        "en": "Quality check: source words left in a translation (%)",
    },
    model_description="A translated fragment is flagged for a person when at least this "
    "share of its words are common words copied from the source.",
    help={
        "pl": "Fragment trafia do przeglądu, gdy co najmniej taki odsetek jego słów to "
        "nieprzetłumaczone słowa źródła.",
        "en": "A fragment goes to review when at least this share of its words are "
        "untranslated words of the source.",
    },
)

LENGTH_RATIO_MAX_PERCENT = SettingSpec(
    key="translation.engine.length_ratio_max_percent",
    type="int",
    default=250,
    minimum=110,
    maximum=1000,
    unit="percent",
    scopes=("platform",),
    operator_level=1,
    label={
        "pl": "Kontrola jakości: długość tłumaczenia wobec źródła (%)",
        "en": "Quality check: a translation's length against its source (%)",
    },
    model_description="A translated fragment is flagged for a person when it is longer "
    "than this percentage of its source.",
    help={
        "pl": "Fragment trafia do przeglądu, gdy jest dłuższy niż taki procent długości "
        "źródła (250 = dwa i pół raza).",
        "en": "A fragment goes to review when it is longer than this percentage of its "
        "source (250 = two and a half times).",
    },
)

#: The platform's own content (e.g. Puppily) is paid from the deployment's USD
#: budget, not credits; a job estimated above this waits for the operator's
#: `translation_confirm_job` (ADR-069 pkt 26).
PLATFORM_CONFIRM_USD = SettingSpec(
    key="translation.engine.platform_confirm_usd",
    type="int",
    default=5,
    minimum=0,
    maximum=1000,
    scopes=("platform",),
    platform_env="TRANSLATION_PLATFORM_CONFIRM_USD",
    label={
        "pl": "Treści platformy: zlecenie czeka na potwierdzenie powyżej (USD)",
        "en": "Platform content: a job waits for confirmation above (USD)",
    },
    model_description="A translation job of the platform's own content whose estimated "
    "cost is above this many US dollars waits for an operator's confirmation.",
    help={
        "pl": "Zlecenie tłumaczenia treści samej platformy, którego szacowany koszt "
        "przekracza tę kwotę, czeka na potwierdzenie operatora.",
        "en": "A translation job of the platform's own content whose estimated cost is "
        "above this amount waits for an operator's confirmation.",
    },
)


def _waits_in_order(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> Mapping[str, tuple[str, str]]:
    """The longest wait is never below the wait: refused at the change, on
    the key the operator was changing, not corrected at read."""
    wait, longest = DEMAND_WAIT_MINUTES.field, DEMAND_MAX_WAIT_MINUTES.field
    if after[longest] >= after[wait]:
        return {}
    if after[wait] != before[wait]:
        return {
            wait: (
                "Odczekanie nie może być dłuższe niż najdłuższe odczekanie "
                f"({after[longest]} min).",
                "above_longest_wait",
            )
        }
    return {
        longest: (
            f"Najdłuższe odczekanie nie może być krótsze niż odczekanie ({after[wait]} min).",
            "below_wait",
        )
    }


ENGINE = SettingGroup(
    key="translation.engine",
    module="shared.translation",
    title={"pl": "Silnik tłumaczeń", "en": "Translation engine"},
    description={
        "pl": "Kiedy automat rusza, co zatrzymuje kontrola jakości i od jakiej kwoty "
        "zlecenie treści platformy czeka na potwierdzenie.",
        "en": "When the automation starts, what the quality check holds back, and above "
        "what amount a job of the platform's content waits for confirmation.",
    },
    permission=TRANSLATION_MANAGE,
    area="ai",
    platform_check=_waits_in_order,
    settings=(
        DEMAND_WAIT_MINUTES,
        DEMAND_MAX_WAIT_MINUTES,
        MASS_PUBLICATION_CAP,
        LEFTOVER_THRESHOLD_PERCENT,
        LENGTH_RATIO_MAX_PERCENT,
        PLATFORM_CONFIRM_USD,
    ),
)


def _platform(spec: SettingSpec) -> int:
    from saas_core.modules.core.organizations.api import platform_setting  # noqa: PLC0415

    return int(platform_setting(spec.key))


def demand_wait() -> timedelta:
    return timedelta(minutes=_platform(DEMAND_WAIT_MINUTES))


def demand_max_wait() -> timedelta:
    return timedelta(minutes=_platform(DEMAND_MAX_WAIT_MINUTES))


def mass_publication_cap() -> int:
    return _platform(MASS_PUBLICATION_CAP)


def quality_thresholds() -> QualityThresholds:
    """What the soft checks flag at, as the platform has it now."""
    from .quality import QualityThresholds  # noqa: PLC0415 — quality imports the glossary's models

    return QualityThresholds(
        leftover_share=_platform(LEFTOVER_THRESHOLD_PERCENT) / 100,
        length_ratio=_platform(LENGTH_RATIO_MAX_PERCENT) / 100,
    )


def platform_confirm_usd_micros() -> int:
    return _platform(PLATFORM_CONFIRM_USD) * 1_000_000
