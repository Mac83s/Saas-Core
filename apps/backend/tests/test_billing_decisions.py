from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.authorization import OrganizationPermissionDenied
from saas_core.modules.core.organizations.context import (
    MissingTenantContext,
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing.authorization import (
    EntitlementRequired,
    authorize_entitled,
)
from saas_core.modules.shared.billing.decisions import (
    DecisionReason,
    FeatureOperation,
    can,
    decide_feature,
    decide_quota,
    limit,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    PlanVersion,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db


def organization(slug: str) -> Organization:
    return Organization.objects.create(name=slug, slug=slug)


def context(tenant: Organization, *, permissions: frozenset[str]) -> TenantContext:
    user = User.objects.create_user(email=f"{tenant.slug}@example.com")
    return TenantContext(
        organization_id=tenant.id,
        membership_id=uuid.uuid7(),
        actor_id=user.id,
        role_key="owner" if BILLING_MANAGE in permissions else "viewer",
        permissions=permissions,
    )


def snapshot(
    tenant: Organization,
    *,
    access_mode: AccessMode = AccessMode.FULL,
    booking: bool = True,
    effective_until=None,
) -> EntitlementSnapshot:
    version = PlanVersion.objects.get(plan__key="starter", version=1)
    return EntitlementSnapshot.all_objects.create(
        organization=tenant,
        plan_version=version,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=access_mode,
        features={"booking.enabled": booking},
        quotas={"appointments.monthly": 1_000},
        sources={
            "booking.enabled": {"kind": "plan", "ref": "starter:v1"},
            "appointments.monthly": {"kind": "plan", "ref": "starter:v1"},
        },
        effective_until=effective_until,
        version=7,
    )


def test_feature_decision_is_explainable_and_uses_local_snapshot() -> None:
    tenant = organization("decision-acme")
    stored = snapshot(tenant)

    with activate_tenant_context(context(tenant, permissions=frozenset({BILLING_MANAGE}))):
        decision = decide_feature("booking.enabled")

    assert decision.allowed is True
    assert decision.reason == DecisionReason.ALLOWED
    assert decision.evidence.snapshot_id == str(stored.id)
    assert decision.evidence.snapshot_version == 7
    assert decision.evidence.source == {"kind": "plan", "ref": "starter:v1"}


def test_missing_snapshot_and_unknown_keys_fail_closed() -> None:
    tenant = organization("no-entitlements")

    with activate_tenant_context(context(tenant, permissions=frozenset())):
        missing = decide_feature("booking.enabled")
        unknown = decide_quota("unknown.monthly")

    assert missing.reason == DecisionReason.SNAPSHOT_MISSING
    assert missing.allowed is False
    assert unknown.reason == DecisionReason.SNAPSHOT_MISSING
    assert unknown.value == 0


def test_read_only_allows_reads_but_denies_mutations() -> None:
    tenant = organization("read-only-acme")
    snapshot(tenant, access_mode=AccessMode.READ_ONLY)

    with activate_tenant_context(context(tenant, permissions=frozenset())):
        assert can("booking.enabled", operation=FeatureOperation.READ) is True
        write = decide_feature("booking.enabled", operation=FeatureOperation.WRITE)
        quota = decide_quota("appointments.monthly")

    assert write.allowed is False
    assert write.reason == DecisionReason.READ_ONLY
    assert quota.available is True
    assert quota.value == 1_000


@pytest.mark.parametrize("access_mode", [AccessMode.FULL, AccessMode.BLOCKED])
def test_disabled_or_blocked_feature_is_denied(access_mode: AccessMode) -> None:
    tenant = organization(f"denied-{access_mode}")
    snapshot(tenant, access_mode=access_mode, booking=False)

    with activate_tenant_context(context(tenant, permissions=frozenset())):
        decision = decide_feature("booking.enabled")

    expected = (
        DecisionReason.ACCESS_BLOCKED
        if access_mode == AccessMode.BLOCKED
        else DecisionReason.FEATURE_DISABLED
    )
    assert decision.allowed is False
    assert decision.reason == expected


def test_expired_snapshot_fails_closed() -> None:
    tenant = organization("expired-acme")
    snapshot(tenant, effective_until=timezone.now() - timedelta(seconds=1))

    with activate_tenant_context(context(tenant, permissions=frozenset())):
        decision = decide_feature("booking.enabled")
        quota = decide_quota("appointments.monthly")
        effective_limit = limit("appointments.monthly")

    assert decision.reason == DecisionReason.SNAPSHOT_EXPIRED
    assert quota.reason == DecisionReason.SNAPSHOT_EXPIRED
    assert effective_limit == 0


def test_quota_returns_effective_value_and_missing_quota_returns_zero() -> None:
    tenant = organization("quota-acme")
    snapshot(tenant)

    with activate_tenant_context(context(tenant, permissions=frozenset())):
        available = decide_quota("appointments.monthly")
        missing = decide_quota("storage.bytes")
        unknown_quota = decide_quota("unknown.monthly")
        unknown_feature = decide_feature("unknown.enabled")
        effective_limit = limit("appointments.monthly")

    assert available.available is True
    assert available.value == 1_000
    assert effective_limit == 1_000
    assert missing.available is False
    assert missing.reason == DecisionReason.QUOTA_MISSING
    assert missing.value == 0
    assert unknown_quota.reason == DecisionReason.UNKNOWN_QUOTA
    assert unknown_feature.reason == DecisionReason.UNKNOWN_FEATURE


def test_rbac_and_entitlements_are_independent_decisions() -> None:
    tenant = organization("authz-acme")
    snapshot(tenant)

    with (
        activate_tenant_context(context(tenant, permissions=frozenset())),
        pytest.raises(OrganizationPermissionDenied),
    ):
        authorize_entitled(BILLING_MANAGE, "booking.enabled")

    tenant_without_feature = organization("no-feature-acme")
    snapshot(tenant_without_feature, booking=False)
    with (
        activate_tenant_context(
            context(tenant_without_feature, permissions=frozenset({BILLING_MANAGE}))
        ),
        pytest.raises(EntitlementRequired) as raised,
    ):
        authorize_entitled(BILLING_MANAGE, "booking.enabled")

    assert raised.value.decision.reason == DecisionReason.FEATURE_DISABLED


def test_decisions_require_tenant_context_before_catalog_lookup() -> None:
    with pytest.raises(MissingTenantContext):
        decide_feature("unknown.enabled")
