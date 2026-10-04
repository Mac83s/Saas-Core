from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.shared.customers.api import ConsentKind, DocumentKind

from .ledger import MANUAL_METHODS
from .models import (
    Amounts,
    OrderChannel,
    OrderLineKind,
    OrderStatus,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
    RefundStatus,
    TaxRate,
)
from .orders import MAX_PAGE_SIZE
from .refunds import REASON_MAX_LENGTH


class OrderQuerySerializer(serializers.Serializer[dict[str, Any]]):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=MAX_PAGE_SIZE, default=25)
    status = serializers.ChoiceField(choices=OrderStatus.values, required=False)
    channel = serializers.ChoiceField(choices=OrderChannel.values, required=False)
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=64,
        required=False,
        help_text="A registered source, as `options` lists them, e.g. `booking`.",
    )
    customer_id = serializers.UUIDField(required=False, help_text="One customer's orders.")
    q = serializers.CharField(
        max_length=120,
        required=False,
        help_text="A part of an order's number, of the buyer's name or of their e-mail.",
    )


class OrderSummarySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    number = serializers.CharField(
        allow_blank=True,
        help_text="`{prefix}/{year}/{NNNN}`, e.g. `R/2026/0001`: per company, source and "
        "year of the company's time zone. Empty for a draft that waits for the company's "
        "answer.",
    )
    status = serializers.ChoiceField(
        choices=OrderStatus.values,
        help_text="A shortcut for lists; an order with nothing to pay is `paid`. An order "
        "its source took back is `canceled` — or `refunded`, once the company gave money "
        "back and the order's terms owe nothing more.",
    )
    channel = serializers.ChoiceField(
        choices=OrderChannel.values,
        help_text="Where it came from: the company's own site or form, the catalogue, or "
        "somebody of the company who wrote it down (`office`).",
    )
    source = serializers.CharField(  # type: ignore[assignment]
        help_text="The registered source that placed it."
    )
    placed_at = serializers.DateTimeField(allow_null=True)
    buyer_name = serializers.CharField(
        help_text="The buyer as they were when the order was placed; the anonymised "
        "customer's placeholder once the customer is removed."
    )
    currency = serializers.CharField(help_text="ISO 4217; the company's currency.")
    gross_minor = serializers.IntegerField(
        help_text="What the lines in force come to, gross, in minor units."
    )


class OrderPageSerializer(serializers.Serializer[dict[str, Any]]):
    total = serializers.IntegerField(help_text="Orders that match the filters.")
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    items = OrderSummarySerializer(many=True)


class OrderLineTargetSerializer(serializers.Serializer[dict[str, Any]]):
    label = serializers.CharField(  # type: ignore[assignment]
        help_text="What the record is called, e.g. the offer's name."
    )
    href = serializers.CharField(
        allow_blank=True, help_text="Where the panel shows it; empty when nowhere."
    )
    at = serializers.DateTimeField(
        allow_null=True, help_text="The record's own time, e.g. a visit's start."
    )


class OrderLineSerializer(serializers.Serializer[dict[str, Any]]):
    position = serializers.IntegerField(help_text="From 1, in the order the source gave.")
    kind = serializers.ChoiceField(choices=OrderLineKind.values)
    name = serializers.CharField(help_text="In the company's own language.")
    customer_name = serializers.CharField(help_text="In the language the customer bought in.")
    quantity = serializers.IntegerField()
    unit_amount_minor = serializers.IntegerField(
        help_text="As the company entered it — gross or net by the order's `amounts` — in "
        "minor units; negative for a discount."
    )
    net_minor = serializers.IntegerField(help_text="What the line comes to, net.")
    vat_minor = serializers.IntegerField(help_text="The line's tax, rounded on the line.")
    gross_minor = serializers.IntegerField(help_text="What the line comes to, gross.")
    tax_rate = serializers.ChoiceField(
        choices=TaxRate.values,
        help_text="A code, not a number: `zw` is exempt and `np` is outside VAT.",
    )
    source = serializers.CharField(  # type: ignore[assignment]
        help_text="What the line stands for, e.g. `booking.appointment`."
    )
    source_reference = serializers.CharField(help_text="That record's id.")
    target = OrderLineTargetSerializer(
        allow_null=True,
        help_text="What the line stands for, as its source names it — a visit with its "
        "time and its day in the calendar. Null when the record is gone.",
    )


class OrderRevisionSerializer(serializers.Serializer[dict[str, Any]]):
    revision = serializers.IntegerField(help_text="From 1; the highest is in force.")
    gross_minor = serializers.IntegerField(help_text="What that revision's lines came to.")


class OrderConsentSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(
        choices=ConsentKind.values,
        help_text="A document the buyer accepted, a marketing consent or a form's field.",
    )
    document_kind = serializers.ChoiceField(
        choices=DocumentKind.choices, allow_null=True, help_text="For a document: which one."
    )
    version = serializers.IntegerField(
        allow_null=True, help_text="For a document: the version whose text was shown."
    )
    locale = serializers.CharField(allow_blank=True, help_text="The language it was shown in.")
    granted = serializers.BooleanField(help_text="False withdraws an earlier consent.")
    created_at = serializers.DateTimeField()


class OrderPaymentSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(
        choices=PaymentKind.values,
        help_text="`full` — the whole at once; `deposit` — a part ahead of the rest; "
        "`balance` — the rest.",
    )
    method = serializers.ChoiceField(
        choices=PaymentMethod.values,
        help_text="`cash` is paid at the desk, in cash or by card on the company's terminal.",
    )
    status = serializers.ChoiceField(
        choices=PaymentStatus.values,
        help_text="`succeeded` counts as paid; `canceled` was marked by mistake and taken "
        "back, or called off with its order; `requires_payment` is awaited until `due_at` "
        "— a `deposit` or `full` the order's source asked for before it confirms, which "
        "is `expired` when not paid by then, or a `balance`, the rest due by a transfer, "
        "which stays awaited after its date and cancels nothing.",
    )
    amount_minor = serializers.IntegerField(
        help_text="In minor units of the order's currency. Of an awaited payment: what is "
        "still awaited."
    )
    due_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Until when an awaited payment is to be paid; null for one marked at the desk.",
    )
    paid_at = serializers.DateTimeField(allow_null=True)
    recorded_by = serializers.CharField(
        allow_blank=True, help_text="Who marked it, by name; empty when no person did."
    )


class OrderRefundSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    method = serializers.ChoiceField(
        choices=MANUAL_METHODS, help_text="How the company gave the money back."
    )
    status = serializers.ChoiceField(
        choices=RefundStatus.values,
        help_text="`succeeded` counts as given back; `canceled` was marked by mistake and "
        "taken back.",
    )
    amount_minor = serializers.IntegerField(help_text="In minor units of the order's currency.")
    reason = serializers.CharField(
        allow_blank=True,
        help_text="The company's own words for a refund its terms did not ask for.",
    )
    refunded_at = serializers.DateTimeField()
    recorded_by = serializers.CharField(allow_blank=True, help_text="Who marked it, by name.")


class OrderSerializer(OrderSummarySerializer):
    customer_id = serializers.UUIDField()
    customer_anonymized_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the order's customer was anonymised — by a person or by the "
        "company's retention setting; null while the customer is still named.",
    )
    buyer_kept_until = serializers.DateField(
        allow_null=True,
        help_text="For an anonymised customer's order that money was taken for: the last "
        "day it still names its buyer. A paid order is the company's sales record and "
        "keeps the buyer for 5 full calendar years after the year of its last ledger "
        "entry, in the company's time zone; the nightly privacy run removes the buyer "
        "afterwards. Null when the customer is not anonymised or the buyer is already gone.",
    )
    buyer_email = serializers.CharField(allow_blank=True)
    buyer_phone = serializers.CharField(allow_blank=True)
    amounts = serializers.ChoiceField(
        choices=Amounts.values, help_text="How `unit_amount_minor` of the lines is read."
    )
    net_minor = serializers.IntegerField()
    vat_minor = serializers.IntegerField()
    revision = serializers.IntegerField(
        help_text="Which lines are in force. A source that prices its record again — a "
        "booking moved to dearer days — writes the next revision."
    )
    version = serializers.IntegerField(
        help_text="Goes up with every change of the order; a write names the one it saw."
    )
    paid_minor = serializers.IntegerField(
        help_text="What the customer has paid: the sum of the order's ledger."
    )
    due_minor = serializers.IntegerField(
        help_text="What is left to pay: `gross_minor` less `paid_minor`. Negative when an "
        "order priced again came to less than was already paid."
    )
    refunded_minor = serializers.IntegerField(
        required=False, help_text="What the company has given back; `paid_minor` is net of it."
    )
    refund_owed_minor = serializers.IntegerField(
        required=False,
        help_text="What is still to be given back by the terms of what was sold, settled "
        "when the order was canceled: what a customer who gave a booking up gets back by "
        "its refund thresholds, or everything when the company called it off. 0 when "
        "nothing is owed — also for an order nobody settled.",
    )
    payments = OrderPaymentSerializer(many=True, help_text="Oldest first.")
    refunds = OrderRefundSerializer(many=True, required=False, help_text="Oldest first.")
    lines = OrderLineSerializer(many=True, help_text="The lines in force.")
    revisions = OrderRevisionSerializer(
        many=True, help_text="Every revision with what it came to, oldest first."
    )
    consents = OrderConsentSerializer(
        many=True,
        help_text="What the buyer accepted when they bought, from the consent journal: "
        "the lines written for the records this order's lines stand for, oldest first. "
        "Empty for an order the company's own people wrote down.",
    )


class OrderSourceSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.CharField(help_text="The value of an order's `source`.")
    prefix = serializers.CharField(help_text="What its orders' numbers start with.")


class CommerceOptionsSerializer(serializers.Serializer[dict[str, Any]]):
    currency = serializers.CharField(help_text="The company's currency: every order is in it.")
    statuses = serializers.ListField(child=serializers.ChoiceField(choices=OrderStatus.values))
    channels = serializers.ListField(child=serializers.ChoiceField(choices=OrderChannel.values))
    sources = OrderSourceSerializer(many=True, help_text="Who places orders in this product.")
    line_kinds = serializers.ListField(child=serializers.ChoiceField(choices=OrderLineKind.values))
    tax_rates = serializers.ListField(child=serializers.ChoiceField(choices=TaxRate.values))
    manual_methods = serializers.ListField(
        child=serializers.ChoiceField(choices=MANUAL_METHODS),
        help_text="The methods of a payment the company marks as received itself.",
    )
    transfer_account_set = serializers.BooleanField(
        required=False,
        help_text="Whether the company gave a bank account for its customers' transfers "
        "(Settings › Customers' payments, group `commerce.transfer`). Without one nothing "
        "can be paid ahead by a transfer.",
    )
    max_page_size = serializers.IntegerField(help_text="The longest page a list returns.")


class PaymentRecordInputSerializer(serializers.Serializer[dict[str, Any]]):
    amount_minor = serializers.IntegerField(
        min_value=1,
        help_text="What the company received, in minor units of the order's currency; at "
        "most what is left to pay (`due_minor`).",
    )
    method = serializers.ChoiceField(
        choices=MANUAL_METHODS,
        help_text="`cash` — at the desk, in cash or by card on the company's terminal; "
        "`transfer` — a transfer the company saw on its account.",
    )
    expected_version = serializers.IntegerField(
        min_value=1, help_text="The order's `version` the caller read."
    )


class PaymentEffectSerializer(serializers.Serializer[dict[str, Any]]):
    amount_minor = serializers.IntegerField()
    paid_minor = serializers.IntegerField(help_text="What would be paid after it.")
    due_minor = serializers.IntegerField(help_text="What would be left to pay.")
    status = serializers.ChoiceField(
        choices=OrderStatus.values, help_text="The order's status after it."
    )
    prepayment_met = serializers.BooleanField(
        required=False,
        help_text="Whether the amount covers the payment the order waits for before its "
        "source confirms: marking it confirms the booking the order is for.",
    )


class RefundRecordInputSerializer(serializers.Serializer[dict[str, Any]]):
    amount_minor = serializers.IntegerField(
        min_value=1,
        help_text="What the company gave back, in minor units of the order's currency; at "
        "most what the customer has paid (`paid_minor`).",
    )
    method = serializers.ChoiceField(
        choices=MANUAL_METHODS,
        help_text="`transfer` — sent back to the customer's account; `cash` — at the desk.",
    )
    reason = serializers.CharField(
        max_length=REASON_MAX_LENGTH,
        required=False,
        allow_blank=True,
        help_text="Why, in the company's own words — needed for a refund beyond what the "
        "order's terms give back (`refund_owed_minor`), 400 `reason_required` without it. "
        "Read on the order's page only; never sent to the customer.",
    )
    expected_version = serializers.IntegerField(
        min_value=1, help_text="The order's `version` the caller read."
    )


class RefundEffectSerializer(serializers.Serializer[dict[str, Any]]):
    amount_minor = serializers.IntegerField()
    paid_minor = serializers.IntegerField(help_text="What would stay paid after it.")
    refund_owed_minor = serializers.IntegerField(
        help_text="What the order's terms would still owe back after it."
    )
    status = serializers.ChoiceField(
        choices=OrderStatus.values, help_text="The order's status after it."
    )
    reason_required = serializers.BooleanField(
        help_text="Whether the amount is beyond what the order's terms give back: the "
        "write then needs a `reason`."
    )


class PaymentVoidInputSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(
        min_value=1, help_text="The order's `version` the caller read."
    )
