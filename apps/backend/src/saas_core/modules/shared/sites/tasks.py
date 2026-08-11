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
