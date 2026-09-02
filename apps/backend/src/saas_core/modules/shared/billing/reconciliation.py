from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    OrganizationAuditAction,
)

from .lifecycle import sync_subscription_lifecycle
from .models import (
    AccessMode,
    BillingReconciliation,
    BillingSubscription,
    ReconciliationStatus,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from .processor import subscription_access
from .provider import (
    BillingProviderError,
    ProviderSubscriptionSnapshot,
    get_billing_provider,
)
from .snapshots import update_entitlement_snapshot
from .tenant_scope import billing_organization_ids, billing_tenant_scope


def run_reconciliation_batch(*, at: datetime | None = None, limit: int | None = None) -> int:
    if settings.BILLING_PROVIDER != "stripe":
        return 0
    checked_at = at or timezone.now()
    batch_limit = limit or settings.BILLING_RECONCILIATION_BATCH_SIZE
    if batch_limit <= 0:
        raise ValueError("Limit rekonsyliacji musi być dodatni.")
    scheduled_for = _schedule_bucket(checked_at)
    handled = 0
    remaining = batch_limit
    # Subscriptions force row-level security, so the batch walks organizations
    # rather than asking for everybody's subscriptions at once (ADR-039).
    for organization_id in billing_organization_ids():
        if remaining <= 0:
            break
        with billing_tenant_scope(organization_id):
            subscription_ids = list(
                BillingSubscription.all_objects.filter(organization_id=organization_id)
                .order_by("updated_at", "id")
                .values_list("id", flat=True)[:remaining]
            )
        remaining -= len(subscription_ids)
        for subscription_id in subscription_ids:
            with billing_tenant_scope(organization_id):
                subscription = BillingSubscription.all_objects.get(pk=subscription_id)
                reconciliation, _ = BillingReconciliation.all_objects.get_or_create(
                    organization_id=subscription.organization_id,
                    subscription=subscription,
                    scheduled_for=scheduled_for,
                    defaults={"baseline_version": subscription.version},
                )
                pending = reconciliation.status == ReconciliationStatus.PENDING
                reconciliation_id = reconciliation.id
            if not pending:
                continue
            if _run_reconciliation(organization_id, reconciliation_id, checked_at):
                handled += 1
    return handled


def _run_reconciliation(
    organization_id: UUID, reconciliation_id: UUID, checked_at: datetime
) -> bool:
    with billing_tenant_scope(organization_id):
        reconciliation = BillingReconciliation.all_objects.select_related(
            "subscription",
        ).get(pk=reconciliation_id)
        stripe_subscription_id = reconciliation.subscription.stripe_subscription_id
    try:
        # Deliberately outside the tenant scope: a provider call must not hold
        # a transaction open for as long as the network takes.
        remote = get_billing_provider().retrieve_subscription(stripe_subscription_id)
    except (BillingProviderError, ImproperlyConfigured) as error:
        _record_failure(organization_id, reconciliation_id, error, checked_at)
        return False
    try:
        return _apply_remote_snapshot(organization_id, reconciliation_id, remote, checked_at)
    except Exception as error:
        _record_failure(organization_id, reconciliation_id, error, checked_at)
        return False


def _apply_remote_snapshot(
    organization_id: UUID,
    reconciliation_id: UUID,
    remote: ProviderSubscriptionSnapshot,
    checked_at: datetime,
) -> bool:
    with billing_tenant_scope(organization_id):
        reconciliation = (
            BillingReconciliation.all_objects.select_for_update()
            .select_related("organization", "subscription")
            .get(pk=reconciliation_id)
        )
        if reconciliation.status != ReconciliationStatus.PENDING:
            return False
        subscription = (
            BillingSubscription.all_objects.select_for_update()
            .select_related("price_mapping__plan_version__plan", "organization")
            .get(pk=reconciliation.subscription_id)
        )
        reconciliation.attempt_count += 1
        if subscription.version != reconciliation.baseline_version:
            _complete(
                reconciliation,
                ReconciliationStatus.CONFLICT,
                checked_at,
                {
                    "baseline_version": reconciliation.baseline_version,
                    "current_version": subscription.version,
                },
            )
            return True

        profile = BillingProfile.objects.get(organization_id=subscription.organization_id)
        if remote.id != subscription.stripe_subscription_id:
            raise BillingProviderError("Stripe zwrócił inną subskrypcję.")
        if remote.customer_id != profile.external_customer_id:
            raise BillingProviderError("Subskrypcja Stripe wskazuje innego Customer.")
        if remote.livemode != settings.STRIPE_LIVEMODE:
            raise BillingProviderError("Subskrypcja Stripe ma inny tryb test/live.")
        if remote.status not in StripeSubscriptionStatus.values:
            raise BillingProviderError("Stripe zwrócił nieobsługiwany status subskrypcji.")
        mapping = (
            StripePriceMapping.objects.select_related("plan_version__plan")
            .filter(stripe_price_id=remote.price_id, livemode=remote.livemode)
            .first()
        )
        if mapping is None:
            raise BillingProviderError("Subskrypcja Stripe używa nieznanego Price.")

        state, access_mode = subscription_access(remote.status)
        grace_period_end = None
        if remote.status == StripeSubscriptionStatus.PAST_DUE:
            grace_period_end = subscription.grace_period_end or checked_at + timedelta(
                days=mapping.plan_version.grace_period_days
            )
            if subscription.state == SubscriptionState.READ_ONLY:
                state = SubscriptionState.READ_ONLY
                access_mode = AccessMode.READ_ONLY
                effective_until = None
            else:
                effective_until = grace_period_end
        elif remote.status == StripeSubscriptionStatus.CANCELED:
            if remote.current_period_end and remote.current_period_end > checked_at:
                access_mode = AccessMode.FULL
                effective_until = remote.current_period_end
            else:
                effective_until = None
        elif state == SubscriptionState.TRIALING:
            effective_until = remote.trial_end
        elif access_mode == AccessMode.READ_ONLY:
            effective_until = None
        else:
            effective_until = remote.current_period_end

        desired: dict[str, Any] = {
            "price_mapping": mapping,
            "state": state,
            "provider_status": remote.status,
            "current_period_start": remote.current_period_start,
            "current_period_end": remote.current_period_end,
            "trial_start": remote.trial_start,
            "trial_end": remote.trial_end,
            "grace_period_end": grace_period_end,
            "cancel_at_period_end": remote.cancel_at_period_end,
            "canceled_at": remote.canceled_at,
            "ended_at": remote.ended_at,
        }
        changes = {
            field: {"from": _json_value(getattr(subscription, field)), "to": _json_value(value)}
            for field, value in desired.items()
            if getattr(subscription, field) != value
        }
        if not changes:
            _complete(reconciliation, ReconciliationStatus.NO_CHANGE, checked_at, {})
            return True
        for field, value in desired.items():
            setattr(subscription, field, value)
        subscription.version += 1
        subscription.save()
        update_entitlement_snapshot(
            subscription.organization,
            mapping,
            state=state,
            access_mode=access_mode,
            effective_until=effective_until,
        )
        sync_subscription_lifecycle(subscription)
        _complete(reconciliation, ReconciliationStatus.SUCCEEDED, checked_at, changes)
        record_audit(
            organization=subscription.organization,
            action=OrganizationAuditAction.BILLING_RECONCILED,
            actor=None,
            target_type="billing_subscription",
            target_id=subscription.id,
            metadata={
                "reconciliation_id": str(reconciliation.id),
                "changed_fields": sorted(changes),
                "baseline_version": reconciliation.baseline_version,
                "result_version": subscription.version,
            },
        )
        return True


def _record_failure(
    organization_id: UUID,
    reconciliation_id: UUID,
    error: Exception,
    checked_at: datetime,
) -> None:
    with billing_tenant_scope(organization_id):
        reconciliation = BillingReconciliation.all_objects.select_for_update().get(
            pk=reconciliation_id
        )
        if reconciliation.status != ReconciliationStatus.PENDING:
            return
        reconciliation.attempt_count += 1
        reconciliation.last_error = str(error)[:2000]
        if reconciliation.attempt_count >= settings.BILLING_RECONCILIATION_MAX_ATTEMPTS:
            reconciliation.status = ReconciliationStatus.FAILED
            reconciliation.completed_at = checked_at
        reconciliation.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_error",
                "completed_at",
                "updated_at",
            ]
        )


def _complete(
    reconciliation: BillingReconciliation,
    status: str,
    checked_at: datetime,
    changes: dict[str, Any],
) -> None:
    reconciliation.status = status
    reconciliation.changes = changes
    reconciliation.last_error = ""
    reconciliation.completed_at = checked_at
    reconciliation.save(
        update_fields=[
            "status",
            "attempt_count",
            "changes",
            "last_error",
            "completed_at",
            "updated_at",
        ]
    )


def _schedule_bucket(checked_at: datetime) -> datetime:
    interval = settings.BILLING_RECONCILIATION_INTERVAL_SECONDS
    timestamp = int(checked_at.timestamp())
    return datetime.fromtimestamp(timestamp - timestamp % interval, tz=UTC)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    identifier = getattr(value, "pk", None)
    return str(identifier) if identifier is not None else value
