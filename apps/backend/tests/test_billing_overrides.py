from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from saas_core.modules.core.identity.models import User, UserStatus
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.billing.decisions import (
    DecisionReason,
    decide_feature,
    decide_quota,
)
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementGrant,
    EntitlementSnapshot,
    PlanVersion,
    StripePriceMapping,
    SubscriptionState,
)
from saas_core.modules.shared.billing.overrides import (
    BillingOperatorRequired,
    OverrideIdempotencyConflict,
    OverrideTargetConflict,
    create_entitlement_override,
    expire_entitlement_overrides,
    revoke_entitlement_override,
)
from saas_core.modules.shared.billing.snapshots import update_entitlement_snapshot

pytestmark = pytest.mark.django_db


def setup_tenant(slug: str) -> tuple[Organization, User, TenantContext]:
    organization = Organization.objects.create(name=slug, slug=slug)
    actor = User.objects.create_user(
        email=f"{slug}@example.com",
        status=UserStatus.ACTIVE,
        is_staff=True,
    )
    context = TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="operator",
        permissions=frozenset(),
    )
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id=f"prod_{slug}",
        stripe_price_id=f"price_{slug}",
    )
    update_entitlement_snapshot(
        organization,
        mapping,
        state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        effective_until=None,
    )
    return organization, actor, context


def test_feature_override_is_idempotent_audited_and_explainable() -> None:
    organization, actor, context = setup_tenant("override-feature")
    starts_at = timezone.now()
    expires_at = starts_at + timedelta(hours=1)

    with activate_tenant_context(context):
        first = create_entitlement_override(
            actor=actor,
            feature_key="booking.enabled",
            enabled=False,
            reason="Incydent bezpieczeństwa INC-42",
            idempotency_key="support:INC-42:disable-booking",
            valid_from=starts_at,
            expires_at=expires_at,
        )
        repeated = create_entitlement_override(
            actor=actor,
            feature_key="booking.enabled",
            enabled=False,
            reason="Incydent bezpieczeństwa INC-42",
            idempotency_key="support:INC-42:disable-booking",
            valid_from=starts_at,
            expires_at=expires_at,
        )
        decision = decide_feature("booking.enabled")

    assert repeated == first
    assert EntitlementGrant.all_objects.filter(organization=organization).count() == 1
    assert decision.allowed is False
    assert decision.reason == DecisionReason.FEATURE_DISABLED
    assert decision.evidence.source["kind"] == "override"
    assert decision.evidence.source["reason"] == "Incydent bezpieczeństwa INC-42"
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action=OrganizationAuditAction.BILLING_OVERRIDE_CREATED,
    )
    assert audit.actor_user == actor
    assert audit.target_id == first.id
    assert audit.metadata["target"] == "booking.enabled"


def test_expired_override_falls_back_locally_before_worker_cleanup() -> None:
    organization, actor, context = setup_tenant("override-expiry")
    starts_at = timezone.now()
    expires_at = starts_at + timedelta(minutes=5)
    with activate_tenant_context(context):
        grant = create_entitlement_override(
            actor=actor,
            quota_key="appointments.monthly",
            limit_value=2_000,
            reason="Podniesienie limitu na import danych",
            idempotency_key="support:import:quota",
            valid_from=starts_at,
            expires_at=expires_at,
        )
        active = decide_quota("appointments.monthly", at=starts_at + timedelta(minutes=1))
        expired = decide_quota("appointments.monthly", at=expires_at)

    assert active.value == 2_000
    assert active.evidence.source["kind"] == "override"
    assert expired.value == 1_000
    assert expired.evidence.source["kind"] == "expired_override"

    assert expire_entitlement_overrides(at=expires_at) == 1
    grant.refresh_from_db()
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert grant.revoked_at == expires_at
    assert snapshot.quotas["appointments.monthly"] == 1_000
    assert snapshot.sources["appointments.monthly"]["kind"] == "plan"
    assert OrganizationAuditEntry.objects.filter(
        organization=organization,
        action=OrganizationAuditAction.BILLING_OVERRIDE_EXPIRED,
        target_id=grant.id,
    ).count() == 1
    assert expire_entitlement_overrides(at=expires_at) == 0


def test_revocation_restores_plan_and_requires_operator() -> None:
    organization, actor, context = setup_tenant("override-revoke")
    with activate_tenant_context(context):
        grant = create_entitlement_override(
            actor=actor,
            feature_key="booking.enabled",
            enabled=False,
            reason="Czasowa blokada funkcji",
            idempotency_key="support:block-booking",
        )
        revoked = revoke_entitlement_override(
            actor=actor,
            grant_id=grant.id,
            reason="Problem rozwiązany",
        )
        assert decide_feature("booking.enabled").allowed is True

    assert revoked.revoked_at is not None
    audit = OrganizationAuditEntry.objects.get(
        organization=organization,
        action=OrganizationAuditAction.BILLING_OVERRIDE_REVOKED,
    )
    assert audit.metadata == {"reason": "Problem rozwiązany"}

    regular_user = User.objects.create_user(email="regular@example.com")
    regular_context = TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=regular_user.id,
        role_key="owner",
        permissions=frozenset(),
    )
    with activate_tenant_context(regular_context), pytest.raises(BillingOperatorRequired):
        create_entitlement_override(
            actor=regular_user,
            feature_key="booking.enabled",
            enabled=False,
            reason="Niedozwolona zmiana",
            idempotency_key="unauthorized",
        )


def test_idempotency_key_cannot_describe_a_different_override() -> None:
    _, actor, context = setup_tenant("override-conflict")
    starts_at = timezone.now()
    with activate_tenant_context(context):
        create_entitlement_override(
            actor=actor,
            feature_key="booking.enabled",
            enabled=False,
            reason="Pierwsza decyzja",
            idempotency_key="support:decision-1",
            valid_from=starts_at,
        )
        with pytest.raises(OverrideIdempotencyConflict):
            create_entitlement_override(
                actor=actor,
                feature_key="booking.enabled",
                enabled=True,
                reason="Inna decyzja",
                idempotency_key="support:decision-1",
                valid_from=starts_at,
            )


def test_active_target_cannot_have_ambiguous_overrides() -> None:
    _, actor, context = setup_tenant("override-target-conflict")
    with activate_tenant_context(context):
        create_entitlement_override(
            actor=actor,
            quota_key="appointments.monthly",
            limit_value=2_000,
            reason="Pierwszy limit operacyjny",
            idempotency_key="support:quota:first",
        )
        with pytest.raises(OverrideTargetConflict):
            create_entitlement_override(
                actor=actor,
                quota_key="appointments.monthly",
                limit_value=3_000,
                reason="Drugi limit operacyjny",
                idempotency_key="support:quota:second",
            )
