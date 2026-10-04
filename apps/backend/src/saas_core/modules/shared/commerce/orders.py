"""Placing an order and what a source may do with it afterwards (ADR-073 §3).

A source — a booking, later the shop — calls these inside its own transaction
and tenant: the order is written with the thing it stands for or not at all.
Commerce works out no amount. The panel reads orders through `list_orders`
and `read_order`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import F, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import TenantContext, require_tenant_context
from saas_core.modules.core.organizations.history import HistoryTarget
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.billing.decisions import FeatureOperation, decide_feature
from saas_core.modules.shared.customers.api import Customer, consents_of
from saas_core.modules.shared.notifications.api import scrub_messages

from .ledger import MANUAL_METHODS, paid_minor, payments_of, status_for
from .models import (
    Amounts,
    Order,
    OrderChannel,
    OrderCounter,
    OrderLine,
    OrderLineKind,
    OrderStatus,
    Payment,
    PaymentRoute,
    PaymentStatus,
    TaxRate,
)
from .names import COMMERCE_ENABLED, ORDERS_READ
from .sources import order_source, order_sources
from .transfer_account import transfer_account

MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class OrderLineInput:
    """A line as its source priced it; see `OrderLine` for each field."""

    kind: str
    name: str
    customer_name: str
    quantity: int
    unit_amount_minor: int
    net_minor: int
    vat_minor: int
    gross_minor: int
    tax_rate: str
    source: str
    source_reference: str


_LINE_FIELDS = tuple(field.name for field in fields(OrderLineInput))


def place_order(
    *,
    source: str,
    customer: Customer,
    currency: str,
    amounts: str,
    lines: Sequence[OrderLineInput],
    channel: str,
    draft: bool = False,
) -> Order | None:
    """Places the order for what `source` is selling in this transaction, with
    the next number of the source's prefix, and returns it — or None where the
    company's plan has no orders (`commerce.enabled`), and the source goes on
    as it did before orders. The buyer is the customer as they are now.

    `draft`: the source has not accepted what the customer asked for yet (a
    booking „on request”). The order is written without a number and takes no
    payment until the source accepts it (`accept_order`) — the counter moves
    only for orders the company took, so a request declined leaves no gap."""
    context = require_tenant_context()
    if not connection.in_atomic_block:
        raise RuntimeError("An order is placed inside its source's transaction.")
    if not decide_feature(COMMERCE_ENABLED).allowed:
        return None
    registered = order_source(source)
    _check(amounts, lines, channel)
    organization = Organization.objects.get(pk=context.organization_id)
    if currency != organization.currency:
        raise ValueError("An order is in the company's currency.")
    now = timezone.now()
    totals = _totals(lines)
    order = Order.all_objects.create(
        organization=organization,
        number="" if draft else _next_number(organization, registered.prefix),
        source=source,
        customer=customer,
        buyer_name=customer.display_name,
        buyer_email=customer.email,
        buyer_phone=customer.phone,
        currency=currency,
        amounts=amounts,
        channel=channel,
        placed_at=now,
        **totals,
        # Nothing to pay is paid; from here on the ledger decides.
        status=OrderStatus.DRAFT if draft else _placed_status(totals["gross_minor"]),
    )
    _write_lines(order, lines)
    _audit(
        context,
        order,
        "commerce.order.drafted" if draft else "commerce.order.placed",
        channel=channel,
        gross_minor=order.gross_minor,
    )
    return order


def accept_order(order: Order) -> Order:
    """The source accepted what the customer asked for: the draft gets its
    number — the next of the source's prefix, now — and is to be paid like any
    placed order. An order that already has its number is left as it is."""
    context = require_tenant_context()
    if order.status != OrderStatus.DRAFT:
        return order
    order.number = _next_number(order.organization, order_source(order.source).prefix)
    order.status = _placed_status(order.gross_minor)
    order.version += 1
    order.save(update_fields=["number", "status", "version", "updated_at"])
    _audit(
        context,
        order,
        "commerce.order.placed",
        channel=order.channel,
        gross_minor=order.gross_minor,
    )
    return order


def _placed_status(gross_minor: int) -> str:
    return OrderStatus.AWAITING_PAYMENT if gross_minor > 0 else OrderStatus.PAID


def order_for(source: str, reference: str) -> Order | None:
    """The order that has a line for this record of a source, locked for the
    caller's change."""
    context = require_tenant_context()
    return (
        Order.all_objects.select_for_update()
        .filter(
            organization_id=context.organization_id,
            pk__in=OrderLine.all_objects.filter(
                organization_id=context.organization_id,
                source=source,
                source_reference=reference,
            ).values("order_id"),
        )
        .first()
    )


def order_references(order: Order, source: str) -> list[str]:
    """The records of `source` the order's lines stand for, in any revision."""
    return list(
        OrderLine.all_objects.filter(
            organization_id=order.organization_id, order=order, source=source
        )
        .order_by()
        .values_list("source_reference", flat=True)
        .distinct()
    )


def orders_of(source: str, references: Sequence[str]) -> dict[str, dict[str, Any]]:
    """The orders of a list of a source's records — the visits of a calendar —
    by reference: `id` and `number`, enough for a link. One read for the list.
    Empty for a caller who may not read orders, and where the plan has none."""
    context = require_tenant_context()
    if (
        not references
        or not context.has_permission(ORDERS_READ)
        or not decide_feature(COMMERCE_ENABLED, operation=FeatureOperation.READ).allowed
    ):
        return {}
    return {
        reference: {"id": order_id, "number": number}
        for reference, order_id, number in OrderLine.all_objects.filter(
            organization_id=context.organization_id,
            source=source,
            source_reference__in=list(references),
        )
        .order_by()
        .values_list("source_reference", "order_id", "order__number")
        .distinct()
    }


def reprice_order(order: Order, *, amounts: str, lines: Sequence[OrderLineInput]) -> Order:
    """The source priced what it sold again — a stay moved to dearer days. The
    new lines become the next revision; the earlier ones stay as they were.
    The same lines again change nothing."""
    context = require_tenant_context()
    if order.status == OrderStatus.CANCELED:
        raise ValueError("A canceled order takes no new lines.")
    _check(amounts, lines, order.channel)
    in_force = [
        tuple(getattr(line, name) for name in _LINE_FIELDS)
        for line in OrderLine.all_objects.filter(
            organization_id=order.organization_id, order=order, revision=order.revision
        ).order_by("position")
    ]
    if amounts == order.amounts and in_force == [
        tuple(getattr(line, name) for name in _LINE_FIELDS) for line in lines
    ]:
        return order
    before = order.gross_minor
    order.revision += 1
    order.amounts = amounts
    for name, value in _totals(lines).items():
        setattr(order, name, value)
    # What was paid stays paid: the new amount only moves what is still due.
    order.status = status_for(order, paid_minor(order))
    order.version += 1
    order.save(
        update_fields=[
            "revision",
            "amounts",
            "net_minor",
            "vat_minor",
            "gross_minor",
            "status",
            "version",
            "updated_at",
        ]
    )
    _write_lines(order, lines)
    _audit(
        context,
        order,
        "commerce.order.repriced",
        changes={"gross_minor": {"from": before, "to": order.gross_minor}},
    )
    return order


def cancel_order(order: Order, *, awaited: str = PaymentStatus.CANCELED, reason: str = "") -> Order:
    """The source took back what it sold: its booking was canceled. A payment
    the order still waited for is closed with it (`awaited`: called off, or
    expired when its date did it) and its date no longer comes; `reason` says
    in the company's history why, when it was not a person's decision."""
    context = require_tenant_context()
    if order.status == OrderStatus.CANCELED:
        return order
    order.status = OrderStatus.CANCELED
    order.version += 1
    order.save(update_fields=["status", "version", "updated_at"])
    waiting = Payment.all_objects.filter(
        organization_id=order.organization_id,
        order=order,
        status=PaymentStatus.REQUIRES_PAYMENT,
    )
    PaymentRoute.objects.filter(payment_id__in=list(waiting.values_list("id", flat=True))).delete()
    waiting.update(status=awaited, version=F("version") + 1, updated_at=timezone.now())
    _audit(context, order, "commerce.order.canceled", **({"reason": reason} if reason else {}))
    return order


def strip_buyer(customer: Customer) -> None:
    """What orders keep of a customer goes with the customer (§9): the buyer's
    name and contact, and the stored copies of the mails commerce sent them
    (the transfer's details). Numbers, lines and amounts stay. Called by
    `customers.strip_customer`, inside its transaction and tenant."""
    orders = Order.all_objects.filter(organization_id=customer.organization_id, customer=customer)
    scrub_messages(
        customer.organization_id,
        [f"commerce-order:{order_id}" for order_id in orders.values_list("id", flat=True)],
        to_customers_only=True,
    )
    orders.update(
        buyer_name=customer.display_name,
        buyer_email="",
        buyer_phone="",
        updated_at=timezone.now(),
    )


def holds_amounts(organization_id: UUID) -> bool:
    """Whether the company has orders: their amounts are in its currency."""
    return Order.all_objects.filter(organization_id=organization_id).exists()


def name_orders(organization_id: UUID, ids: Sequence[UUID]) -> dict[UUID, HistoryTarget]:
    """An order in the company's history is its number."""
    return {
        order.id: HistoryTarget(
            # A draft — a request not accepted yet — has no number.
            label=order.number or "—",
            href=f"/panel/orders/{order.id}",
            at=order.placed_at,
        )
        for order in Order.all_objects.filter(organization_id=organization_id, pk__in=ids)
    }


def options() -> dict[str, Any]:
    """What a caller may filter orders by and what their fields can hold."""
    context = authorize_entitled(ORDERS_READ, COMMERCE_ENABLED, operation=FeatureOperation.READ)
    organization = Organization.objects.get(pk=context.organization_id)
    return {
        "currency": organization.currency,
        "statuses": OrderStatus.values,
        "channels": OrderChannel.values,
        "sources": [{"kind": source.kind, "prefix": source.prefix} for source in order_sources()],
        "line_kinds": OrderLineKind.values,
        "tax_rates": TaxRate.values,
        "manual_methods": list(MANUAL_METHODS),
        "transfer_account_set": transfer_account() is not None,
        "max_page_size": MAX_PAGE_SIZE,
    }


def list_orders(
    *,
    page: int = 1,
    page_size: int = 25,
    status: str = "",
    channel: str = "",
    source: str = "",
    customer_id: UUID | None = None,
    query: str = "",
) -> dict[str, Any]:
    """The company's orders, newest first. `query` is a part of a number, of
    the buyer's name or of their e-mail."""
    context = authorize_entitled(ORDERS_READ, COMMERCE_ENABLED, operation=FeatureOperation.READ)
    orders = Order.all_objects.filter(organization_id=context.organization_id)
    if status:
        orders = orders.filter(status=status)
    if channel:
        orders = orders.filter(channel=channel)
    if source:
        orders = orders.filter(source=source)
    if customer_id is not None:
        orders = orders.filter(customer_id=customer_id)
    if query.strip():
        text = query.strip()
        orders = orders.filter(
            Q(number__icontains=text)
            | Q(buyer_name__icontains=text)
            | Q(buyer_email__icontains=text)
        )
    start = (page - 1) * page_size
    return {
        "total": orders.count(),
        "page": page,
        "page_size": page_size,
        "items": [
            _summary(order)
            for order in orders.order_by("-placed_at", "-id")[start : start + page_size]
        ],
    }


def read_order(order_id: UUID) -> dict[str, Any]:
    """One order with its lines in force, what each revision came to, what
    was paid and what its buyer accepted."""
    context = authorize_entitled(ORDERS_READ, COMMERCE_ENABLED, operation=FeatureOperation.READ)
    order = Order.all_objects.filter(organization_id=context.organization_id, pk=order_id).first()
    if order is None:
        raise NotFound("Nie ma takiego zamówienia.")
    return order_detail(order)


def order_detail(order: Order) -> dict[str, Any]:
    """The order as its page shows it. Who may read it is the caller's
    question: a read asks for it, a write answers with it."""
    lines = OrderLine.all_objects.filter(organization_id=order.organization_id, order=order)
    paid = paid_minor(order)
    # What the order's lines stand for, across every revision: a booking.
    records: dict[str, set[str]] = {}
    for source, reference in lines.order_by().values_list("source", "source_reference").distinct():
        records.setdefault(source, set()).add(reference)
    return {
        **_summary(order),
        "customer_id": order.customer_id,
        "buyer_email": order.buyer_email,
        "buyer_phone": order.buyer_phone,
        "amounts": order.amounts,
        "net_minor": order.net_minor,
        "vat_minor": order.vat_minor,
        "revision": order.revision,
        "version": order.version,
        "paid_minor": paid,
        "due_minor": order.gross_minor - paid,
        "payments": payments_of(order),
        "lines": _named(
            order,
            list(
                lines.filter(revision=order.revision)
                .order_by("position")
                .values("position", *_LINE_FIELDS)
            ),
        ),
        "revisions": list(
            lines.values("revision").annotate(gross_minor=Sum("gross_minor")).order_by("revision")
        ),
        # What the buyer accepted when they bought (ADR-073 §9): the journal's
        # lines of the records this order is for.
        "consents": [
            consent
            for source in sorted(records)
            for consent in consents_of(source, sorted(records[source]))
        ],
    }


def _named(order: Order, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each line with what it stands for, as its order's source names it."""
    name = order_source(order.source).targets
    wanted: dict[str, list[str]] = {}
    for line in lines:
        wanted.setdefault(line["source"], []).append(line["source_reference"])
    named = {
        source: name(order.organization_id, source, references) if name else {}
        for source, references in wanted.items()
    }
    for line in lines:
        target = named[line["source"]].get(line["source_reference"])
        line["target"] = (
            None
            if target is None
            else {"label": target.label, "href": target.href, "at": target.at}
        )
    return lines


def _summary(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "number": order.number,
        "status": order.status,
        "channel": order.channel,
        "source": order.source,
        "placed_at": order.placed_at,
        "buyer_name": order.buyer_name,
        "currency": order.currency,
        "gross_minor": order.gross_minor,
    }


def _check(amounts: str, lines: Sequence[OrderLineInput], channel: str) -> None:
    """A source's mistake, not a customer's: it fails loudly."""
    if not lines:
        raise ValueError("An order has at least one line.")
    if amounts not in Amounts.values or channel not in OrderChannel.values:
        raise ValueError("Unknown amounts or channel of an order.")
    for line in lines:
        if line.kind not in OrderLineKind.values or line.tax_rate not in TaxRate.values:
            raise ValueError(f"Unknown kind or tax rate of an order line: {line!r}")
        if line.net_minor + line.vat_minor != line.gross_minor:
            raise ValueError(f"An order line's net and tax do not add up: {line!r}")


def _totals(lines: Sequence[OrderLineInput]) -> dict[str, Any]:
    return {
        "net_minor": sum(line.net_minor for line in lines),
        "vat_minor": sum(line.vat_minor for line in lines),
        "gross_minor": sum(line.gross_minor for line in lines),
    }


def _write_lines(order: Order, lines: Sequence[OrderLineInput]) -> None:
    OrderLine.all_objects.bulk_create(
        OrderLine(
            organization_id=order.organization_id,
            order=order,
            revision=order.revision,
            position=position,
            **{name: getattr(line, name) for name in _LINE_FIELDS},
        )
        for position, line in enumerate(lines, start=1)
    )


def _next_number(organization: Organization, prefix: str) -> str:
    """`R/2026/0001`: the next of the prefix in the company's own year — the
    server's is UTC's, and wrong for an hour or two on New Year's night. The
    counter's row is locked until the order's transaction ends, so a number is
    given once and a rolled-back order leaves no gap."""
    year = timezone.now().astimezone(ZoneInfo(organization.timezone)).year
    OrderCounter.all_objects.get_or_create(organization=organization, prefix=prefix, year=year)
    counter = OrderCounter.all_objects.select_for_update().get(
        organization=organization, prefix=prefix, year=year
    )
    counter.last += 1
    counter.save(update_fields=["last"])
    return f"{prefix}/{year}/{counter.last:04d}"


def _audit(context: TenantContext, order: Order, action: str, **metadata: Any) -> None:
    record_audit(
        organization=order.organization,
        action=action,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="order",
        target_id=order.id,
        # Never the buyer: the history is read by whoever manages settings.
        metadata={"number": order.number, "source": order.source, **metadata},
    )
