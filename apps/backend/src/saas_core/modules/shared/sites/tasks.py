from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task

from saas_core.modules.core.organizations.api import DomainEventDeliveryError
from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    tenant_task_context,
)

from .services import publish_site_outbox_event

logger = logging.getLogger("saas_core.security")


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.sites.tasks.verify_site_domain",
)
def verify_site_domain(domain_id: str) -> None:
    from .dns_verification import verify_domain_dns

    try:
        parsed_domain_id = UUID(domain_id)
    except (TypeError, ValueError):
        logger.warning(
            "site_domain_task_identifier_rejected",
            extra={"security_event": "sites.domain_task_identifier_rejected"},
        )
        return
    verify_domain_dns(domain_id=parsed_domain_id)


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.sites.tasks.schedule_domain_verifications",
)
def schedule_domain_verifications() -> int:
    from .dns_verification import schedule_due_domain_verifications

    return schedule_due_domain_verifications()


@shared_task(  # type: ignore[untyped-decorator]
    autoretry_for=(DomainEventDeliveryError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 8},
)
def publish_site_outbox_event_task(
    event_id: str,
    signed_tenant_context: str,
) -> None:
    try:
        parsed_event_id = UUID(event_id)
    except (TypeError, ValueError):
        logger.warning(
            "sites_outbox_task_identifier_rejected",
            extra={"security_event": "sites.outbox_task_identifier_rejected"},
        )
        return
    try:
        with tenant_task_context(
            signed_tenant_context,
            expected_causation_id=f"sites-outbox:{parsed_event_id}",
        ):
            publish_site_outbox_event(event_id=parsed_event_id)
    except InvalidTenantTaskContext:
        logger.warning(
            "sites_outbox_task_context_rejected",
            extra={"security_event": "sites.outbox_task_context_rejected"},
        )


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.sites.tasks.publish_scheduled_entry",
)
def publish_scheduled_entry(
    entry_id: str,
    organization_id: str,
    membership_id: str,
    actor_id: str,
) -> None:
    """Publishes one article whose scheduled moment has passed.

    The tenant context is rebuilt from the stored membership rather than from a
    signed payload: a publication scheduled for next week outlives any signed
    contract, and asking again is also what stops somebody who has since lost
    access from getting one more publication out of the queue.
    """
    from saas_core.modules.core.organizations.tasks import deferred_tenant_context

    from .collections import run_scheduled_publication

    try:
        parsed_entry_id = UUID(entry_id)
    except (TypeError, ValueError):
        logger.warning(
            "sites_schedule_task_identifier_rejected",
            extra={"security_event": "sites.schedule_task_identifier_rejected"},
        )
        return
    try:
        with deferred_tenant_context(
            organization_id=organization_id,
            membership_id=membership_id,
            actor_id=actor_id,
            causation_id=f"sites-entry-schedule:{parsed_entry_id}",
        ):
            run_scheduled_publication(entry_id=parsed_entry_id)
    except InvalidTenantTaskContext:
        logger.warning(
            "sites_schedule_task_context_rejected",
            extra={"security_event": "sites.schedule_task_context_rejected"},
        )


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.sites.tasks.publish_due_entries",
)
def publish_due_entries() -> int:
    from .collections import due_scheduled_entries

    due = due_scheduled_entries()
    for item in due:
        publish_scheduled_entry.delay(
            item["entry_id"],
            item["organization_id"],
            item["membership_id"],
            item["actor_id"],
        )
    return len(due)
