from datetime import timedelta

from celery import shared_task

from . import admission
from .models import UsageEntry

#: A year of comparisons and the running month: enough to reconcile with
#: OpenRouter's billing and to read the margin.
RETENTION = timedelta(days=396)


@shared_task  # type: ignore[untyped-decorator]
def sweep_model_port_admissions() -> tuple[int, int]:
    """Expired reservations stop counting; calls stuck past their time become unknown."""
    return admission.sweep()


@shared_task  # type: ignore[untyped-decorator]
def purge_model_port_usage() -> int:
    deleted, _ = (
        UsageEntry.objects.using(admission.alias())
        .filter(created_at__lt=admission.now() - RETENTION)
        .delete()
    )
    return deleted
