"""The ceilings, in USD (ADR-068 pkt 7; owner answer 7 of 2026-10-02).

All below the deployment key's own monthly limit (USD 100), so ours trips
first and a cut-off key never stops every task at once. Defaults in code,
overridable by `MODEL_PORT_BUDGET_<NAME>` until the settings registry exists.
The assistant's three budgets are the assistant track's starting values of
2026-10-02, to be tuned on telemetry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Budgets:
    key_month_limit: float = 100.0
    platform_month: float = 80.0
    translation_month: float = 55.0
    translation_day: float = 6.0
    #: Share of the daily translation pool one company may take while another
    #: company within its share is waiting.
    translation_org_share: float = 0.25
    assistant_reserve_month: float = 25.0
    assistant_day: float = 4.0
    assistant_org_day: float = 2.0
    assistant_conversation: float = 1.5
    assistant_person_day: float = 1.5


def current_budgets() -> Budgets:
    defaults = Budgets()
    values: dict[str, float] = {}
    for name in Budgets.__dataclass_fields__:
        raw = os.environ.get(f"MODEL_PORT_BUDGET_{name.upper()}")
        values[name] = float(raw) if raw not in (None, "") else getattr(defaults, name)
    return Budgets(**values)


def problems(budgets: Budgets) -> list[str]:
    """What the system check refuses: ceilings that would let the key trip first."""
    found = []
    if budgets.platform_month > 0.8 * budgets.key_month_limit:
        found.append("Sufit platformy przekracza 80% limitu klucza OpenRouter.")
    if budgets.translation_month > budgets.platform_month:
        found.append("Sufit puli tłumaczeń przekracza sufit platformy.")
    if budgets.translation_day > budgets.translation_month:
        found.append("Dzienny sufit tłumaczeń przekracza miesięczny.")
    if budgets.assistant_reserve_month > budgets.platform_month:
        found.append("Rezerwa asystenta przekracza sufit platformy.")
    return found


def micros(usd: float) -> int:
    return int(round(usd * 1_000_000))
