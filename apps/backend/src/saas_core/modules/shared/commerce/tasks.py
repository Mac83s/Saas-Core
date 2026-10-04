"""The dates of awaited payments (ADR-073 §5): a prepayment that did not come
by its date expires, its order is canceled and the source lets go of what it
held — the booking's time, later the goods. A balance — the rest of a
confirmed order's price — is only reminded of and reported late: it cancels
nothing (owner decision 29a)."""

from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.tasks import InvalidTenantTaskContext, tenant_task_context
from saas_core.modules.shared.notifications.security import decrypt_secret

from .models import PaymentRoute
from .payments import payment_due

logger = logging.getLogger("saas_core.security")


@shared_task  # type: ignore[untyped-decorator]
def expire_due_payments() -> int:
    """Reads the routes — no tenant's data — and opens each payment's own
    organization for it; answers how many payments expired. A route the
    payment is to be looked at again for (a balance, reminded of before its
    date) is moved to that time instead of being closed."""
    expired = 0
    routes = list(
        PaymentRoute.objects.filter(
            dispatched_at__isnull=True, due_at__lte=timezone.now()
        ).order_by("due_at")[:100]
    )
    for route in routes:
        again: datetime | None = None
        try:
            with tenant_task_context(
                _contract(route),
                expected_causation_id=f"commerce-payment:{route.payment_id}",
                # Due when the source's terms say, which can be past the TTL.
                expires=False,
            ):
                gone, again = payment_due(route.payment_id)
                expired += gone
        except InvalidTenantTaskContext as error:
            # A contract that does not open now never will; left unmarked it
            # would head the queue forever (the reminders' lesson, ADR-058 §7).
            logger.warning(
                "commerce_payment_route_rejected",
                extra={
                    "security_event": "commerce.payment_route_rejected",
                    "route_id": str(route.pk),
                    "reason": str(error),
                },
            )
        with transaction.atomic():
            waiting = PaymentRoute.objects.filter(pk=route.pk, dispatched_at__isnull=True)
            if again is not None:
                waiting.update(due_at=again)
            else:
                waiting.update(dispatched_at=timezone.now())
    return expired


def _contract(route: PaymentRoute) -> str:
    try:
        return decrypt_secret(route.signed_tenant_context)
    except RuntimeError as error:
        # A key since rotated: no later run decrypts it either.
        raise InvalidTenantTaskContext(str(error)) from error
