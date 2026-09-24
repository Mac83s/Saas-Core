from datetime import timedelta
from uuid import UUID

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from .models import TERMINAL, ImageGenerationJob, JobState
from .services import WORKER_SEEN
from .worker import expire_ingest, run_job

INGEST_TIMEOUT = timedelta(hours=24)
REFUSED_PROMPT_RETENTION = timedelta(days=30)


@shared_task(queue="ai")  # type: ignore[untyped-decorator]
def run_image_generation_job(organization_id: str, job_id: str) -> None:
    run_job(UUID(organization_id), UUID(job_id))


@shared_task(queue="ai")  # type: ignore[untyped-decorator]
def reconcile_image_generation_jobs() -> int:
    # The heartbeat: this task runs only where a worker consumes `ai`, and the
    # offer is unavailable without it (a product with no worker-ai stays dark).
    cache.set(WORKER_SEEN, 1, 300)
    count = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            now = timezone.now()
            jobs = ImageGenerationJob.all_objects.filter(organization_id=organization_id)
            stale = list(
                jobs.filter(
                    state=JobState.INGESTING, created_at__lt=now - INGEST_TIMEOUT
                ).values_list("id", flat=True)[:100]
            )
            due = list(
                jobs.filter(next_attempt_at__lte=now)
                .exclude(state__in=TERMINAL)
                .exclude(id__in=stale)
                .filter(Q(lease_until=None) | Q(lease_until__lte=now))
                .order_by("next_attempt_at", "id")
                .values_list("id", flat=True)[:100]
            )
            jobs.filter(
                state=JobState.REFUSED, finished_at__lt=now - REFUSED_PROMPT_RETENTION
            ).exclude(prompt="").update(prompt="")
        for job_id in stale:
            expire_ingest(organization_id, job_id)
        for job_id in due:
            run_image_generation_job.delay(str(organization_id), str(job_id))
            count += 1
    return count
