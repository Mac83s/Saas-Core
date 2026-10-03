from datetime import timedelta
from uuid import UUID

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.api import platform_setting
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from .models import AssistantConversation, AssistantTurn, TurnState
from .services import WORKER_SEEN, WORKER_SEEN_TTL
from .settings_spec import RETENTION_DAYS
from .turns import FAILURE_TIMEOUT, fail_without_person

#: A turn nobody moved for this long is given up: its worker died, or there is
#: none. The person sees it failed and writes again.
STALE_SECONDS = 180


@shared_task(queue="ai")  # type: ignore[untyped-decorator]
def run_assistant_turn(organization_id: str, turn_id: str) -> None:
    cache.set(WORKER_SEEN, 1, WORKER_SEEN_TTL)
    from .turns import run_turn

    run_turn(UUID(organization_id), UUID(turn_id))


# A tick nobody consumed within two minutes is dropped, not piled up.
@shared_task(queue="ai", expires=120)  # type: ignore[untyped-decorator]
def assistant_heartbeat() -> None:
    """Says a worker consumes the `ai` queue, so the chat is open."""
    cache.set(WORKER_SEEN, 1, WORKER_SEEN_TTL)


@shared_task  # type: ignore[untyped-decorator]
def reconcile_assistant_turns() -> int:
    """Closes turns left queued or running with nobody working on them. Runs
    on the default queue: it must work exactly when the `ai` worker does not."""
    stale = timezone.now() - timedelta(seconds=STALE_SECONDS)
    closed = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            turn_ids = list(
                AssistantTurn.all_objects.filter(
                    organization_id=organization_id,
                    state__in=[TurnState.QUEUED, TurnState.RUNNING],
                    updated_at__lt=stale,
                ).values_list("id", flat=True)[:100]
            )
        for turn_id in turn_ids:
            fail_without_person(organization_id, turn_id, FAILURE_TIMEOUT)
            closed += 1
    return closed


@shared_task  # type: ignore[untyped-decorator]
def purge_assistant_conversations() -> int:
    """Once a day: conversations past `assistant.retention.conversation_days`
    since their last message leave with their transcript."""
    cutoff = timezone.now() - timedelta(days=int(platform_setting(RETENTION_DAYS.key)))
    removed = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            _, by_model = AssistantConversation.all_objects.filter(
                organization_id=organization_id, updated_at__lt=cutoff
            ).delete()
            removed += by_model.get(AssistantConversation._meta.label, 0)
    return removed
