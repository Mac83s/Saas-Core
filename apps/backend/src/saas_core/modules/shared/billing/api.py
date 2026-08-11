"""Public authorization and quota API for Shared and Vertical modules."""

from .authorization import EntitlementRequired, authorize_entitled
from .decisions import FeatureOperation
from .quotas import (
    QuotaExceeded,
    QuotaUnavailable,
    adjust_quota_reservation,
    commit_quota,
    consume_quota,
    extend_quota_reservation,
    release_committed_quota,
    release_quota,
    reserve_quota,
)

__all__ = [
    "EntitlementRequired",
    "FeatureOperation",
    "QuotaExceeded",
    "QuotaUnavailable",
    "adjust_quota_reservation",
    "authorize_entitled",
    "commit_quota",
    "consume_quota",
    "extend_quota_reservation",
    "release_committed_quota",
    "release_quota",
    "reserve_quota",
]
