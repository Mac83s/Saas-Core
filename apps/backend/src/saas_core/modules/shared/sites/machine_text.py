"""The mark on text a machine wrote (ADR-071 pkt 17; TL19b).

A language version with AI text always says so to machines: the page's
payload names the IPTC digital source type, and the structured data and the
head carry it. Whether a visitor also reads a notice is the operator's
switch, off by default, and even then only on a version no person stands
behind yet (`origin.reviewed` false) — an accepted translation is the
company's own text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saas_core.modules.core.organizations.api import (
    SettingArea,
    SettingGroup,
    SettingSpec,
    platform_setting,
    register_setting_area,
    register_setting_group,
)

from .permissions import SITE_CONTENT_EDIT

#: IPTC's digital source types (the vocabulary schema.org's `digitalSourceType`
#: takes): text a trained model wrote, and text a person and a model wrote.
IPTC_AI = "https://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
IPTC_MIXED = "https://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"

MACHINE_NOTICE = SettingSpec(
    key="sites.translation.machine_notice",
    type="bool",
    default=False,
    scopes=("platform",),
    label={
        "pl": "Widoczna notka o tłumaczeniu automatycznym",
        "en": "Visible notice on automatic translations",
    },
    model_description="Whether a visitor of a company's site reads a notice on a language "
    "version translated by AI that no person has accepted yet. The machine-readable mark "
    "(structured data and head) is always there, whatever this switch says.",
    help={
        "pl": "Czy gość strony firmy widzi notkę na wersji językowej przetłumaczonej przez "
        "AI, której nikt jeszcze nie zaakceptował. Znacznik dla wyszukiwarek jest zawsze, "
        "niezależnie od tego przełącznika.",
        "en": "Whether a visitor of a company's site sees a notice on a language version "
        "translated by AI that nobody has accepted yet. The mark for search engines is "
        "always there, whatever this switch says.",
    },
)

#: The sites' own platform keys. An area of this module: products compose the
#: sites without the model port, whose "ai" area would not exist there.
PLATFORM_AREA = SettingArea(
    key="sites-platform",
    title={"pl": "Strony firm", "en": "Company sites"},
    description={
        "pl": "Co platforma ustawia dla stron wszystkich firm.",
        "en": "What the platform sets for every company's site.",
    },
    # After every company area and the "ai" area: the „Platforma” page lists
    # areas in registry order, platform-only ones last.
    order=95,
)

TRANSLATION = SettingGroup(
    key="sites.translation",
    module="shared.sites",
    title={"pl": "Tłumaczenia na stronach firm", "en": "Translations on company sites"},
    description={
        "pl": "Jak strony firm mówią gościom, że tekst przetłumaczyła maszyna.",
        "en": "How company sites tell visitors that a machine translated the text.",
    },
    # A platform group: no company writes it; the registry only requires that
    # a composed module declares the permission.
    permission=SITE_CONTENT_EDIT,
    area=PLATFORM_AREA.key,
    settings=(MACHINE_NOTICE,),
)


def register_machine_text_settings() -> None:
    register_setting_area(PLATFORM_AREA)
    register_setting_group(TRANSLATION)


def has_machine_text(origin: Mapping[str, Any] | None) -> bool:
    """Whether the version carries text a model wrote. Snapshots from before
    the `machine` key say only how the version came to be, so "mixed" counts."""
    if not isinstance(origin, Mapping):
        return False
    if "machine" in origin:
        return bool(origin["machine"])
    return origin.get("origin") in ("ai", "mixed")


def machine_text(origin: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """What the page says about a version with AI text; None for a person's."""
    if not has_machine_text(origin):
        return None
    assert origin is not None
    reviewed = bool(origin.get("reviewed"))
    return {
        "source_type": IPTC_AI if origin.get("origin") == "ai" else IPTC_MIXED,
        "reviewed": reviewed,
        # The visible notice: the operator's switch, and nobody behind the text.
        "notice": not reviewed and bool(platform_setting(MACHINE_NOTICE.key)),
    }
