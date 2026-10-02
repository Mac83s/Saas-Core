"""The plan's limit on the company's languages, for Core's service (ADR-071 pkt 7)."""

from saas_core.modules.core.organizations.api import PublicLocalesLimit

from .decisions import DecisionReason, FeatureOperation, decide_quota

PUBLIC_LOCALES_ADDITIONAL_MAX = "public_locales.additional.max"


def public_locales_limit() -> PublicLocalesLimit:
    """Languages beyond the first the plan allows. A plan without the number
    has no limit; any other reason the number is not there — no plan yet, a
    blocked, expired or read-only subscription — refuses adding with it."""
    decision = decide_quota(PUBLIC_LOCALES_ADDITIONAL_MAX, operation=FeatureOperation.WRITE)
    if decision.available:
        return PublicLocalesLimit(allowed=True, additional_max=decision.value)
    if decision.reason == DecisionReason.QUOTA_MISSING:
        return PublicLocalesLimit(allowed=True)
    return PublicLocalesLimit(allowed=False, reason=str(decision.reason))
