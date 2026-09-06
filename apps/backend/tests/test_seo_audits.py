from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.billing.models import (
    CreditOperation,
    CreditReservation,
    EntitlementSnapshot,
)
from saas_core.modules.shared.seo.callbacks import receive_callback
from saas_core.modules.shared.seo.models import AuditCallbackReceipt, AuditOrder, SourceSiteBinding
from saas_core.modules.shared.seo.source import SourceConfig, SourceError, SsaSource
from saas_core.modules.shared.seo.worker import dispatch_audit
from saas_core.modules.shared.sites.models import Domain, Site
from test_sites_api import csrf_value, sites_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def seo(settings: Any) -> Any:
    cache.clear()
    settings.SEO_SSA_BASE_URL = "https://ssa.example.test/api/v1"
    settings.SEO_SSA_SOURCE_ID = str(uuid4())
    settings.SEO_SSA_PRODUCT_ID = "saas-core"
    settings.SEO_SSA_DEPLOYMENT_ID = "test"
    settings.SEO_SSA_SERVICE_KEY = "synthetic-service-key"
    settings.SEO_SSA_CALLBACK_SECRET = "synthetic-callback-key"
    settings.SEO_AUDIT_CREDIT_OPERATION = "seo.test.audit"
    client, org, user = sites_client(slug="seo-owner", role_key="owner")
    snapshot = EntitlementSnapshot.all_objects.get(organization=org)
    snapshot.features["seo.audit.enabled"] = True
    snapshot.quotas["credits.monthly"] = 100
    snapshot.save()
    operation = CreditOperation.objects.create(key="seo.test.audit", name="Test audit", cost=7)
    site = Site.all_objects.create(organization=org, name="Test", slug="test", created_by=user)
    Domain.all_objects.create(
        organization=org,
        site=site,
        hostname="owned.example.test",
        kind="custom",
        status="verified",
        is_canonical=True,
        created_by=user,
    )
    return client, org, user, site, operation


def order_for(seo: Any, *, key: str = "audit-test-001") -> AuditOrder:
    client, _, _, site, _ = seo
    response = client.post(
        "/api/v1/seo/audits/",
        {"site_id": str(site.id), "idempotency_key": key},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 201, response.content
    return AuditOrder.all_objects.select_related("binding").get(pk=response.json()["id"])


class FakeSource(SsaSource):
    def __init__(self, order: AuditOrder):
        super().__init__(SourceConfig.configured())
        self.order = order
        self.calls: list[str] = []
        self.remote = {
            "source_id": str(self.config.source_id),
            "product_id": self.config.product_id,
            "deployment_id": self.config.deployment_id,
            "external_tenant_id": str(order.organization_id),
            "external_project_id": order.binding.external_project_id,
            "binding_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "project_id": str(uuid4()),
            "root_url": order.binding.root_url,
        }
        self.result = {
            **self.remote,
            "client_reference": str(order.id),
            "operation_id": str(uuid4()),
            "audit_run_id": str(uuid4()),
            "job_id": str(uuid4()),
            "module_run_id": str(uuid4()),
            "requested_options": order.requested_options,
            "effective_options": {"start_url": order.binding.root_url, "max_pages": 100},
            "audit_status": "completed",
            "job_status": "succeeded",
            "module_status": "completed",
            "module_delivered": True,
            "provider_cost_usd": "0.01000000",
        }
        self.exists = False
        self.lose_response = False
        self.report_error = False

    def provision(self, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("provision")
        return self.remote

    def status(self, tenant_id: UUID, client_reference: UUID) -> dict[str, Any]:
        assert client_reference == self.order.id
        self.calls.append("status")
        if not self.exists:
            raise SourceError("missing", missing=True)
        return self.result

    def start(self, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["client_reference"] == self.order.id
        assert kwargs["options"] == self.order.requested_options
        self.calls.append("start")
        self.exists = True
        if self.lose_response:
            raise SourceError("ssa_transport_unknown")
        return self.result

    def report(self, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("report")
        if self.report_error:
            raise SourceError("ssa_report_incomplete")
        return {"audit": {"id": self.result["audit_run_id"]}, "issues": [], "issue_count": 0}


def due(order: AuditOrder) -> None:
    AuditOrder.all_objects.filter(pk=order.id).update(
        next_attempt_at=timezone.now() - timedelta(seconds=1)
    )


def test_order_reserves_once_and_does_not_contact_ssa(seo: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        SsaSource, "_request", lambda *args, **kwargs: pytest.fail("request did network IO")
    )
    order = order_for(seo)
    client, _, _, site, _ = seo
    response = client.post(
        "/api/v1/seo/audits/",
        {"site_id": str(site.id), "idempotency_key": order.idempotency_key},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(order.id)
    assert CreditReservation.all_objects.count() == 1
    assert order.credit_cost == 7 and order.credit_state == "reserved"
    assert CreditReservation.all_objects.get().expires_at is None
    response = client.post(
        "/api/v1/seo/audits/",
        {"site_id": str(site.id), "idempotency_key": order.idempotency_key, "max_pages": 2},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 409


@pytest.mark.parametrize("refusal", ["feature", "permission", "csrf", "domain", "unknown_price"])
def test_refusal_creates_no_order_or_reservation(seo: Any, refusal: str) -> None:
    client, org, _, site, operation = seo
    if refusal == "feature":
        EntitlementSnapshot.all_objects.filter(organization=org).update(
            features={"sites.enabled": True}
        )
    elif refusal == "permission":
        from saas_core.modules.core.organizations.models import Role

        Membership.objects.filter(organization=org).update(
            role=Role.objects.get(key="manager", organization=None)
        )
    elif refusal == "domain":
        Domain.all_objects.filter(site=site).update(status="pending")
    elif refusal == "unknown_price":
        operation.delete()
    response = client.post(
        "/api/v1/seo/audits/",
        {"site_id": str(site.id), "idempotency_key": "refused-audit"},
        format="json",
        HTTP_X_CSRFTOKEN="invalid" if refusal == "csrf" else csrf_value(client),
    )
    assert response.status_code in {403, 409}, response.content
    assert not AuditOrder.all_objects.exists()
    assert not SourceSiteBinding.all_objects.exists()
    assert not CreditReservation.all_objects.exists()


@pytest.mark.parametrize(
    "module_status,credit_state",
    [
        ("completed", "committed"),
        ("partial", "released"),
        ("failed", "released"),
        ("cancelled", "released"),
    ],
)
def test_authoritative_delivery_settles_exactly_once(
    seo: Any, module_status: str, credit_state: str
) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    source.result["module_status"] = module_status
    source.result["module_delivered"] = module_status in {"completed", "partial"}
    source.result["audit_status"] = "completed" if module_status == "partial" else module_status
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert order.state == module_status
    assert order.credit_state == credit_state
    assert str(order.provider_cost_usd) == "0.01000000"
    assert bool(order.report_hash) == (module_status in {"completed", "partial"})
    dispatch_audit(order.organization_id, order.id, source=source)
    assert source.calls.count("start") == 1
    assert CreditReservation.all_objects.get().state == credit_state


def test_lost_response_uses_get_and_same_operation_without_second_submission(seo: Any) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    source.lose_response = True
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert (order.state, order.credit_state) == ("reconciling", "reserved")
    due(order)
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert order.state == "completed"
    assert source.calls.count("start") == 1
    assert source.calls.count("status") == 2


@pytest.mark.parametrize("failure", ["identity", "report", "module", "options"])
def test_unverified_or_incomplete_delivery_keeps_hold(seo: Any, failure: str) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    if failure == "identity":
        source.result["external_tenant_id"] = str(uuid4())
    elif failure == "module":
        source.result["module_status"] = None
    elif failure == "options":
        source.result["effective_options"]["max_pages"] = 10000
    else:
        source.report_error = True
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert (order.state, order.credit_state, order.report_hash) == ("reconciling", "reserved", "")


def test_revoked_requester_cannot_start_but_existing_purchase_can_settle(seo: Any) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    Membership.objects.filter(organization_id=order.organization_id).update(status="suspended")
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert order.state == "cancelled" and not source.calls
    assert order.credit_state == "released"


def callback_for(
    order: AuditOrder, source: FakeSource, *, event_id: UUID | None = None
) -> tuple[bytes, dict[str, str]]:
    event_id = event_id or uuid4()
    run = {
        "id": source.result["module_run_id"],
        "module_code": "onsite",
        "run_reference": source.result["audit_run_id"],
        "client_reference": str(order.id),
        "status": "completed",
        "delivered": True,
        "project_id": source.result["project_id"],
        "organization": source.result["organization_id"],
        "tenant_id": str(order.organization_id),
        "source_id": str(source.config.source_id),
        "source_product_id": source.config.product_id,
        "source_deployment_id": source.config.deployment_id,
        "external_project_id": order.binding.external_project_id,
        "error_message": "PRIVATE MUST NEVER BE RETAINED",
    }
    body = json.dumps({"id": str(event_id), "type": "module_run.finished", "run": run}).encode()
    timestamp = str(int(time.time()))
    signature = base64.b64encode(
        hmac.digest(
            source.config.callback_secret.encode(),
            str(event_id).encode() + b"." + timestamp.encode() + b"." + body,
            "sha256",
        )
    ).decode()
    return body, {
        "webhook-id": str(event_id),
        "webhook-timestamp": timestamp,
        "webhook-signature": "v1," + signature,
    }


def test_callback_before_submit_response_is_idempotent_and_never_charges(seo: Any) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    body, headers = callback_for(order, source)
    assert receive_callback(body, headers) is True
    assert receive_callback(body, headers) is False
    order.refresh_from_db()
    assert order.credit_state == "reserved" and not order.report_hash
    receipt = AuditCallbackReceipt.all_objects.get()
    assert receipt.payload_hash == hashlib.sha256(body).hexdigest()
    assert "PRIVATE" not in str(receipt.__dict__)


def test_callback_invalid_signature_reads_zero_database_rows(seo: Any) -> None:
    order = order_for(seo)
    body, headers = callback_for(order, FakeSource(order))
    headers["webhook-signature"] = "v1,bad"
    with CaptureQueriesContext(connection) as captured, pytest.raises(PermissionDenied):
        receive_callback(body, headers)
    assert len(captured) == 0


def test_settlement_survives_membership_revoked_after_submission(seo: Any) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    source.lose_response = True
    dispatch_audit(order.organization_id, order.id, source=source)
    Membership.objects.filter(organization_id=order.organization_id).update(status="suspended")
    due(order)
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert (order.state, order.credit_state) == ("completed", "committed")
    assert source.calls.count("start") == 1


def test_cancelled_before_dispatch_releases_without_module(seo: Any) -> None:
    order = order_for(seo)
    source = FakeSource(order)
    source.result.update(
        audit_status="cancelled",
        job_status="cancelled",
        module_run_id=None,
        module_status=None,
        module_delivered=None,
        provider_cost_usd=None,
    )
    dispatch_audit(order.organization_id, order.id, source=source)
    order.refresh_from_db()
    assert (order.state, order.credit_state) == ("cancelled", "released")


def test_inactive_catalog_operation_is_explicitly_free(seo: Any) -> None:
    seo[4].is_active = False
    seo[4].save()
    order = order_for(seo)
    assert order.credit_state == "free" and order.credit_cost == 0
    assert not CreditReservation.all_objects.exists()


def test_cross_tenant_reads_do_not_disclose_audit(seo: Any) -> None:
    order = order_for(seo)
    client, org, _ = sites_client(slug="seo-stranger", role_key="owner")
    EntitlementSnapshot.all_objects.filter(organization=org).update(
        features={"seo.audit.enabled": True}
    )
    assert client.get(f"/api/v1/seo/audits/{order.id}/").status_code == 404
    assert client.get("/api/v1/seo/audits/").json() == {"items": [], "next_cursor": None}


def test_closed_result_and_original_request_are_immutable(seo: Any) -> None:
    from django.db import DatabaseError, transaction

    order = order_for(seo)
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditOrder.all_objects.filter(pk=order.id).update(requested_options={"max_pages": 1000})
    source = FakeSource(order)
    dispatch_audit(order.organization_id, order.id, source=source)
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditOrder.all_objects.filter(pk=order.id).update(report_snapshot={"forged": True})


def test_erasure_removes_three_seo_tables_and_retains_other_tenant(seo: Any) -> None:
    from saas_core.modules.core.organizations.erasure import erase_organization, row_counts

    order = order_for(seo)
    source = FakeSource(order)
    receive_callback(*callback_for(order, source))
    dispatch_audit(order.organization_id, order.id, source=source)
    _, other, _ = sites_client(slug="seo-erasure-other", role_key="owner")
    before = row_counts(order.organization_id)
    assert {key for key in before if key.startswith("seo.")} == {
        "seo.SourceSiteBinding",
        "seo.AuditOrder",
        "seo.AuditCallbackReceipt",
    }
    receipt = erase_organization(
        organization=seo[1], requested_by=seo[2], reason="Synthetic deletion"
    )
    assert row_counts(order.organization_id) == {}
    assert receipt.row_counts["seo.AuditOrder"] == 1
    assert row_counts(other.id)


def test_worker_sets_tenant_before_private_order_reads(seo: Any) -> None:
    order = order_for(seo)
    with CaptureQueriesContext(connection) as captured:
        dispatch_audit(order.organization_id, order.id, source=FakeSource(order))
    sqls = [item["sql"] for item in captured]
    setting = next(i for i, sql in enumerate(sqls) if "SET LOCAL app.organization_id" in sql)
    private = next(i for i, sql in enumerate(sqls) if 'FROM "seo_auditorder"' in sql)
    assert setting < private


def test_callback_sets_tenant_before_order_reads(seo: Any) -> None:
    order = order_for(seo)
    body, headers = callback_for(order, FakeSource(order))
    with CaptureQueriesContext(connection) as captured:
        receive_callback(body, headers)
    sqls = [item["sql"] for item in captured]
    assert next(i for i, sql in enumerate(sqls) if "SET LOCAL app.organization_id" in sql) < next(
        i for i, sql in enumerate(sqls) if 'FROM "seo_auditorder"' in sql
    )


def test_audit_list_cursor_has_no_duplicates_and_read_has_no_business_effect(seo: Any) -> None:
    first, second = order_for(seo), order_for(seo, key="audit-test-002")
    client = seo[0]
    before = list(CreditReservation.all_objects.values("id", "state"))
    page = client.get("/api/v1/seo/audits/?limit=1").json()
    assert [row["id"] for row in page["items"]] == [str(second.id)]
    page = client.get(f"/api/v1/seo/audits/?limit=1&cursor={page['next_cursor']}").json()
    assert [row["id"] for row in page["items"]] == [str(first.id)]
    assert page["next_cursor"] is None
    assert list(CreditReservation.all_objects.values("id", "state")) == before


def test_unknown_request_option_is_refused_instead_of_silently_ignored(seo: Any) -> None:
    client, _, _, site, _ = seo
    response = client.post(
        "/api/v1/seo/audits/",
        {"site_id": str(site.id), "idempotency_key": "unknown-mode", "mode": "full"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert response.status_code == 400
    assert not AuditOrder.all_objects.exists()


def test_displayed_price_is_checked_under_catalog_lock_before_reserving(seo: Any) -> None:
    client, _, _, site, operation = seo
    offer = client.get("/api/v1/seo/audit-offer/")
    assert offer.status_code == 200 and offer.json() == {"credit_cost": 7, "max_pages": 100}
    assert not CreditReservation.all_objects.exists()
    operation.cost = 9
    operation.save()
    payload = {
        "site_id": str(site.id),
        "idempotency_key": "price-review-001",
        "expected_credit_cost": 7,
    }
    response = client.post(
        "/api/v1/seo/audits/", payload, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "credit_price_changed"
    assert not AuditOrder.all_objects.exists() and not CreditReservation.all_objects.exists()
    payload["expected_credit_cost"] = 9
    with CaptureQueriesContext(connection) as captured:
        response = client.post(
            "/api/v1/seo/audits/", payload, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
        )
    assert response.status_code == 201
    sqls = [row["sql"] for row in captured]
    locked = next(
        i
        for i, sql in enumerate(sqls)
        if 'FROM "billing_creditoperation"' in sql and "FOR UPDATE" in sql
    )
    reserved = next(
        i for i, sql in enumerate(sqls) if 'INSERT INTO "billing_creditreservation"' in sql
    )
    assert locked < reserved
    operation.cost = 12
    operation.save()
    response = client.post(
        "/api/v1/seo/audits/", payload, format="json", HTTP_X_CSRFTOKEN=csrf_value(client)
    )
    assert response.status_code == 200 and response.json()["credit_cost"] == 9
