from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.shared.customers.api import ConsentKind, DocumentKind

from .models import Amounts, OrderChannel, OrderLineKind, OrderStatus, TaxRate
from .orders import MAX_PAGE_SIZE


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
        help_text="A shortcut for lists; an order with nothing to pay is `paid`.",
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


class OrderSerializer(OrderSummarySerializer):
    customer_id = serializers.UUIDField()
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
    version = serializers.IntegerField(help_text="Goes up with every change of the order.")
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
    max_page_size = serializers.IntegerField(help_text="The longest page a list returns.")
