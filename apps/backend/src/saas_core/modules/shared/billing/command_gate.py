"""The plan decides whether a channel may act for a company at all (ADR-076 §1, §8).

Registered as the command executor's `features` gate: on every call, the
channel's feature (`assistant.text.enabled`), the command's extra features and
its entitlement, each through `decide_feature` like any panel write. No service
knows `assistant.*`; a downgrade during a conversation stops the next call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saas_core.modules.core.organizations.api import CHANNEL_FEATURES, CommandSpec, Preview
from saas_core.modules.core.organizations.context import TenantContext

from .decisions import FeatureOperation, decide_feature


def plan_features(
    spec: CommandSpec,
    context: TenantContext,
    arguments: Mapping[str, Any],
    preview: Preview | None,
) -> str | None:
    channel = CHANNEL_FEATURES.get(context.acting_via)
    if channel is None:
        return "channel_unavailable"
    operation = FeatureOperation.READ if spec.risk == "read" else FeatureOperation.WRITE
    entitlement = (spec.entitlement,) if spec.entitlement else ()
    for key in (*channel, *sorted(spec.extra_features), *entitlement):
        decision = decide_feature(key, operation=operation)
        if not decision.allowed:
            return str(decision.reason)
    return None
