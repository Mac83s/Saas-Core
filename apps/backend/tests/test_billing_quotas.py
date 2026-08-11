from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, close_old_connections, connections, transaction

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    PlanVersion,
    QuotaDefinition,
    QuotaReservation,
    QuotaReservationState,
    QuotaUsage,
    SubscriptionState,
)
from saas_core.modules.shared.billing.quotas import (
    QuotaExceeded,
    QuotaReservationConflict,
    QuotaReservationExpired,
    QuotaUnavailable,
    adjust_quota_reservation,
    commit_quota,
    consume_quota,
    extend_quota_reservation,
    release_expired_quota_reservations,
    release_quota,
    reserve_quota,
)

pytestmark = pytest.mark.django_db


def setup_quota(*, slug: str, quota: int = 2) -> tuple[Organization, TenantContext]:
    tenant = Organization.objects.create(name=slug, slug=slug)
    actor = User.objects.create_user(email=f"{slug}@example.com")
    plan_version = PlanVersion.objects.get(plan__key="starter", version=1)
    EntitlementSnapshot.all_objects.create(
        organization=tenant,
        plan_version=plan_version,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"booking.enabled": True},
        quotas={"appointments.monthly": quota},
        sources={"appointments.monthly": {"kind": "plan", "ref": "starter:v1"}},
    )
    return tenant, TenantContext(
        organization_id=tenant.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="owner",
        permissions=frozenset(),
    )


def test_reservation_is_idempotent_and_never_exceeds_limit() -> None:
    tenant, tenant_context = setup_quota(slug="quota-reserve", quota=2)

    with activate_tenant_context(tenant_context):
        first = reserve_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:one",
        )
        repeated = reserve_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:one",
        )
        with pytest.raises(QuotaExceeded):
            reserve_quota(
                "appointments.monthly",
                amount=1,
                idempotency_key="appointment:two",
            )

    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert repeated.id == first.id
    assert usage.reserved == 2
    assert usage.used == 0
    assert QuotaReservation.all_objects.filter(organization=tenant).count() == 1


def test_same_idempotency_key_cannot_change_reservation_scope() -> None:
    _, tenant_context = setup_quota(slug="quota-conflict", quota=3)

    with activate_tenant_context(tenant_context):
        reserve_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:same",
        )
        with pytest.raises(QuotaReservationConflict):
            reserve_quota(
                "appointments.monthly",
                amount=2,
                idempotency_key="appointment:same",
            )


def test_commit_and_release_are_idempotent_and_update_counter() -> None:
    tenant, tenant_context = setup_quota(slug="quota-finalize", quota=3)

    with activate_tenant_context(tenant_context):
        reserve_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:commit",
        )
        committed = commit_quota("appointment:commit")
        repeated_commit = commit_quota("appointment:commit")
        with pytest.raises(QuotaReservationConflict):
            release_quota("appointment:commit")

        reserve_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:release",
        )
        released = release_quota("appointment:release")
        repeated_release = release_quota("appointment:release")

    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert committed.state == QuotaReservationState.COMMITTED
    assert repeated_commit.id == committed.id
    assert released.state == QuotaReservationState.RELEASED
    assert repeated_release.id == released.id
    assert usage.used == 1
    assert usage.reserved == 0


def test_reservation_can_be_adjusted_and_extended_before_exact_commit() -> None:
    tenant, tenant_context = setup_quota(slug="quota-adjust", quota=8)
    now = datetime(2026, 8, 11, 12, tzinfo=UTC)

    with activate_tenant_context(tenant_context):
        reservation = reserve_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:adjust",
            at=now,
            expires_at=now + timedelta(minutes=5),
        )
        extended = extend_quota_reservation(
            "appointment:adjust",
            expires_at=now + timedelta(hours=1),
            at=now,
        )
        adjusted = adjust_quota_reservation(
            "appointment:adjust",
            amount=5,
            at=now + timedelta(minutes=10),
        )
        committed = commit_quota(
            "appointment:adjust",
            at=now + timedelta(minutes=10),
        )
        repeated = adjust_quota_reservation(
            "appointment:adjust",
            amount=5,
            at=now + timedelta(minutes=10),
        )

    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert extended.expires_at == now + timedelta(hours=1)
    assert adjusted.amount == 5
    assert committed.state == QuotaReservationState.COMMITTED
    assert repeated.id == reservation.id
    assert usage.used == 5
    assert usage.reserved == 0


def test_adjustment_cannot_exceed_quota_or_change_committed_amount() -> None:
    tenant, tenant_context = setup_quota(slug="quota-adjust-limit", quota=3)

    with activate_tenant_context(tenant_context):
        reserve_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:adjust-limit",
        )
        with pytest.raises(QuotaExceeded):
            adjust_quota_reservation("appointment:adjust-limit", amount=4)
        commit_quota("appointment:adjust-limit")
        with pytest.raises(QuotaReservationConflict):
            adjust_quota_reservation("appointment:adjust-limit", amount=1)

    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert usage.used == 2
    assert usage.reserved == 0


def test_consume_is_exactly_once_for_repeated_business_event() -> None:
    tenant, tenant_context = setup_quota(slug="quota-consume", quota=5)

    with activate_tenant_context(tenant_context):
        first = consume_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:created:42",
        )
        repeated = consume_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:created:42",
        )

    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert repeated.id == first.id
    assert first.state == QuotaReservationState.COMMITTED
    assert usage.used == 2
    assert usage.reserved == 0


def test_expired_reservation_cannot_be_committed_and_is_released_by_worker() -> None:
    tenant, tenant_context = setup_quota(slug="quota-expired", quota=2)
    reserved_at = datetime(2026, 8, 11, 12, tzinfo=UTC)
    expires_at = reserved_at + timedelta(minutes=5)

    with activate_tenant_context(tenant_context):
        reservation = reserve_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:expired",
            at=reserved_at,
            expires_at=expires_at,
        )
        with pytest.raises(QuotaReservationExpired):
            commit_quota("appointment:expired", at=expires_at)

    assert release_expired_quota_reservations(at=expires_at) == 1
    assert release_expired_quota_reservations(at=expires_at) == 0
    reservation.refresh_from_db()
    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert reservation.state == QuotaReservationState.RELEASED
    assert usage.used == 0
    assert usage.reserved == 0


def test_monthly_usage_isolated_between_periods() -> None:
    tenant, tenant_context = setup_quota(slug="quota-periods", quota=1)
    august = datetime(2026, 8, 31, 23, 59, tzinfo=UTC)
    september = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)

    with activate_tenant_context(tenant_context):
        consume_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:august",
            at=august,
        )
        consume_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:september",
            at=september,
        )

    periods = list(
        QuotaUsage.all_objects.filter(organization=tenant).order_by("period_start")
    )
    assert [(item.period_start.isoformat(), item.used) for item in periods] == [
        ("2026-08-01", 1),
        ("2026-09-01", 1),
    ]


def test_downgrade_below_used_value_blocks_further_consumption() -> None:
    tenant, tenant_context = setup_quota(slug="quota-downgrade", quota=3)

    with activate_tenant_context(tenant_context):
        consume_quota(
            "appointments.monthly",
            amount=2,
            idempotency_key="appointment:before-downgrade",
        )
        EntitlementSnapshot.all_objects.filter(organization=tenant).update(
            quotas={"appointments.monthly": 1}
        )
        with pytest.raises(QuotaExceeded):
            consume_quota(
                "appointments.monthly",
                amount=1,
                idempotency_key="appointment:after-downgrade",
            )

    usage = QuotaUsage.all_objects.get(organization=tenant)
    assert usage.used == 2
    assert usage.reserved == 0


def test_read_only_snapshot_cannot_reserve_quota() -> None:
    tenant, tenant_context = setup_quota(slug="quota-read-only")
    EntitlementSnapshot.all_objects.filter(organization=tenant).update(
        access_mode=AccessMode.READ_ONLY
    )

    with (
        activate_tenant_context(tenant_context),
        pytest.raises(QuotaUnavailable),
    ):
        reserve_quota(
            "appointments.monthly",
            amount=1,
            idempotency_key="appointment:read-only",
        )


def test_database_rejects_non_positive_reservation_amount() -> None:
    tenant, _ = setup_quota(slug="quota-constraint")
    usage = QuotaUsage.all_objects.create(
        organization=tenant,
        quota_definition=QuotaDefinition.objects.get(key="appointments.monthly"),
        period_start="2026-08-01",
        period_end="2026-09-01",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        QuotaReservation.all_objects.create(
            organization=tenant,
            usage=usage,
            idempotency_key="invalid-zero",
            amount=0,
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_cannot_both_reserve_last_unit() -> None:
    _, tenant_context = setup_quota(slug="quota-concurrent", quota=1)

    def attempt(key: str) -> str:
        close_old_connections()
        try:
            with activate_tenant_context(tenant_context):
                reserve_quota(
                    "appointments.monthly",
                    amount=1,
                    idempotency_key=key,
                )
            return "reserved"
        except QuotaExceeded:
            return "exceeded"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ["concurrent:one", "concurrent:two"]))

    assert sorted(results) == ["exceeded", "reserved"]
    usage = QuotaUsage.all_objects.get(organization_id=tenant_context.organization_id)
    assert usage.reserved == 1
    assert usage.used == 0
