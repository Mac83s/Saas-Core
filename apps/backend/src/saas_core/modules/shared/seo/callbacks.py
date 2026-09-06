from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from saas_core.modules.core.organizations.context import set_local_organization_id

from .models import AuditCallbackReceipt, AuditOrder
from .source import SourceConfig
from .worker import TERMINAL


def receive_callback(body: bytes, headers: Mapping[str, str]) -> bool:
    """Authenticate bytes before deriving the tenant; only reconciliation can settle."""
    config = SourceConfig.configured()
    try:
        event_id = UUID(headers.get("webhook-id", ""))
        timestamp = headers.get("webhook-timestamp", "")
        if len(body) > 64_000 or abs(time.time() - int(timestamp)) > 300:
            raise ValueError
        signed = str(event_id).encode() + b"." + timestamp.encode() + b"." + body
        expected = (
            "v1,"
            + base64.b64encode(
                hmac.digest(config.callback_secret.encode(), signed, "sha256")
            ).decode()
        )
        if not hmac.compare_digest(headers.get("webhook-signature", ""), expected):
            raise ValueError
        payload = json.loads(body)
        run = payload["run"]
        if (
            str(payload["id"]) != str(event_id)
            or payload["type"] != "module_run.finished"
            or run["module_code"] != "onsite"
            or str(run["source_id"]) != str(config.source_id)
            or run["source_product_id"] != config.product_id
            or run["source_deployment_id"] != config.deployment_id
            or run["status"] not in {"completed", "partial", "failed", "cancelled"}
        ):
            raise ValueError
        UUID(str(run["project_id"]))
        UUID(str(run["organization"]))
        if not isinstance(run["external_project_id"], str) or run["delivered"] is not (
            run["status"] in {"completed", "partial"}
        ):
            raise ValueError
        tenant_id, order_id = UUID(run["tenant_id"]), UUID(run["client_reference"])
        module_id, audit_id = UUID(run["id"]), UUID(run["run_reference"])
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise PermissionDenied("Invalid audit callback.") from error
    digest = hashlib.sha256(body).hexdigest()
    with transaction.atomic():
        set_local_organization_id(tenant_id)
        order = (
            AuditOrder.all_objects.select_for_update(of=("self",))
            .select_related("binding")
            .filter(
                pk=order_id,
                organization_id=tenant_id,
                binding__source_id=config.source_id,
            )
            .first()
        )
        if (
            order is None
            or str(run["external_project_id"]) != order.binding.external_project_id
            or (
                order.binding.remote_project_id
                and str(run["project_id"]) != str(order.binding.remote_project_id)
            )
            or (
                order.binding.remote_organization_id
                and str(run["organization"]) != str(order.binding.remote_organization_id)
            )
            or (order.remote_audit_run_id and audit_id != order.remote_audit_run_id)
            or (order.remote_module_run_id and module_id != order.remote_module_run_id)
        ):
            raise PermissionDenied("Invalid audit callback binding.")
        receipt, created = AuditCallbackReceipt.all_objects.get_or_create(
            organization_id=tenant_id,
            source_id=config.source_id,
            event_id=event_id,
            defaults={
                "order": order,
                "payload_hash": digest,
                "remote_module_run_id": module_id,
                "remote_audit_run_id": audit_id,
                "status": run["status"],
            },
        )
        if receipt.payload_hash != digest or receipt.order_id != order.id:
            raise PermissionDenied("Conflicting audit callback.")
        if order.state not in TERMINAL:
            order.next_attempt_at = timezone.now()
            order.save(update_fields=["next_attempt_at", "updated_at"])
        return created
