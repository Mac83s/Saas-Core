"""The policy the engine registers for content modules (ADR-069 pkt 12 and 30).

A module reads it on every AI write, so a stricter mode — a company switching
to review, the operator pausing a company, the deployment's switch — reaches
jobs already queued from their next item. The effective mode is the strictest
of the company's own (or the profile's starting value), the operator's
override for the company and the deployment ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings

from saas_core.content_protocol.policy import (
    REASON_OPERATOR_FORCED_REVIEW,
    TranslationPolicy,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.platform_workspace import is_platform_workspace

from .models import TranslationCeiling, TranslationOverride, TranslationSettings
from .settings_spec import MASS_PUBLICATION_CAP, MODE, profile_default, strictest

REASON_KILL_SWITCH = "kill_switch"
REASON_ORGANIZATION_PAUSED = "organization_paused"
REASON_PROCESSOR_NOT_LISTED = "processor_not_listed"


@dataclass(frozen=True, slots=True)
class EffectiveMode:
    mode: str
    reason: str | None
    # Where the value comes from: code, product, organization, operator, platform.
    source: str
    company_mode: str
    company_source: str


def ceiling_state() -> str:
    row = TranslationCeiling.objects.order_by("-created_at", "-id").first()
    return row.state if row is not None else "none"


def operator_override(organization_id: UUID) -> TranslationOverride | None:
    return (
        TranslationOverride.all_objects.filter(organization_id=organization_id)
        .order_by("-created_at", "-id")
        .first()
    )


def company_mode(organization_id: UUID) -> tuple[str, str]:
    row = TranslationSettings.all_objects.filter(organization_id=organization_id).first()
    if row is not None and row.mode:
        return row.mode, "organization"
    if MODE.key in settings.SETTINGS_DEFAULTS:
        return profile_default(settings.SETTINGS_DEFAULTS, MODE), "product"
    return MODE.default, "code"


def effective_mode(organization_id: UUID) -> EffectiveMode:
    own, own_source = company_mode(organization_id)
    # The platform's own workspace (Puppily's content) is the operator's content,
    # exempt from the processor listing (ADR-068 pkt 9).
    platform = is_platform_workspace(
        Organization.objects.filter(pk=organization_id).only("workspace_kind").first()
    )
    ceiling = ceiling_state()
    override = operator_override(organization_id)
    cap = override.mode_cap if override is not None else ""
    if ceiling == "off":
        return EffectiveMode("off", REASON_KILL_SWITCH, "platform", own, own_source)
    if not platform and not settings.MODEL_PORT_PROCESSOR_LISTED:
        return EffectiveMode("off", REASON_PROCESSOR_NOT_LISTED, "platform", own, own_source)
    if cap == "off":
        return EffectiveMode("off", REASON_ORGANIZATION_PAUSED, "operator", own, own_source)
    mode = strictest(own, "review" if ceiling == "review" else "automatic", cap or "automatic")
    if mode == own:
        return EffectiveMode(mode, None, own_source, own, own_source)
    source = "operator" if cap == "review" else "platform"
    return EffectiveMode(mode, REASON_OPERATOR_FORCED_REVIEW, source, own, own_source)


class EnginePolicy:
    """Registered from `AppConfig.ready`; read by content modules at write time."""

    def policy(self, *, organization_id: UUID) -> TranslationPolicy:
        effective = effective_mode(organization_id)
        return TranslationPolicy(
            mode=effective.mode,
            reason=effective.reason,
            mass_publication_cap=MASS_PUBLICATION_CAP,
        )


ENGINE_POLICY = EnginePolicy()
