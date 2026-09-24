"""Public authorization and quota API for Shared and Vertical modules."""

from .authorization import EntitlementRequired, authorize_entitled
from .credits import commit_credits, operation_cost, release_credits, reserve_credits
from .decisions import FeatureOperation, decide_feature, decide_quota
from .quotas import (
    QuotaExceeded,
    QuotaReservationConflict,
    QuotaReservationExpired,
    QuotaUnavailable,
    adjust_quota_reservation,
    commit_quota,
    consume_quota,
    extend_quota_reservation,
    release_committed_quota,
    release_quota,
    reserve_quota,
)
from .tenant_scope import billing_organization_ids

__all__ = [
    "EntitlementRequired",
    "FeatureOperation",
    "QuotaExceeded",
    "QuotaReservationConflict",
    "QuotaReservationExpired",
    "QuotaUnavailable",
    "adjust_quota_reservation",
    "authorize_entitled",
    "commit_quota",
    "decide_feature",
    "decide_quota",
    "consume_quota",
    "extend_quota_reservation",
    "release_committed_quota",
    "release_quota",
    "reserve_quota",
    "reserve_credits",
    "commit_credits",
    "release_credits",
    "operation_cost",
    "billing_organization_ids",
]
