from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.context import TenantContext

from .decisions import FeatureDecision, FeatureOperation, decide_feature


class EntitlementRequired(PermissionDenied):
    default_detail = "Plan organizacji nie pozwala na tę operację."
    default_code = "entitlement_required"

    def __init__(self, decision: FeatureDecision) -> None:
        self.decision = decision
        super().__init__(code=self.default_code)


def authorize_entitled(
    permission: str,
    feature_key: str,
    *,
    operation: FeatureOperation = FeatureOperation.WRITE,
) -> TenantContext:
    context = authorize(permission)
    decision = decide_feature(feature_key, operation=operation)
    if not decision.allowed:
        raise EntitlementRequired(decision)
    return context
