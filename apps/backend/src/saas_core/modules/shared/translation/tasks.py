from uuid import UUID

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from .models import JOB_TERMINAL, TranslationJob

#: Set while a worker consumes the `ai` queue; without it the offer says
#: `worker_unavailable` (a deployment without worker-ai stays dark).
WORKER_SEEN = "translation:worker-seen"
WORKER_SEEN_TTL = 300


@shared_task(queue="ai")  # type: ignore[untyped-decorator]
def run_translation_job(organization_id: str, job_id: str) -> None:
    cache.set(WORKER_SEEN, 1, WORKER_SEEN_TTL)
    from .worker import run_job

    run_job(UUID(organization_id), UUID(job_id))


def enqueue_job(organization_id: UUID, job_id: UUID) -> None:
    run_translation_job.delay(str(organization_id), str(job_id))


# A tick nobody consumed within two minutes is dropped, not piled up.
@shared_task(queue="ai", expires=120)  # type: ignore[untyped-decorator]
def reconcile_translation_jobs() -> int:
    """The heartbeat, and every job with work due — its lease ran out, its wait
    ended or its deadline passed — handed to a run."""
    cache.set(WORKER_SEEN, 1, WORKER_SEEN_TTL)
    count = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            due = list(
                TranslationJob.all_objects.filter(
                    organization_id=organization_id, next_attempt_at__lte=timezone.now()
                )
                .exclude(state__in=list(JOB_TERMINAL))
                .order_by("next_attempt_at", "id")
                .values_list("id", flat=True)[:50]
            )
        for job_id in due:
            enqueue_job(organization_id, job_id)
            count += 1
    return count
