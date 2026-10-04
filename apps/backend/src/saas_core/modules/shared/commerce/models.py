"""An order — what a company sold to one customer (ADR-073 §3): its number,
the buyer as they were then, and the lines a source handed over ready-priced.
Commerce works out no price: a line carries what the quote or the basket came
to, and a placed line is never changed."""

from __future__ import annotations

import uuid

from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel
from saas_core.modules.shared.customers.api import CUSTOMER_MODEL


class OrderStatus(models.TextChoices):
    """A shortcut for lists; what was paid is decided by the ledger (§3)."""

    DRAFT = "draft", "Szkic"
    AWAITING_PAYMENT = "awaiting_payment", "Do zapłaty"
    PARTIALLY_PAID = "partially_paid", "Opłacone częściowo"
    PAID = "paid", "Opłacone"
    FULFILLED = "fulfilled", "Zrealizowane"
    COMPLETED = "completed", "Zakończone"
    CANCELED = "canceled", "Anulowane"
    REFUNDED = "refunded", "Zwrócone"


class OrderChannel(models.TextChoices):
    """Where the order came from."""

    COMPANY_SITE = "company_site", "Strona firmy"
    CATALOG = "catalog", "Katalog"
    #: Somebody of the company wrote it down for the customer.
    OFFICE = "office", "Biuro"


class OrderLineKind(models.TextChoices):
    BOOKING = "booking", "Rezerwacja"
    PRODUCT = "product", "Produkt"
    EXTRA = "extra", "Dodatek"
    DISCOUNT = "discount", "Rabat"
    VOUCHER = "voucher", "Bon"
    DELIVERY = "delivery", "Dostawa"
    FEE = "fee", "Opłata"


class TaxRate(models.TextChoices):
    """A tax rate as a code, because an exemption is not 0% and „outside VAT”
    is not an exemption (§8). The codes of booking's `VatCode` and the
    warehouse's `VatRate`."""

    STANDARD = "23", "23%"
    REDUCED = "8", "8%"
    SUPER_REDUCED = "5", "5%"
    ZERO = "0", "0%"
    EXEMPT = "zw", "zw."
    OUTSIDE = "np", "np."


class Amounts(models.TextChoices):
    """How a line's unit amount is read: as the company entered it."""

    GROSS = "gross", "Brutto"
    NET = "net", "Netto"


class Order(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: `{prefix}/{year}/{NNNN}`, given when the order is placed; a draft that
    #: waits for the company's answer has none yet.
    number = models.CharField(max_length=32, blank=True)
    #: The registered source that placed it (`register_order_source`).
    source = models.CharField(max_length=64)
    customer = models.ForeignKey(CUSTOMER_MODEL, on_delete=models.PROTECT, related_name="+")
    #: The buyer as they were when the order was placed. Cleared when the
    #: customer is anonymised; amounts and lines stay.
    buyer_name = models.CharField(max_length=160)
    buyer_email = models.EmailField(blank=True)
    buyer_phone = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=3)
    amounts = models.CharField(max_length=8, choices=Amounts.choices)
    #: What the lines in force come to.
    net_minor = models.BigIntegerField(default=0)
    vat_minor = models.BigIntegerField(default=0)
    gross_minor = models.BigIntegerField(default=0)
    status = models.CharField(max_length=24, choices=OrderStatus.choices)
    channel = models.CharField(max_length=16, choices=OrderChannel.choices)
    #: Which of its lines are in force: a change of price writes the next
    #: revision's lines and leaves the earlier ones as they were.
    revision = models.PositiveIntegerField(default=1)
    #: Goes up with every change; a write names the one it saw.
    version = models.PositiveIntegerField(default=1)
    placed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"],
                condition=~models.Q(number=""),
                name="commerce_order_number_uq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "-placed_at"], name="commerce_order_placed_idx"),
            models.Index(fields=["organization", "customer"], name="commerce_order_customer_idx"),
        ]
        ordering = ("organization_id", "-placed_at", "-id")


class OrderLine(TenantScopedModel):
    """One line of one revision. Append-only: the database refuses an update
    and, outside a tenant's erasure, a delete — a correction is the next
    revision's line."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lines")
    revision = models.PositiveIntegerField()
    position = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=16, choices=OrderLineKind.choices)
    #: In the seller's own language — the panel and the invoicing program —
    #: and in the customer's — their e-mails and their own link.
    name = models.CharField(max_length=240)
    customer_name = models.CharField(max_length=240)
    quantity = models.IntegerField()
    #: As the company entered it, gross or net by the order's `amounts`.
    unit_amount_minor = models.BigIntegerField()
    #: What the line comes to. The tax is rounded on the line (ADR-072 §7), so
    #: these are the source's numbers, never `quantity × unit`.
    net_minor = models.BigIntegerField()
    vat_minor = models.BigIntegerField()
    gross_minor = models.BigIntegerField()
    tax_rate = models.CharField(max_length=4, choices=TaxRate.choices)
    #: What the line stands for, as a string and that record's id — never a
    #: foreign key to another module.
    source = models.CharField(max_length=64)
    source_reference = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "revision", "position"], name="commerce_orderline_position_uq"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "source", "source_reference"],
                name="commerce_orderline_source_idx",
            ),
        ]
        ordering = ("order_id", "revision", "position")


class OrderCounter(TenantScopedModel):
    """The last number given for a prefix in a year, per company."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    prefix = models.CharField(max_length=8)
    year = models.PositiveSmallIntegerField()
    last = models.PositiveIntegerField(default=0)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "prefix", "year"], name="commerce_ordercounter_uq"
            ),
        ]


class PaymentKind(models.TextChoices):
    """Which part of what an order comes to a payment is (ADR-073 §4)."""

    #: A part paid ahead of the rest.
    DEPOSIT = "deposit", "Przedpłata"
    BALANCE = "balance", "Dopłata"
    FULL = "full", "Całość"
    #: Held and given back: no part of what the order comes to (§8).
    SECURITY_DEPOSIT = "security_deposit", "Kaucja"


class PaymentMethod(models.TextChoices):
    ONLINE = "online", "Online"
    TRANSFER = "transfer", "Przelew"
    #: At the desk: cash or the company's own card terminal.
    CASH = "cash", "Na miejscu"
    CASH_ON_DELIVERY = "cash_on_delivery", "Za pobraniem"


class PaymentStatus(models.TextChoices):
    REQUIRES_PAYMENT = "requires_payment", "Czeka na wpłatę"
    PROCESSING = "processing", "W toku"
    #: A hold on a card: a security deposit not yet taken.
    AUTHORIZED = "authorized", "Zablokowana"
    SUCCEEDED = "succeeded", "Wpłacona"
    FAILED = "failed", "Nieudana"
    CANCELED = "canceled", "Wycofana"
    EXPIRED = "expired", "Wygasła"


class Payment(TenantScopedModel):
    """Money for an order (ADR-073 §4). What was paid is decided by the ledger;
    this row says which payment it was, how and who marked it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField(max_length=24, choices=PaymentKind.choices)
    method = models.CharField(max_length=24, choices=PaymentMethod.choices)
    status = models.CharField(max_length=24, choices=PaymentStatus.choices)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    #: Until when it is to be paid; empty for one paid at the desk.
    due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    #: The person who marked a payment received by hand. An id, not a key: an
    #: account that goes must not take the payment's history with it.
    recorded_by = models.UUIDField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["organization", "order"], name="commerce_payment_order_idx"),
        ]
        ordering = ("order_id", "created_at", "id")


class LedgerEntryKind(models.TextChoices):
    """ADR-037 §3, with the security deposit's own kinds (ADR-073 §4)."""

    CHARGE = "charge", "Wpłata"
    PROVIDER_FEE = "provider_fee", "Opłata operatora"
    APPLICATION_FEE = "application_fee", "Prowizja platformy"
    REFUND = "refund", "Zwrot"
    REFUND_FEE_REVERSAL = "refund_fee_reversal", "Zwrot prowizji"
    DISPUTE_HOLD = "dispute_hold", "Blokada sporu"
    DISPUTE_RELEASE = "dispute_release", "Zwolnienie sporu"
    DISPUTE_FEE = "dispute_fee", "Opłata za spór"
    PAYOUT = "payout", "Wypłata"
    SECURITY_RECEIVED = "security_received", "Kaucja przyjęta"
    SECURITY_RETURNED = "security_returned", "Kaucja zwrócona"
    SECURITY_RETAINED = "security_retained", "Kaucja zatrzymana"


class LedgerEntry(TenantScopedModel):
    """One line of the money's history. Append-only: the database refuses an
    update and, outside a tenant's erasure, a delete — a mistake is taken back
    by the opposite entry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="ledger")
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger"
    )
    kind = models.CharField(max_length=24, choices=LedgerEntryKind.choices)
    #: Signed: what came in is positive.
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["organization", "order"], name="commerce_ledger_order_idx"),
        ]
        ordering = ("order_id", "occurred_at", "id")


class PaymentRoute(models.Model):
    """Which payment's date comes when (ADR-073 §5): what the deadlines' task
    reads before it knows a tenant. Identifiers and a date, never a customer's
    data — the pattern of booking's `ReminderRoute` (ADR-058 §7). The contract
    is the organization's own, so it outlives whoever placed the order."""

    payment_id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    signed_tenant_context = models.TextField()
    due_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["due_at"],
                condition=models.Q(dispatched_at__isnull=True),
                name="commerce_payroute_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.payment_id)
