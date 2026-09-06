from uuid import UUID

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from .models import AuditOrder
from .worker import TERMINAL, dispatch_audit


@shared_task  # type: ignore[untyped-decorator]
def dispatch_audit_task(organization_id: str, order_id: str) -> None:
    dispatch_audit(UUID(organization_id), UUID(order_id))


@shared_task  # type: ignore[untyped-decorator]
def reconcile_audits() -> int:
    count = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            now = timezone.now()
            ids = list(
                AuditOrder.all_objects.filter(
                    organization_id=organization_id, next_attempt_at__lte=now
                )
                .exclude(state__in=TERMINAL)
                .filter(Q(lease_until=None) | Q(lease_until__lte=now))
                .order_by("next_attempt_at", "id")
                .values_list("id", flat=True)[:100]
            )
        for order_id in ids:
            dispatch_audit_task.delay(str(organization_id), str(order_id))
            count += 1
    return count
