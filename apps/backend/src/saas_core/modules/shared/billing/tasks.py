from __future__ import annotations

from celery import shared_task

from .lifecycle import process_due_lifecycle_actions
from .overrides import expire_entitlement_overrides
from .processor import StripeEventProcessingError, process_stripe_event
from .reconciliation import run_reconciliation_batch


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(StripeEventProcessingError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_stripe_webhook(event_id: str) -> None:
    process_stripe_event(event_id)


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.billing.tasks.process_billing_lifecycle"
)
def process_billing_lifecycle() -> int:
    return process_due_lifecycle_actions()


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.billing.tasks.reconcile_billing_subscriptions"
)
def reconcile_billing_subscriptions() -> int:
    return run_reconciliation_batch()


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.billing.tasks.expire_billing_overrides"
)
def expire_billing_overrides() -> int:
    return expire_entitlement_overrides()
