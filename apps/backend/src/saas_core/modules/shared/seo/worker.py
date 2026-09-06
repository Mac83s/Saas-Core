"""Reconcile one durable intent; a timeout cannot decide whether a purchase succeeded."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    context_from_membership,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    MembershipStatus,
    Organization,
    OrganizationStatus,
)
from saas_core.modules.shared.billing.api import (
    authorize_entitled,
    commit_credits,
    release_credits,
)
from saas_core.modules.shared.sites.api import read_site_audit_target

from .models import AuditOrder, AuditOrderState, SourceSiteBinding
from .permissions import SEO_AUDIT_ENABLED, SEO_AUDIT_RUN
from .source import SourceConfig, SourceError, SsaSource, canonical_hash

TERMINAL = {
    AuditOrderState.COMPLETED,
    AuditOrderState.PARTIAL,
    AuditOrderState.FAILED,
    AuditOrderState.CANCELLED,
}


def _settlement_context(order: AuditOrder) -> TenantContext:
    # This is the persisted prior authorization, not a new request impersonating
    # a member who may since have left. It may only settle this order's hold.
    return TenantContext(
        organization_id=order.organization_id,
        membership_id=order.membership_id,
        actor_id=order.created_by_id,
        role_key="seo_order",
        permissions=frozenset(),
        principal_kind="seo_order",
    )


def _request_still_authorized(order: AuditOrder) -> bool:
    membership = (
        Membership.objects.select_related("role", "user", "organization")
        .filter(
            pk=order.membership_id,
            organization_id=order.organization_id,
            user_id=order.created_by_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
            organization__status=OrganizationStatus.ACTIVE,
        )
        .first()
    )
    if membership is None:
        return False
    from rest_framework.exceptions import APIException

    with activate_tenant_context(context_from_membership(membership)):
        try:
            authorize_entitled(SEO_AUDIT_RUN, SEO_AUDIT_ENABLED)
            target = read_site_audit_target(site_id=order.binding.site_id)
            if target["root_url"] != order.binding.root_url:
                return False
        except APIException:
            return False
    return True


def _identity(payload: dict[str, Any], order: AuditOrder, config: SourceConfig) -> None:
    expected = {
        "source_id": str(config.source_id),
        "product_id": config.product_id,
        "deployment_id": config.deployment_id,
        "external_tenant_id": str(order.organization_id),
        "external_project_id": order.binding.external_project_id,
    }
    if any(str(payload.get(key)) != value for key, value in expected.items()):
        raise SourceError("ssa_identity_mismatch")


def _operation(payload: dict[str, Any], order: AuditOrder, config: SourceConfig) -> None:
    _identity(payload, order, config)
    expected = {
        "client_reference": str(order.id),
        "project_id": str(order.binding.remote_project_id),
        "binding_id": str(order.binding.remote_binding_id),
        "organization_id": str(order.binding.remote_organization_id),
    }
    if any(str(payload.get(key)) != value for key, value in expected.items()):
        raise SourceError("ssa_operation_identity_mismatch")
    if payload.get("requested_options") != order.requested_options:
        raise SourceError("ssa_operation_options_mismatch")
    effective = payload.get("effective_options")
    if (
        not isinstance(effective, dict)
        or effective.get("start_url") != order.binding.root_url
        or not isinstance(effective.get("max_pages"), int)
        or isinstance(effective.get("max_pages"), bool)
        or not 1 <= effective["max_pages"] <= order.requested_options["max_pages"]
        or (order.effective_options and effective != order.effective_options)
    ):
        raise SourceError("ssa_effective_options_mismatch")
    module_id = payload.get("module_run_id")
    if module_id is not None:
        try:
            parsed_module = UUID(str(module_id))
        except ValueError as error:
            raise SourceError("ssa_operation_malformed") from error
        if order.remote_module_run_id and order.remote_module_run_id != parsed_module:
            raise SourceError("ssa_operation_identity_mismatch")
    elif order.remote_module_run_id is not None:
        raise SourceError("ssa_operation_identity_mismatch")
    for field, local in [
        ("audit_run_id", order.remote_audit_run_id),
        ("job_id", order.remote_job_id),
        ("operation_id", order.remote_operation_id),
    ]:
        try:
            incoming = UUID(str(payload[field]))
        except (KeyError, ValueError, TypeError) as error:
            raise SourceError("ssa_operation_malformed") from error
        if local is not None and local != incoming:
            raise SourceError("ssa_operation_identity_mismatch")


@transaction.atomic
def _claim(organization_id: UUID, order_id: UUID) -> AuditOrder | None:
    set_local_organization_id(organization_id)
    now = timezone.now()
    order = (
        AuditOrder.all_objects.select_for_update(of=("self",))
        .select_related("binding")
        .filter(
            pk=order_id,
            organization_id=organization_id,
        )
        .first()
    )
    if (
        order is None
        or order.state in TERMINAL
        or order.next_attempt_at > now
        or (order.lease_until is not None and order.lease_until > now)
    ):
        return None
    if order.state == AuditOrderState.QUEUED and not _request_still_authorized(order):
        _finish(order, AuditOrderState.CANCELLED, error_code="request_authorization_revoked")
        return None
    order.lease_token = uuid4()
    order.lease_until = now + timedelta(minutes=5)
    order.attempts += 1
    if order.state == AuditOrderState.QUEUED:
        order.state = AuditOrderState.SUBMITTING
    order.save(update_fields=["lease_token", "lease_until", "attempts", "state", "updated_at"])
    return order


def _finish(
    order: AuditOrder,
    state: str,
    *,
    report: dict[str, Any] | None = None,
    error_code: str = "",
    provider_cost: Decimal | None = None,
) -> None:
    if order.credit_reservation_key:
        with activate_tenant_context(_settlement_context(order)):
            if state == AuditOrderState.COMPLETED:
                commit_credits(order.credit_reservation_key)
                order.credit_state = "committed"
            else:
                release_credits(order.credit_reservation_key)
                order.credit_state = "released"
    order.state = state
    order.error_code = error_code
    order.completed_at = timezone.now()
    order.lease_until = None
    order.lease_token = None
    if report is not None:
        order.report_snapshot = report
        order.report_hash = canonical_hash(report)
    order.provider_cost_usd = provider_cost
    order.save()
    record_audit(
        organization=Organization.objects.get(pk=order.organization_id),
        action="seo.audit.finished",
        actor=None,
        target_type="seo_audit_order",
        target_id=order.id,
        metadata={
            "state": state,
            "credit_state": order.credit_state,
            "credit_cost": order.credit_cost,
            "report_hash": order.report_hash,
        },
    )


def dispatch_audit(
    organization_id: UUID, order_id: UUID, *, source: SsaSource | None = None
) -> None:
    config = source.config if source else SourceConfig.configured()
    client = source or SsaSource(config)
    order = _claim(organization_id, order_id)
    if order is None:
        return
    try:
        if order.binding.source_id != config.source_id:
            raise SourceError("ssa_source_changed")
        if order.binding.remote_project_id is None:
            provisioned = client.provision(
                organization_id,
                external_project_id=order.binding.external_project_id,
                name=order.binding.name,
                root_url=order.binding.root_url,
            )
            _identity(provisioned, order, config)
            if provisioned.get("root_url") != order.binding.root_url:
                raise SourceError("ssa_binding_url_mismatch")
            with transaction.atomic():
                set_local_organization_id(organization_id)
                binding = SourceSiteBinding.all_objects.select_for_update().get(
                    pk=order.binding_id, organization_id=organization_id
                )
                for remote, local in [
                    ("binding_id", "remote_binding_id"),
                    ("project_id", "remote_project_id"),
                    ("organization_id", "remote_organization_id"),
                ]:
                    value = UUID(str(provisioned[remote]))
                    held = getattr(binding, local)
                    if held is not None and held != value:
                        raise SourceError("ssa_binding_identity_mismatch")
                    setattr(binding, local, value)
                binding.save()
                order.binding = binding
        # A GET always precedes submission, including a retry after a lost HTTP
        # response. Only an explicit absence permits resending the same intent.
        try:
            result = client.status(organization_id, order.id)
        except SourceError as error:
            if not error.missing:
                raise
            with transaction.atomic():
                set_local_organization_id(organization_id)
                if not _request_still_authorized(order):
                    raise SourceError("request_authorization_revoked", retryable=False) from error
            result = client.start(
                organization_id,
                external_project_id=order.binding.external_project_id,
                client_reference=order.id,
                options=order.requested_options,
            )
        _operation(result, order, config)
        status = str(result.get("audit_status", ""))
        if status not in {"pending", "running", "completed", "failed", "cancelled"}:
            raise SourceError("ssa_unknown_audit_status")
        module_status = result.get("module_status")
        terminal = None
        cost = None
        undispatched_cancel = (
            status == "cancelled"
            and result.get("job_status") == "cancelled"
            and result.get("module_run_id") is None
            and module_status is None
        )
        if undispatched_cancel:
            terminal = AuditOrderState.CANCELLED
        elif status in {"completed", "failed", "cancelled"}:
            if module_status not in {"completed", "partial", "failed", "cancelled"}:
                raise SourceError("ssa_module_not_terminal")
            if result.get("module_run_id") is None:
                raise SourceError("ssa_module_not_terminal")
            expected_delivered = module_status in {"completed", "partial"}
            if result.get("module_delivered") is not expected_delivered:
                raise SourceError("ssa_delivery_mismatch")
            if status == "completed" and module_status not in {"completed", "partial"}:
                raise SourceError("ssa_delivery_mismatch")
            terminal = {
                "completed": AuditOrderState.COMPLETED,
                "partial": AuditOrderState.PARTIAL,
                "failed": AuditOrderState.FAILED,
                "cancelled": AuditOrderState.CANCELLED,
            }[module_status]
            if status != "completed" and terminal in {
                AuditOrderState.COMPLETED,
                AuditOrderState.PARTIAL,
            }:
                raise SourceError("ssa_delivery_mismatch")
            if result.get("provider_cost_usd") is not None:
                try:
                    cost = Decimal(str(result["provider_cost_usd"]))
                    if not cost.is_finite() or cost < 0 or cost >= Decimal("1000000000000"):
                        raise InvalidOperation
                except InvalidOperation as error:
                    raise SourceError("ssa_provider_cost_invalid") from error
        report = None
        if terminal in {AuditOrderState.COMPLETED, AuditOrderState.PARTIAL}:
            assert order.binding.remote_project_id is not None
            report = client.report(
                organization_id,
                audit_run_id=UUID(str(result["audit_run_id"])),
                project_id=order.binding.remote_project_id,
            )
            report["provenance"] = {
                "source_id": str(config.source_id),
                "operation_id": str(result["operation_id"]),
                "audit_run_id": str(result["audit_run_id"]),
                "observed_at": timezone.now().isoformat(),
                "effective_options": result.get("effective_options"),
            }
        with transaction.atomic():
            set_local_organization_id(organization_id)
            current = (
                AuditOrder.all_objects.select_for_update()
                .filter(pk=order.id, organization_id=organization_id)
                .first()
            )
            if (
                current is None
                or current.lease_token != order.lease_token
                or current.state in TERMINAL
            ):
                return
            current.remote_operation_id = UUID(str(result["operation_id"]))
            current.remote_audit_run_id = UUID(str(result["audit_run_id"]))
            current.remote_job_id = UUID(str(result["job_id"]))
            current.remote_module_run_id = (
                UUID(str(result["module_run_id"])) if result.get("module_run_id") else None
            )
            current.effective_options = result.get("effective_options", {})
            if terminal is not None:
                _finish(current, terminal, report=report, provider_cost=cost)
            else:
                current.state = AuditOrderState.RUNNING
                current.lease_until = None
                current.lease_token = None
                current.next_attempt_at = timezone.now() + timedelta(seconds=30)
                current.error_code = ""
                current.save()
    except (SourceError, ValueError, KeyError, TypeError) as error:
        code = error.code if isinstance(error, SourceError) else "ssa_response_malformed"
        with transaction.atomic():
            set_local_organization_id(organization_id)
            current = (
                AuditOrder.all_objects.select_for_update()
                .filter(pk=order.id, organization_id=organization_id)
                .first()
            )
            if (
                current is None
                or current.lease_token != order.lease_token
                or current.state in TERMINAL
            ):
                return
            if code == "request_authorization_revoked":
                _finish(current, AuditOrderState.CANCELLED, error_code=code)
            else:
                current.state = AuditOrderState.RECONCILING
                current.error_code = code
                current.lease_until = None
                current.lease_token = None
                current.next_attempt_at = timezone.now() + timedelta(
                    seconds=min(3600, 2 ** min(current.attempts, 11))
                )
                current.save()
