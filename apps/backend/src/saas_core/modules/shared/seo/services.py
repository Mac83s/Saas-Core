from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    operation_cost,
    reserve_credits,
)
from saas_core.modules.shared.sites.api import read_site_audit_target

from .models import AuditOrder, SourceSiteBinding
from .permissions import SEO_AUDIT_ENABLED, SEO_AUDIT_READ, SEO_AUDIT_RUN
from .source import SourceConfig, canonical_hash


class AuditOrderConflict(APIException):
    status_code = 409
    default_detail = "Klucz operacji wskazuje inny audyt lub zmienioną domenę."
    default_code = "seo_audit_conflict"


class AuditOrderNotFound(NotFound):
    default_detail = "Audyt nie istnieje."
    default_code = "seo_audit_not_found"


@transaction.atomic
def request_audit(
    *,
    site_id: UUID,
    idempotency_key: str,
    options: dict[str, Any],
    expected_credit_cost: int | None = None,
) -> tuple[AuditOrder, bool]:
    context = authorize_entitled(SEO_AUDIT_RUN, SEO_AUDIT_ENABLED)
    if context.principal_kind != "membership":
        raise PermissionDenied("An audit purchase requires a person membership.")
    config = SourceConfig.configured()
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 120:
        raise AuditOrderConflict(detail="Klucz idempotencji musi mieć od 8 do 120 znaków.")
    normalized = dict(options)
    max_pages = normalized.get("max_pages")
    if set(normalized) - {"max_pages"} or (
        max_pages is not None
        and (
            not isinstance(max_pages, int)
            or isinstance(max_pages, bool)
            or not 1 <= max_pages <= config.max_pages
        )
    ):
        raise AuditOrderConflict(detail="Parametry audytu są poza dozwolonym zakresem.")
    # Core sets the page ceiling explicitly; the caller cannot inflate a paid
    # operation by relying on a later change to SSA's default project settings.
    normalized.setdefault("max_pages", config.max_pages)
    digest = canonical_hash({
        "site_id": str(site_id),
        "options": normalized,
        "expected_credit_cost": expected_credit_cost,
    })
    organization = Organization.objects.select_for_update().get(pk=context.organization_id)
    existing = AuditOrder.all_objects.filter(
        organization_id=context.organization_id,
        idempotency_key=key,
    ).first()
    if existing is not None:
        if existing.request_hash != digest:
            raise AuditOrderConflict
        return existing, False
    target = read_site_audit_target(site_id=site_id)
    binding, _created = SourceSiteBinding.all_objects.get_or_create(
        organization_id=context.organization_id,
        site_id=site_id,
        source_id=config.source_id,
        defaults={
            "external_project_id": str(site_id),
            "name": target["name"],
            "root_url": target["root_url"],
        },
    )
    if binding.root_url != target["root_url"]:
        raise AuditOrderConflict
    order = AuditOrder(
        organization_id=context.organization_id,
        binding=binding,
        created_by_id=context.actor_id,
        membership_id=context.membership_id,
        idempotency_key=key,
        request_hash=digest,
        requested_options=normalized,
        credit_operation_key=config.credit_operation_key,
        next_attempt_at=timezone.now(),
    )
    credit_key = f"seo-audit-{order.id}"
    reservation = reserve_credits(
        config.credit_operation_key, idempotency_key=credit_key, expected_cost=expected_credit_cost
    )
    if reservation is not None:
        order.credit_reservation_key = credit_key
        order.credit_cost = reservation.cost
        order.credit_state = "reserved"
    order.save()
    record_audit(
        organization=organization,
        action="seo.audit.requested",
        actor=User.objects.get(pk=context.actor_id),
        target_type="seo_audit_order",
        target_id=order.id,
        metadata={
            "site_id": str(site_id),
            "credit_cost": order.credit_cost,
            "credit_operation_key": order.credit_operation_key,
        },
    )
    return order, True


def read_audit(*, order_id: UUID) -> AuditOrder:
    context = authorize_entitled(SEO_AUDIT_READ, SEO_AUDIT_ENABLED, operation=FeatureOperation.READ)
    order = (
        AuditOrder.all_objects.select_related("binding")
        .filter(
            pk=order_id,
            organization_id=context.organization_id,
        )
        .first()
    )
    if order is None:
        raise AuditOrderNotFound
    return order


def list_audits(
    *, cursor: UUID | None = None, limit: int = 50
) -> tuple[list[AuditOrder], UUID | None]:
    context = authorize_entitled(SEO_AUDIT_READ, SEO_AUDIT_ENABLED, operation=FeatureOperation.READ)
    query = (
        AuditOrder.all_objects.select_related("binding")
        .defer("report_snapshot")
        .filter(organization_id=context.organization_id)
    )
    if cursor is not None:
        query = query.filter(id__lt=cursor)
    limit = min(max(limit, 1), 100)
    rows = list(query.order_by("-id")[: limit + 1])
    return rows[:limit], rows[limit - 1].id if len(rows) > limit else None


def read_audit_offer() -> dict[str, int]:
    authorize_entitled(SEO_AUDIT_RUN, SEO_AUDIT_ENABLED)
    config = SourceConfig.configured()
    return {
        "credit_cost": operation_cost(config.credit_operation_key),
        "max_pages": config.max_pages,
    }
