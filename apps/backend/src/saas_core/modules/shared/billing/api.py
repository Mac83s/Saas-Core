"""Public authorization and quota API for Shared and Vertical modules."""

from .authorization import EntitlementRequired, authorize_entitled
from .decisions import FeatureOperation
from .quotas import QuotaExceeded, QuotaUnavailable, consume_quota, reserve_quota

__all__ = [
    "EntitlementRequired",
    "FeatureOperation",
    "QuotaExceeded",
    "QuotaUnavailable",
    "authorize_entitled",
    "consume_quota",
    "reserve_quota",
]
