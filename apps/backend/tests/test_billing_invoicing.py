from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.shared.billing.invoicing import (
    CanonicalInvoiceRequest,
    InternalInvoiceAdapter,
    InvoiceAdapterError,
    InvoiceAdapterResult,
    process_invoice_document,
    queue_paid_invoice,
)
from saas_core.modules.shared.billing.models import (
    BillingInvoiceDocument,
    BillingSubscription,
    InvoiceDocumentStatus,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    StripeWebhookEvent,
    SubscriptionState,
    WebhookProcessingStatus,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


class FailingInvoiceAdapter:
    key = "failing"

    def issue(self, _request: CanonicalInvoiceRequest) -> InvoiceAdapterResult:
        raise InvoiceAdapterError("Kolejka operatora faktur jest niedostępna.")


def setup_invoice(slug: str) -> tuple[BillingProfile, BillingSubscription, StripeWebhookEvent]:
    organization = Organization.objects.create(name=slug, slug=slug)
    profile = BillingProfile.objects.create(
        organization=organization,
        customer_kind="company",
        legal_name="ACME sp. z o.o.",
        tax_id="5250000000",
        address_line1="Prosta 1",
        postal_code="00-001",
        city="Warszawa",
        billing_email="billing@example.com",
        external_customer_id=f"cus_{slug}",
    )
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id=f"prod_{slug}",
        stripe_price_id=f"price_{slug}",
    )
    subscription = BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{slug}",
        state=SubscriptionState.ACTIVE,
        provider_status=StripeSubscriptionStatus.ACTIVE,
        current_period_start=NOW,
        current_period_end=NOW + timedelta(days=30),
    )
    event = StripeWebhookEvent.objects.create(
        stripe_event_id=f"evt_{slug}",
        event_type="invoice.paid",
        api_version="2026-07-29.dahlia",
        livemode=False,
        provider_created_at=NOW,
        payload={"data": {"object": {"id": f"in_{slug}"}}},
        status=WebhookProcessingStatus.PROCESSED,
        organization=organization,
        subscription=subscription,
        signature_verified_at=NOW,
        processed_at=NOW,
    )
    return profile, subscription, event


def valid_invoice_data(slug: str) -> dict:
    return {
        "id": f"in_{slug}",
        "currency": "pln",
        "amount_paid": 14_900,
        "lines": {
            "data": [
                {
                    "id": f"il_{slug}",
                    "description": "Starter v1",
                    "amount": 14_900,
                    "currency": "pln",
                    "quantity": 1,
                }
            ]
        },
    }


def test_canonical_request_and_adapter_result_are_durable_and_idempotent() -> None:
    profile, subscription, event = setup_invoice("invoice-success")
    data = valid_invoice_data("invoice-success")

    first = queue_paid_invoice(
        event=event,
        subscription=subscription,
        profile=profile,
        data=data,
    )
    repeated = queue_paid_invoice(
        event=event,
        subscription=subscription,
        profile=profile,
        data=data,
    )
    completed = process_invoice_document(first.id, adapter=InternalInvoiceAdapter())
    replay = process_invoice_document(first.id, adapter=InternalInvoiceAdapter())

    assert repeated.id == first.id
    assert BillingInvoiceDocument.all_objects.count() == 1
    assert first.request["schema"] == "saas-core.invoice-request.v1"
    assert first.request["currency"] == "PLN"
    assert first.request["buyer"]["tax_id"] == "5250000000"
    assert completed.status == InvoiceDocumentStatus.SUCCEEDED
    assert completed.adapter_key == "internal"
    assert completed.result["status"] == "recorded"
    assert completed.result["payload"]["ksef_submission"] == "not_configured"
    assert replay.attempt_count == 1


def test_adapter_failure_is_retryable_and_does_not_change_confirmed_payment() -> None:
    profile, subscription, event = setup_invoice("invoice-adapter-failure")
    document = queue_paid_invoice(
        event=event,
        subscription=subscription,
        profile=profile,
        data=valid_invoice_data("invoice-adapter-failure"),
    )

    with pytest.raises(InvoiceAdapterError, match="niedostępna"):
        process_invoice_document(document.id, adapter=FailingInvoiceAdapter())

    document.refresh_from_db()
    subscription.refresh_from_db()
    event.refresh_from_db()
    assert document.status == InvoiceDocumentStatus.FAILED
    assert document.adapter_key == "failing"
    assert document.attempt_count == 1
    assert subscription.state == SubscriptionState.ACTIVE
    assert subscription.provider_status == StripeSubscriptionStatus.ACTIVE
    assert event.status == WebhookProcessingStatus.PROCESSED

    retried = process_invoice_document(document.id, adapter=InternalInvoiceAdapter())
    assert retried.status == InvoiceDocumentStatus.SUCCEEDED
    assert retried.attempt_count == 2


def test_incomplete_invoice_is_persisted_as_failure_without_adapter_call() -> None:
    profile, subscription, event = setup_invoice("invoice-incomplete")

    document = queue_paid_invoice(
        event=event,
        subscription=subscription,
        profile=profile,
        data={"id": "in_invoice-incomplete"},
    )

    assert document.status == InvoiceDocumentStatus.FAILED
    assert document.attempt_count == 0
    assert document.completed_at is not None
    assert "Brak waluty" in document.last_error
    assert "Brak poprawnej kwoty" in document.last_error
    assert "Brak pozycji" in document.last_error
