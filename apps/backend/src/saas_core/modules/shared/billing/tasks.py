from __future__ import annotations

from celery import shared_task

from .processor import StripeEventProcessingError, process_stripe_event


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(StripeEventProcessingError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_stripe_webhook(event_id: str) -> None:
    process_stripe_event(event_id)
