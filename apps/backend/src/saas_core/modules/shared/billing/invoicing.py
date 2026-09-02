from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from saas_core.modules.core.organizations.models import BillingProfile

from .models import (
    BillingInvoiceDocument,
    BillingSubscription,
    InvoiceDocumentStatus,
    StripeWebhookEvent,
)


class InvoiceAdapterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalInvoiceRequest:
    schema: str
    request_id: str
    source_invoice_id: str
    payment_confirmed_at: str
    currency: str
    amount_paid_minor: int
    buyer: dict[str, Any]
    lines: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class InvoiceAdapterResult:
    document_id: str
    status: str
    payload: dict[str, Any]


class InvoiceAdapter(Protocol):
    key: str

    def issue(self, request: CanonicalInvoiceRequest) -> InvoiceAdapterResult: ...


class InternalInvoiceAdapter:
    """Trwały adapter graniczny W5; nie wysyła dokumentu do KSeF."""

    key = "internal"

    def issue(self, request: CanonicalInvoiceRequest) -> InvoiceAdapterResult:
        return InvoiceAdapterResult(
            document_id=f"internal:{request.request_id}",
            status="recorded",
            payload={"ksef_submission": "not_configured"},
        )


def queue_paid_invoice(
    *,
    event: StripeWebhookEvent,
    subscription: BillingSubscription,
    profile: BillingProfile,
    data: dict[str, Any],
) -> BillingInvoiceDocument:
    stripe_invoice_id = _string(data.get("id")) or event.stripe_event_id
    existing = BillingInvoiceDocument.all_objects.filter(
        stripe_invoice_id=stripe_invoice_id
    ).first()
    if existing is not None:
        return existing

    document_id = uuid.uuid7()
    request, validation_error = _canonical_request(
        document_id=document_id,
        event=event,
        profile=profile,
        data=data,
        stripe_invoice_id=stripe_invoice_id,
    )
    status = InvoiceDocumentStatus.FAILED if validation_error else InvoiceDocumentStatus.PENDING
    document = BillingInvoiceDocument.all_objects.create(
        id=document_id,
        organization_id=subscription.organization_id,
        subscription=subscription,
        origin_event=event,
        stripe_invoice_id=stripe_invoice_id,
        status=status,
        request=request,
        last_error=validation_error,
        payment_confirmed_at=event.provider_created_at,
        completed_at=timezone.now() if validation_error else None,
    )
    if not validation_error:
        organization_id = document.organization_id
        transaction.on_commit(
            lambda: _enqueue_invoice_task(document.id, organization_id),
            robust=True,
        )
    return document


def process_invoice_document(
    document_id: UUID | str,
    *,
    adapter: InvoiceAdapter | None = None,
) -> BillingInvoiceDocument:
    with transaction.atomic():
        document = BillingInvoiceDocument.all_objects.select_for_update().get(pk=document_id)
        if document.status == InvoiceDocumentStatus.SUCCEEDED:
            return document
        document.status = InvoiceDocumentStatus.PROCESSING
        document.attempt_count += 1
        document.last_error = ""
        document.completed_at = None
        document.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_error",
                "completed_at",
                "updated_at",
            ]
        )
        raw_request = document.request

    selected_adapter = adapter
    try:
        if selected_adapter is None:
            selected_adapter = invoice_adapter_from_settings()
        request = _request_from_json(raw_request)
        result = selected_adapter.issue(request)
    except Exception as error:
        message = str(error).strip() or "Adapter fakturowania zwrócił błąd."
        adapter_key = selected_adapter.key if selected_adapter is not None else "unconfigured"
        with transaction.atomic():
            document = BillingInvoiceDocument.all_objects.select_for_update().get(pk=document_id)
            document.status = InvoiceDocumentStatus.FAILED
            document.adapter_key = adapter_key
            document.last_error = message[:2000]
            document.completed_at = timezone.now()
            document.save(
                update_fields=[
                    "status",
                    "adapter_key",
                    "last_error",
                    "completed_at",
                    "updated_at",
                ]
            )
        if isinstance(error, InvoiceAdapterError):
            raise
        raise InvoiceAdapterError("Nie udało się wystawić dokumentu.") from error

    with transaction.atomic():
        document = BillingInvoiceDocument.all_objects.select_for_update().get(pk=document_id)
        document.status = InvoiceDocumentStatus.SUCCEEDED
        document.adapter_key = selected_adapter.key
        document.result = {
            "document_id": result.document_id,
            "status": result.status,
            "payload": result.payload,
        }
        document.last_error = ""
        document.completed_at = timezone.now()
        document.save(
            update_fields=[
                "status",
                "adapter_key",
                "result",
                "last_error",
                "completed_at",
                "updated_at",
            ]
        )
        return document


def invoice_adapter_from_settings() -> InvoiceAdapter:
    adapter_class = import_string(settings.BILLING_INVOICE_ADAPTER)
    return cast(InvoiceAdapter, adapter_class())


def _canonical_request(
    *,
    document_id: UUID,
    event: StripeWebhookEvent,
    profile: BillingProfile,
    data: dict[str, Any],
    stripe_invoice_id: str,
) -> tuple[dict[str, Any], str]:
    errors: list[str] = []
    currency = _string(data.get("currency"))
    if currency is None:
        errors.append("Brak waluty opłaconej faktury Stripe.")
    amount_paid = data.get("amount_paid")
    if not isinstance(amount_paid, int) or isinstance(amount_paid, bool) or amount_paid < 0:
        errors.append("Brak poprawnej kwoty opłaconej faktury Stripe.")
        amount_paid = None
    lines = _invoice_lines(data.get("lines"))
    if not lines:
        errors.append("Brak pozycji opłaconej faktury Stripe.")
    request = {
        "schema": "saas-core.invoice-request.v1",
        "request_id": str(document_id),
        "source_invoice_id": stripe_invoice_id,
        "payment_confirmed_at": event.provider_created_at.isoformat(),
        "currency": currency.upper() if currency else None,
        "amount_paid_minor": amount_paid,
        "buyer": {
            "kind": profile.customer_kind,
            "legal_name": profile.legal_name,
            "tax_id": profile.tax_id,
            "country_code": profile.country_code,
            "address_line1": profile.address_line1,
            "postal_code": profile.postal_code,
            "city": profile.city,
            "billing_email": profile.billing_email,
        },
        "lines": lines,
    }
    return request, " ".join(errors)


def _invoice_lines(value: Any) -> list[dict[str, Any]]:
    rows = value.get("data") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        amount = row.get("amount")
        currency = _string(row.get("currency"))
        if not isinstance(amount, int) or isinstance(amount, bool) or currency is None:
            continue
        quantity = row.get("quantity")
        result.append({
            "source_line_id": _string(row.get("id")),
            "description": _string(row.get("description")) or "",
            "amount_minor": amount,
            "currency": currency.upper(),
            "quantity": (
                quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else None
            ),
        })
    return result


def _request_from_json(value: Any) -> CanonicalInvoiceRequest:
    if not isinstance(value, dict):
        raise InvoiceAdapterError("Kanoniczne żądanie faktury nie jest obiektem.")
    try:
        return CanonicalInvoiceRequest(
            schema=str(value["schema"]),
            request_id=str(value["request_id"]),
            source_invoice_id=str(value["source_invoice_id"]),
            payment_confirmed_at=str(value["payment_confirmed_at"]),
            currency=str(value["currency"]),
            amount_paid_minor=int(value["amount_paid_minor"]),
            buyer=dict(value["buyer"]),
            lines=tuple(value["lines"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise InvoiceAdapterError("Kanoniczne żądanie faktury jest niekompletne.") from error


def _enqueue_invoice_task(document_id: UUID, organization_id: UUID) -> None:
    from .tasks import issue_invoice_document

    # The document row carries forced row-level security, so the worker is told
    # which tenant it is for; it cannot look that up first (ADR-039).
    issue_invoice_document.delay(str(document_id), str(organization_id))


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
