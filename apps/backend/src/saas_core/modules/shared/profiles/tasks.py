from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task

from .search_engine import SearchEngineUnavailable
from .search_index import reconcile, sync_organization

logger = logging.getLogger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.profiles.tasks.index_catalog_organization",
    autoretry_for=(SearchEngineUnavailable,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def index_catalog_organization(organization_id: str) -> None:
    """One tenant's catalogue document follows its row (ADR-064).

    The payload is only an identifier, and the catalogue row it names is what
    sets the tenant — the task reads nothing a forged message could not already
    find on the public catalogue page.
    """
    try:
        parsed = UUID(organization_id)
    except (TypeError, ValueError):
        logger.warning("catalog_index_task_identifier_rejected")
        return
    sync_organization(parsed)


@shared_task(  # type: ignore[untyped-decorator]
    name="saas_core.modules.shared.profiles.tasks.reconcile_catalog_search",
)
def reconcile_catalog_search() -> dict[str, int]:
    try:
        return reconcile()
    except SearchEngineUnavailable as error:
        # The next sweep tries again; the catalogue meanwhile searches PostgreSQL.
        logger.warning("catalog_search_reconcile_failed", extra={"reason": str(error)})
        return {}
