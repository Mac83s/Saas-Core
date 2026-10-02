"""Whether the plan lets a company read or change a settings group (ADR-078 pkt 5).

Registered in core's settings service: the group names a feature, and the same
`decide_feature` as every panel write answers. A refusal leaves the company's
values stored; the schema shows the group locked with the reason.
"""

from __future__ import annotations

from .decisions import FeatureOperation, decide_feature


def settings_feature(feature_key: str, write: bool) -> str | None:
    decision = decide_feature(
        feature_key, operation=FeatureOperation.WRITE if write else FeatureOperation.READ
    )
    return None if decision.allowed else str(decision.reason)
