from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.options import (
    SETTING_STRATEGIES,
    SETTING_TYPES,
    SETTING_UNITS,
)
from saas_core.modules.core.organizations.serializers import LocalizedTextSerializer

from .cancellation import CANCEL_REASONS, REFUND_THRESHOLDS
from .models import (
    Confirmation,
    ExtraBasis,
    PaymentPolicy,
    RangeUnit,
    RefundBasis,
    StaffChoice,
    TimeModel,
    TimeOffSource,
    VatCode,
)
from .offer_settings import SLOT_STEPS, offer_setting


def _changes() -> serializers.DictField:
    return serializers.DictField(
        child=serializers.JSONField(),
        help_text="What the write changes, per field: `{from, to}`, or `{changed: true}` for "
        "a private value and a list of links. Empty for a new item and for no change.",
    )


class CatalogCreateSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=("location", "staff", "service", "resource"))
    name = serializers.CharField(max_length=160)
    public_slug = serializers.SlugField(max_length=80, required=False)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    resource_kind = serializers.CharField(max_length=80, required=False)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=1440, required=False)
    buffer_before_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    buffer_after_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    minimum_notice_minutes = serializers.IntegerField(min_value=0, required=False)
    #: For a service: the kind of visit a module provides (e.g. from a service
    #: template of the organization's type, ADR-050).
    appointment_kind = serializers.CharField(max_length=64, required=False, allow_blank=True)
    #: For staff: the team member's account this calendar entry stands for.
    membership_id = serializers.UUIDField(required=False, allow_null=True)


class ScheduleCreateSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(
        choices=(
            "availability",
            "time_off",
            "service_staff",
            "service_location",
            "service_resource",
        )
    )
    service_id = serializers.UUIDField(required=False)
    staff_id = serializers.UUIDField(required=False, allow_null=True)
    location_id = serializers.UUIDField(required=False)
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    weekday = serializers.IntegerField(min_value=0, max_value=6, required=False)
    local_start = serializers.TimeField(required=False)
    local_end = serializers.TimeField(required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    reason = serializers.CharField(max_length=160, required=False, allow_blank=True)


class CustomerInputSerializer(serializers.Serializer[dict[str, Any]]):
    display_name = serializers.CharField(min_length=1, max_length=160)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    #: The visitor's language. Not refused when the company does not offer
    #: it: the booking falls back to the company's first language (ADR-071 pkt 21).
    locale = serializers.CharField(
        max_length=10,
        required=False,
        help_text="Język klienta; spoza języków firmy zamieniany na pierwszy język firmy.",
    )


class MaterialInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Produkt z magazynu przy usłudze albo wizycie (ADR-055)."""

    item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0)
    #: `consume` — zużycie na koszt firmy (RW); `sale` — sprzedaż klientowi (WZ).
    mode = serializers.ChoiceField(choices=("consume", "sale"), default="consume")


class MaterialLineSerializer(serializers.Serializer[dict[str, Any]]):
    item_id = serializers.UUIDField()
    name = serializers.CharField()
    unit = serializers.CharField()
    quantity = serializers.CharField()
    mode = serializers.ChoiceField(choices=("consume", "sale"))
    #: Cena sprzedaży netto z chwili zapisu; null dla zużycia.
    unit_price_minor = serializers.IntegerField(allow_null=True)
    currency = serializers.CharField()


class MaterialsInputSerializer(serializers.Serializer[dict[str, Any]]):
    materials = MaterialInputSerializer(many=True)


class ParticipantInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Who comes: so many people of a category, or standard people without one."""

    category_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Null — standard people."
    )
    count = serializers.IntegerField(min_value=1, max_value=1000)


def _participants() -> serializers.ListField:
    return serializers.ListField(
        child=ParticipantInputSerializer(),
        required=False,
        max_length=20,
        help_text="Who comes; omitted — one standard person. The price and a unit's "
        "capacity count them.",
    )


class ExtraPickSerializer(serializers.Serializer[dict[str, Any]]):
    extra_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=100, required=False)


def _extras() -> serializers.ListField:
    return serializers.ListField(
        child=ExtraPickSerializer(),
        required=False,
        max_length=20,
        help_text="The optional extras picked, each with how many (1 when omitted). The "
        "offer's mandatory extras are always charged.",
    )


def _quote_digest() -> serializers.CharField:
    return serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="The `digest` of the quote shown to whoever books. When the price is "
        "another one by now, the answer is 409 `quote_changed` with the new quote in "
        "`detail.quote`. Omitted — the booking takes the price as it is.",
    )


class BookingQuoteLineSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(
        choices=["price", "extra_person", "category", "discount", "extra"],
        help_text="`price` — the offer's price; `extra_person` — people beyond those it "
        "includes; `category` — participants of a category; `discount` — for the length; "
        "`extra` — an extra of the offer.",
    )
    name = serializers.CharField(help_text="In the company's language.")
    customer_name = serializers.CharField(help_text="In the customer's language.")
    quantity = serializers.IntegerField(
        help_text="How many times the amount is charged: nights, people, people × nights."
    )
    unit_amount_minor = serializers.IntegerField(
        help_text="As the price list has it — gross or net by the quote's `amounts`; "
        "negative for a discount."
    )
    net_minor = serializers.IntegerField()
    vat_minor = serializers.IntegerField()
    gross_minor = serializers.IntegerField()
    vat_code = serializers.ChoiceField(choices=VatCode.choices)
    time_units = serializers.IntegerField(
        allow_null=True, help_text="Nights or days the line covers; null — charged once."
    )
    people = serializers.IntegerField(allow_null=True)
    category_id = serializers.UUIDField(allow_null=True)
    price_rule_id = serializers.UUIDField(allow_null=True)
    percent = serializers.IntegerField(allow_null=True, help_text="A discount's percent.")
    extra_id = serializers.UUIDField(allow_null=True)


class QuotePrepaymentSerializer(serializers.Serializer[dict[str, Any]]):
    """What is paid before the booking is confirmed (ADR-073 §5)."""

    kind = serializers.ChoiceField(
        choices=["deposit", "full"],
        help_text="`deposit` — a part ahead, the rest on site; `full` — the whole.",
    )
    amount_minor = serializers.IntegerField(help_text="Gross, in minor units.")
    transfer_due_days = serializers.IntegerField(
        help_text="How many days the customer has to pay by a transfer before the booking "
        "expires; never past the booking's start."
    )
    balance_due_days_before = serializers.IntegerField(
        required=False,
        help_text="With `deposit`: the rest is due by a transfer this many days before the "
        "booking's start. Absent: the rest is paid on site.",
    )


class RefundThresholdSerializer(serializers.Serializer[dict[str, Any]]):
    """One refund threshold of an offer (ADR-072 §8)."""

    min_days_before = serializers.IntegerField(
        min_value=REFUND_THRESHOLDS["min_days_before"]["minimum"],
        max_value=REFUND_THRESHOLDS["min_days_before"]["maximum"],
        help_text="At least this many whole days of the company's calendar before the "
        "booking's start.",
    )
    refund_percent = serializers.IntegerField(
        min_value=REFUND_THRESHOLDS["refund_percent"]["minimum"],
        max_value=REFUND_THRESHOLDS["refund_percent"]["maximum"],
        help_text="The percent that goes back to a customer who gives the booking up then.",
    )


class QuoteCancellationSerializer(serializers.Serializer[dict[str, Any]]):
    """What giving the booking up gives back, as the offer said when it was
    booked (ADR-072 §8, ADR-073 §8)."""

    applies_to = serializers.ChoiceField(
        choices=RefundBasis.values,
        help_text="`deposit` — the thresholds are counted on the prepayment and anything "
        "else paid goes back whole; `paid` — on everything paid.",
    )
    refunds = RefundThresholdSerializer(
        many=True,
        help_text="The longest notice first; less notice than the last row gives nothing "
        "back.",
    )


class BookingQuoteSerializer(serializers.Serializer[dict[str, Any]]):
    """A booking's price (ADR-072 §7): whole minor units, the tax worked out on
    each line. No lines — the offer has no price list."""

    currency = serializers.CharField()
    amounts = serializers.ChoiceField(
        choices=["gross", "net"], help_text="How `unit_amount_minor` is read."
    )
    lines = BookingQuoteLineSerializer(many=True)
    participants = ParticipantInputSerializer(many=True)
    extras = ExtraPickSerializer(many=True, help_text="The optional extras picked.")
    security_deposit_minor = serializers.IntegerField(
        help_text="Held and given back: beside the totals, never in them."
    )
    payment_policy = serializers.ChoiceField(
        choices=PaymentPolicy.choices,
        help_text="What the customer is told about paying. An offer that asks for money "
        "ahead where none can be paid ahead says `on_site`.",
    )
    prepayment = QuotePrepaymentSerializer(
        allow_null=True,
        required=False,
        help_text="What a booking at this price waits for before it is confirmed; null — "
        "nothing, it is confirmed at once.",
    )
    cancellation = QuoteCancellationSerializer(
        allow_null=True,
        required=False,
        help_text="The refund thresholds a booking at this price is given up under; null "
        "or absent — the offer has none, and everything paid goes back.",
    )
    net_minor = serializers.IntegerField()
    vat_minor = serializers.IntegerField()
    gross_minor = serializers.IntegerField(help_text="What the customer pays.")
    digest = serializers.CharField(
        help_text="Of the price, the same in every language; send it back as `quote_digest`."
    )


class BookingQuoteInputSerializer(serializers.Serializer[dict[str, Any]]):
    """What to price: a visit at `starts_at`, or a stay from `start_date` to
    `end_date` in a unit or a group."""

    service_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    group_id = serializers.UUIDField(required=False, allow_null=True)
    participants = _participants()
    extras = _extras()
    locale = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10,
        help_text="The customer's language, for `customer_name`; omitted — the company's.",
    )
    price_only = serializers.BooleanField(
        required=False,
        help_text="Only what the price list says for that time, whether or not it could be "
        "booked: the offer may still be switched off, the unit taken, a season's rule broken. "
        "For a preview of the price list; a booking is priced without it.",
    )


class AppointmentCreateSerializer(serializers.Serializer[dict[str, Any]]):
    service_id = serializers.UUIDField()
    #: Omitted: the server picks the least busy free person (ADR-058 §4).
    staff_id = serializers.UUIDField(required=False, allow_null=True)
    #: The people, the lead first; fewer than the service needs make a vacancy.
    staff_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=10)
    #: Choose only among this team's free members (with no people named).
    team_id = serializers.UUIDField(required=False, allow_null=True)
    location_id = serializers.UUIDField()
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    starts_at = serializers.DateTimeField()
    customer = CustomerInputSerializer()
    #: Pominięte: produkty z usługi. Podane: dokładnie te (wymaga inventory.use).
    materials = MaterialInputSerializer(many=True, required=False)
    #: „Uwagi”: what the customer wants the company to know (never in an e-mail).
    customer_notes = serializers.CharField(required=False, allow_blank=True, max_length=500)
    place_town = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
        help_text="„Miejsce wizyty”: the town, when the visit is not at the company's location.",
    )
    place_address = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=240,
        help_text="Street and number in that town; optional, and only with a town.",
    )
    participants = _participants()
    extras = _extras()
    quote_digest = _quote_digest()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _street_needs_town(
            attrs.get("place_town", ""), attrs.get("place_address", ""), "place_town"
        )
        return attrs


def _street_needs_town(town: str, address: str, town_field: str) -> None:
    if address.strip() and not town.strip():
        raise serializers.ValidationError({town_field: "Podaj miejscowość do tej ulicy."})


class VisitPlaceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """„Miejsce wizyty” of a booked visit; both empty clear it (ADR-066)."""

    town = serializers.CharField(allow_blank=True, max_length=120, help_text="The town.")
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=240,
        help_text="Street and number; optional, and only with a town.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _street_needs_town(attrs.get("town", ""), attrs.get("address", ""), "town")
        return attrs


class VisitPlaceSuggestionSerializer(serializers.Serializer[dict[str, Any]]):
    """A place the company keeps (a farm, say); choosing it fills the visit's place."""

    name = serializers.CharField(help_text="What the office knows the place by.")
    town = serializers.CharField()
    address = serializers.CharField()


class VisitPlaceSuggestionListSerializer(serializers.Serializer[dict[str, Any]]):
    items = VisitPlaceSuggestionSerializer(many=True)


class PublicConsentsInputSerializer(serializers.Serializer[dict[str, Any]]):
    """What the customer accepted on the booking form (ADR-073 §9)."""

    documents = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=10,
        help_text="The `text_id` of every document shown and accepted, as `GET …/consents/` "
        "gave them. One in force that is missing here, or another text by now, is 409 "
        "`documents_changed` with the documents to show in `detail.documents`.",
    )


class PublicAppointmentCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """The customer names the service, place and time, and — where the service
    lets them — a team or a person shown to customers; everything else is the
    server's (ADR-058 §4, §8)."""

    service_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    customer = CustomerInputSerializer()
    team_id = serializers.UUIDField(required=False, allow_null=True)
    person_id = serializers.UUIDField(required=False, allow_null=True)
    #: „Uwagi”: for the company's eyes only, never in an e-mail (answer 1A).
    customer_notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    extras = _extras()
    quote_digest = _quote_digest()
    consents = PublicConsentsInputSerializer(
        required=False,
        help_text="The company's documents the customer accepted; required as soon as the "
        "company has one in force in the booking's language.",
    )


class PublicQuoteInputSerializer(serializers.Serializer[dict[str, Any]]):
    """The visit a customer is about to book, to be priced."""

    service_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    extras = _extras()
    locale = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10,
        help_text="The customer's language, for the lines' names; one the company does not "
        "have is answered in its own.",
    )


class PublicQuoteLineSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(
        choices=["price", "extra_person", "category", "discount", "extra"]
    )
    name = serializers.CharField(help_text="In the customer's language.")
    quantity = serializers.IntegerField()
    gross_minor = serializers.IntegerField(help_text="What the line comes to, tax included.")


class PublicQuoteSerializer(serializers.Serializer[dict[str, Any]]):
    """A price as the customer reads it: gross, in whole minor units."""

    currency = serializers.CharField()
    lines = PublicQuoteLineSerializer(many=True)
    gross_minor = serializers.IntegerField(help_text="What the customer pays.")
    security_deposit_minor = serializers.IntegerField(
        help_text="Held and given back; not part of `gross_minor`."
    )
    payment_policy = serializers.ChoiceField(
        choices=PaymentPolicy.choices,
        help_text="`on_site` — the customer pays at the visit; `none` — nothing is said; "
        "`transfer`, `deposit`, `full` — a part or the whole is paid ahead, see "
        "`prepayment`.",
    )
    prepayment = QuotePrepaymentSerializer(
        allow_null=True,
        required=False,
        help_text="What the customer pays before the booking is confirmed; null — nothing.",
    )
    cancellation = QuoteCancellationSerializer(
        allow_null=True,
        required=False,
        help_text="What giving the booking up gives back of what was paid; null — the "
        "service has no thresholds, and everything paid goes back.",
    )
    digest = serializers.CharField(help_text="Send it back as `quote_digest` when booking.")


class PublicQuoteAnswerSerializer(serializers.Serializer[dict[str, Any]]):
    quote = PublicQuoteSerializer(
        allow_null=True, help_text="Null — the service has no price to show."
    )


class RescheduleSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    quote_digest = _quote_digest()


class CrewMemberSerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    #: The person's account, for "my visits" (null: no account).
    membership_id = serializers.UUIDField(allow_null=True)
    lead = serializers.BooleanField()


class TeamRefSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AppointmentOrderSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField(help_text="`GET /commerce/orders/{id}/`.")
    number = serializers.CharField()


class AppointmentSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    service_name = serializers.CharField()
    service_id = serializers.UUIDField(help_text="The offer it was booked from.")
    status = serializers.CharField(
        help_text=(
            "`confirmed`, `completed`, `canceled`, `no_show` (the customer did not come), "
            "`pending_request` — a customer's booking of an offer taken on request: it holds "
            "its time until `hold_expires_at` and waits for the company to accept or decline "
            "it (`…/accept/`, `…/decline/`) — or `pending_payment`: the offer asks for money "
            "before confirming, and the booking holds its time until `hold_expires_at` — it "
            "is confirmed when the company marks the payment in its order. Either expires "
            "(`canceled`) when the date comes first."
        )
    )
    hold_expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Until when a `pending_request` booking waits for the company's answer, "
        "or a `pending_payment` one for its payment; null otherwise.",
    )
    order = AppointmentOrderSerializer(
        required=False,
        allow_null=True,
        help_text="The booking's order, for a caller who may read orders "
        "(`commerce.orders.read`); null for a booking without a price, without orders in "
        "the company's plan, or for anybody else.",
    )
    passed = serializers.BooleanField(
        help_text=(
            "Confirmed and its planned end is behind us: nobody closed it with complete or "
            "no-show yet (UX-031). It is no longer ahead, and a vacancy on it is nobody's work."
        )
    )
    closes_explicitly = serializers.BooleanField(
        help_text=(
            "Its module closes visits of this kind itself (e.g. when field work ends): a passed "
            "one is not finished rather than done, and only a completed one counts as done."
        )
    )
    customer_name = serializers.CharField()
    title = serializers.CharField(
        allow_blank=True,
        help_text=(
            "What the module that owns the visit's detail calls it (a herd "
            "visit's farm), shown before the customer's name; empty when none."
        ),
    )
    staff_id = serializers.UUIDField(
        allow_null=True, help_text="The lead; null for a stay, which takes a unit, nobody."
    )
    staff_name = serializers.CharField(allow_null=True)
    #: The calendar entry's team member, for "my visits" (null: no account).
    staff_membership_id = serializers.UUIDField(allow_null=True)
    time_model = serializers.ChoiceField(
        choices=[TimeModel.SLOT.value, TimeModel.RANGE.value],
        help_text="`slot` — a visit; `range` — a stay or rental from–to.",
    )
    location_name = serializers.CharField()
    place = serializers.CharField(
        allow_null=True,
        help_text=(
            "Where the visit takes place, as a town: the visit's own place_town, "
            "else what the module that owns the visit's detail knows (a field "
            "visit's farm). Null when neither says."
        ),
    )
    place_town = serializers.CharField(
        help_text="The visit's own „Miejsce wizyty”: its town, or empty."
    )
    #: Null when the caller may not see it: only who plans visits and the
    #: people on this visit do (ADR-067).
    customer_phone = serializers.CharField(
        allow_null=True,
        help_text="The customer's phone, for whoever plans visits and the people on it.",
    )
    customer_email = serializers.CharField(
        allow_null=True,
        help_text="The customer's e-mail, for whoever plans visits and the people on it.",
    )
    appointment_kind = serializers.CharField(
        help_text="The kind of the visit's service; a product's own kinds name its visits.",
    )
    flags = serializers.ListField(
        child=serializers.CharField(),
        help_text="Marks a product puts on the visit's card, e.g. farm_missing (ADR-067).",
    )
    place_address = serializers.CharField(
        allow_blank=True,
        help_text=(
            "Street and number of the visit's own place, or empty; empty also for "
            "whoever may not see the customer's phone."
        ),
    )
    resource_name = serializers.CharField(allow_null=True)
    resource_id = serializers.UUIDField(
        allow_null=True, help_text="The unit or room it takes, if any."
    )
    #: Tylko w panelu firmy; klient w self-service tego nie dostaje.
    materials = MaterialLineSerializer(many=True, required=False)
    #: False, gdy materiał tej wizyty rozlicza jej moduł (ADR-055) albo nie ma magazynu.
    takes_materials = serializers.BooleanField(required=False)
    self_service_token = serializers.CharField(required=False, allow_null=True)
    #: Everybody on the visit, the lead first (ADR-058 §2).
    crew = CrewMemberSerializer(many=True)
    #: How many people the visit was booked for.
    staff_required = serializers.IntegerField()
    #: A vacancy: fewer people than required, or no lead.
    needs_assignment = serializers.BooleanField()
    #: The system chose the people; the office has not looked yet.
    auto_assigned = serializers.BooleanField()
    #: Name it in an assignment (`expected_version`).
    crew_version = serializers.IntegerField()
    #: Why it waits in „Do przydzielenia”, and since when.
    queue_reason = serializers.CharField()
    queued_at = serializers.DateTimeField(allow_null=True)
    #: The team the customer chose (null also once that team was removed).
    requested_team = TeamRefSerializer(allow_null=True)
    #: The person the customer chose on the public form.
    requested_staff_id = serializers.UUIDField(allow_null=True)
    #: „Uwagi” from the customer. Panel only; never in an e-mail.
    customer_notes = serializers.CharField()
    quote = BookingQuoteSerializer(
        required=False,
        allow_null=True,
        help_text="The price frozen when the booking was made or last moved; null for a "
        "booking from before quotes.",
    )


class PublicSelfServiceSerializer(serializers.Serializer[dict[str, Any]]):
    """What the customer's link may still do, by the booking's own terms (B4)."""

    reschedule = serializers.BooleanField()
    cancel = serializers.BooleanField()
    until = serializers.DateTimeField(
        allow_null=True,
        help_text="Until when the link allows changes; null when it allows none.",
    )


class PublicAwaitedPaymentSerializer(serializers.Serializer[dict[str, Any]]):
    """The transfer a booking waits for (ADR-073 §5)."""

    kind = serializers.ChoiceField(
        choices=["deposit", "full", "balance"],
        required=False,
        help_text="`deposit`, `full` — awaited before the booking is confirmed; `balance` "
        "— the rest of a confirmed booking's price, which calls nothing off when late.",
    )
    number = serializers.CharField(help_text="The order's number: the transfer's title.")
    amount_minor = serializers.IntegerField(help_text="Gross, in minor units.")
    currency = serializers.CharField()
    due_at = serializers.DateTimeField(help_text="Until when the payment is awaited.")
    account_holder = serializers.CharField()
    account_number = serializers.CharField()
    bank_name = serializers.CharField(allow_blank=True)


class PublicSettlementSerializer(serializers.Serializer[dict[str, Any]]):
    """What comes back of what the customer paid (ADR-073 §8)."""

    currency = serializers.CharField()
    paid_minor = serializers.IntegerField(help_text="What the customer has paid.")
    refund_minor = serializers.IntegerField(
        help_text="Of a booking not canceled: what giving it up now would give back, by "
        "the thresholds it was booked under. Of a canceled one: what the company is still "
        "to give back."
    )


class SettlementTermsSerializer(serializers.Serializer[dict[str, Any]]):
    refund_minor = serializers.IntegerField(help_text="What the thresholds give back now.")
    percent = serializers.IntegerField(
        help_text="The percent of the threshold the notice reaches; 100 without thresholds."
    )
    days_before = serializers.IntegerField(
        help_text="Whole days of the company's calendar until the booking's start."
    )


class AppointmentSettlementSerializer(serializers.Serializer[dict[str, Any]]):
    """A booking's money for whoever is about to call it off (ADR-073 §8)."""

    currency = serializers.CharField()
    paid_minor = serializers.IntegerField(help_text="What the customer has paid.")
    refund_owed_minor = serializers.IntegerField(
        help_text="Of a canceled booking: what is still to be given back."
    )
    balance_overdue = serializers.BooleanField(
        help_text="The rest of the price was due by a transfer and is not paid: the company "
        "may call the booking off with the reason `balance_overdue`."
    )
    by_terms = SettlementTermsSerializer(
        help_text="What the booking's own refund thresholds give back now — what the "
        "customer gets when they give it up, or when the company calls it off for a late "
        "balance. The company's own calling off for any other reason gives everything back."
    )


class AppointmentSettlementAnswerSerializer(serializers.Serializer[dict[str, Any]]):
    settlement = AppointmentSettlementSerializer(
        allow_null=True, help_text="Null — nothing was paid, there is nothing to settle."
    )


class AppointmentDeclineSerializer(serializers.Serializer[dict[str, Any]]):
    reason = serializers.CharField(
        max_length=300,
        required=False,
        allow_blank=True,
        help_text="The company's own words to the customer about why it cannot take the "
        "booking — optional, plain text up to 300 characters, without a link or an address "
        "(400 `links`). It goes into the customer's e-mail and is kept nowhere else.",
    )


class AppointmentCancelSerializer(serializers.Serializer[dict[str, Any]]):
    reason = serializers.ChoiceField(
        choices=CANCEL_REASONS,
        required=False,
        help_text="`balance_overdue` — the rest of the price was not paid by its date: "
        "what the customer paid is then settled by the booking's refund thresholds, as when "
        "they give it up themselves (400 `balance_not_overdue` when no balance is late). "
        "Without a reason the company gives everything back.",
    )


class PublicAppointmentSerializer(serializers.Serializer[dict[str, Any]]):
    """What the customer sees of their visit: no stock, and of the people
    only the team they chose or a name shown to customers (ADR-058 §8)."""

    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    service_name = serializers.CharField()
    location_name = serializers.CharField()
    time_model = serializers.CharField(
        required=False,
        help_text="`range` — a stay or a rental, told by its days and moved by its dates "
        "(`…/stay/`); `slot` — a visit at a time.",
    )
    range_unit = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="With `range`: `night` — `ends_at` is the departure day's check-out; "
        "`day` — `ends_at` is on the last day. Empty for a visit.",
    )
    unit_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="The unit of a stay (a cottage, a car), in the customer's language where "
        "translated; null for a visit.",
    )
    status = serializers.CharField(
        help_text="`pending_request`: the booking waits for the company's answer until "
        "`hold_expires_at`; `pending_payment`: it waits for the payment in `payment` until "
        "`hold_expires_at`; either then expires. Otherwise `confirmed`, `completed`, "
        "`canceled` or `no_show`."
    )
    hold_expires_at = serializers.DateTimeField(required=False, allow_null=True)
    payment = PublicAwaitedPaymentSerializer(
        required=False,
        allow_null=True,
        help_text="What the customer is still to transfer, and where — before the booking "
        "is confirmed, or the rest of a confirmed one's price; null when nothing is awaited.",
    )
    settlement = PublicSettlementSerializer(
        required=False,
        allow_null=True,
        help_text="What comes back of what the customer paid; null when nothing was paid.",
    )
    #: The team the customer chose, by name.
    team_name = serializers.CharField(allow_null=True)
    #: „Przyjmie Cię”: the lead's name when it is shown to customers.
    person_name = serializers.CharField(allow_null=True)
    self_service_token = serializers.CharField(required=False)
    self_service = PublicSelfServiceSerializer()
    quote = PublicQuoteSerializer(
        required=False,
        allow_null=True,
        help_text="The price frozen when the visit was booked or last moved; null when "
        "the service had none.",
    )


class AppointmentListSerializer(serializers.Serializer[dict[str, Any]]):
    items = AppointmentSerializer(many=True)


class QueueItemSerializer(AppointmentSerializer):
    """A visit in „Do przydzielenia”, with what the office phones or reads."""

    customer_phone = serializers.CharField()
    customer_email = serializers.CharField()


class QueueSerializer(serializers.Serializer[dict[str, Any]]):
    items = QueueItemSerializer(many=True)


class OverviewSerializer(serializers.Serializer[dict[str, Any]]):
    #: People who take visits: an active entry with a service and hours.
    bookable_staff = serializers.IntegerField()
    teams = serializers.IntegerField()
    #: Visits in „Do przydzielenia”; null for whoever may not assign.
    waiting = serializers.IntegerField(allow_null=True)
    requests = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="Customers' requests waiting for the company's answer. Null for whoever "
        "may not answer them, and where the company takes nothing on request and nothing "
        "waits: „Prośby” has no use then.",
    )
    stays = serializers.BooleanField(
        help_text="The company sells an offer booked by dates: „Obłożenie” has a use."
    )


class CrewInputSerializer(serializers.Serializer[dict[str, Any]]):
    #: Exactly the people who should be on the visit; the same ones again is „Zostaw”.
    staff_ids = serializers.ListField(child=serializers.UUIDField(), max_length=10)
    #: One of `staff_ids`; omitted: the first of them.
    lead_id = serializers.UUIDField(required=False, allow_null=True)
    #: The `crew_version` the office looked at (ADR-058 §9).
    expected_version = serializers.IntegerField(min_value=0)
    #: „Powiadom pracowników”: in the app and by e-mail.
    notify = serializers.BooleanField(default=True)


class WorkRangeSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class CandidateSerializer(serializers.Serializer[dict[str, Any]]):
    """One person for one visit („kto jest wolny”, ADR-058 §9)."""

    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    team_ids = serializers.ListField(child=serializers.UUIDField())
    #: active, suspended, invited or none.
    account = serializers.CharField()
    #: Null for whoever may not see it (management and the person only).
    phone = serializers.CharField(allow_null=True)
    does_service = serializers.BooleanField()
    #: free, busy, time_off, off_schedule — never the reason of an absence.
    state = serializers.CharField()
    until = serializers.DateTimeField(allow_null=True)
    hours = WorkRangeSerializer(many=True)
    on_visit = serializers.BooleanField()
    lead = serializers.BooleanField()
    day_visits = serializers.IntegerField()
    day_minutes = serializers.IntegerField()
    next_free = serializers.DateTimeField(allow_null=True)


class CandidateListSerializer(serializers.Serializer[dict[str, Any]]):
    items = CandidateSerializer(many=True)


class CandidateQuerySerializer(serializers.Serializer[dict[str, Any]]):
    #: Everybody in the company, not only who does the service („Pokaż: Wszyscy”).
    everyone = serializers.BooleanField(default=False)


class TeamSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    member_ids = serializers.ListField(child=serializers.UUIDField())


class TeamListSerializer(serializers.Serializer[dict[str, Any]]):
    items = TeamSerializer(many=True)


class TeamInputSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160)
    member_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100)


class TeamUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, required=False)
    member_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=100, required=False
    )


_REFUNDS_HELP = (
    "What a customer who gives a booking of this service up gets back of what they paid: "
    "rows „at least `min_days_before` days before the start → `refund_percent` back”, the "
    "longest notice first, at most six; less notice than the last row gives nothing back. "
    "Empty: no thresholds — everything paid goes back. Frozen in each booking. A booking "
    "the company itself calls off gives everything back, whatever the thresholds."
)


class ServiceSetupSerializer(serializers.Serializer[dict[str, Any]]):
    """A service as Ustawienia › Usługi i grafik edits it (team phase 3c)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    appointment_kind = serializers.CharField()
    time_model = serializers.ChoiceField(choices=[TimeModel.SLOT.value, TimeModel.RANGE.value])
    range_unit = serializers.CharField(help_text="`night`, `day`; empty for a `slot` service.")
    range_start_local = serializers.TimeField(allow_null=True)
    range_end_local = serializers.TimeField(allow_null=True)
    group_ids = serializers.ListField(child=serializers.UUIDField())
    duration_minutes = serializers.IntegerField(allow_null=True)
    buffer_before_minutes = serializers.IntegerField()
    buffer_after_minutes = serializers.IntegerField()
    minimum_notice_minutes = serializers.IntegerField()
    staff_count = serializers.IntegerField()
    public_staff_choice = serializers.CharField()
    slot_step_minutes = serializers.IntegerField(
        help_text=offer_setting("slot_step_minutes").model_description
    )
    online = serializers.BooleanField(help_text=offer_setting("online").model_description)
    confirmation = serializers.ChoiceField(
        choices=Confirmation.choices,
        required=False,
        help_text=offer_setting("confirmation").model_description,
    )
    response_hours = serializers.IntegerField(
        required=False, help_text=offer_setting("response_hours").model_description
    )
    payment_policy = serializers.ChoiceField(
        choices=PaymentPolicy.choices, help_text=offer_setting("payment_policy").model_description
    )
    deposit_percent = serializers.IntegerField(
        required=False, help_text=offer_setting("deposit_percent").model_description
    )
    transfer_due_days = serializers.IntegerField(
        required=False, help_text=offer_setting("transfer_due_days").model_description
    )
    balance_due_days_before = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=offer_setting("balance_due_days_before").model_description,
    )
    cancellation_refunds = RefundThresholdSerializer(
        many=True, required=False, help_text=_REFUNDS_HELP
    )
    cancellation_applies_to = serializers.ChoiceField(
        choices=RefundBasis.values,
        required=False,
        help_text=offer_setting("cancellation_applies_to").model_description,
    )
    active = serializers.BooleanField()
    draft = serializers.BooleanField(
        help_text="Never switched on since it was made; only a draft can be discarded."
    )
    preset_id = serializers.CharField(
        allow_null=True, help_text="The preset the offer was started from, if any."
    )
    preset_version = serializers.IntegerField(allow_null=True)
    #: Who does it; the places it is offered at; the resources a visit takes
    #: one of.
    staff_ids = serializers.ListField(child=serializers.UUIDField())
    location_ids = serializers.ListField(child=serializers.UUIDField())
    resource_ids = serializers.ListField(child=serializers.UUIDField())
    materials = MaterialInputSerializer(many=True)
    #: False when the visit's module takes its own material (ADR-055).
    takes_materials = serializers.BooleanField()
    version = serializers.IntegerField(
        help_text="The service's version; a change names it (`expected_version`)."
    )
    future_bookings = serializers.IntegerField(
        help_text=(
            "Bookings of this service that will still happen (from now, neither canceled, "
            "completed nor a no-show). Switching the service off leaves them as they are."
        )
    )


class AppointmentKindSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="The `appointment_kind` a service sells.")
    label = serializers.CharField(help_text="Its name, as the module declares it.")  # type: ignore[assignment]


class PlaceSetupSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    address = serializers.CharField()
    active = serializers.BooleanField()
    online = serializers.BooleanField(
        help_text="Shown on the booking form on the company's site (B2)."
    )
    version = serializers.IntegerField(
        help_text="The place's version; a change names it (`expected_version`)."
    )


class ResourceSetupSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    active = serializers.BooleanField()
    group_id = serializers.UUIDField(
        allow_null=True, help_text="The pool of identical units it belongs to, if any."
    )
    location_id = serializers.UUIDField(
        allow_null=True, help_text="Where the unit is, if anywhere."
    )
    capacity = serializers.IntegerField(allow_null=True, help_text="How many people it takes.")
    description = serializers.CharField()
    version = serializers.IntegerField(
        help_text="The resource's version; a change names it (`expected_version`)."
    )


class GroupSetupSerializer(serializers.Serializer[dict[str, Any]]):
    """A pool of identical units (ADR-072 §3)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    active = serializers.BooleanField()
    version = serializers.IntegerField(
        help_text="The group's version; a change names it (`expected_version`)."
    )


class ServiceSetupPreviewSerializer(ServiceSetupSerializer):
    """The service as the write would leave it; nothing is saved."""

    changes = _changes()


class PlaceSetupPreviewSerializer(PlaceSetupSerializer):
    """The place as the write would leave it; nothing is saved."""

    changes = _changes()


class ResourceSetupPreviewSerializer(ResourceSetupSerializer):
    """The resource as the write would leave it; nothing is saved."""

    changes = _changes()


class GroupSetupPreviewSerializer(GroupSetupSerializer):
    """The group as the write would leave it; nothing is saved."""

    changes = _changes()


class SetupPersonSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    hours_version = serializers.IntegerField(
        help_text="The version of the person's week, for a change of their hours."
    )


class SetupOptionValueSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.CharField()
    label = LocalizedTextSerializer()  # type: ignore[assignment]


class SetupOptionSerializer(serializers.Serializer[dict[str, Any]]):
    """One setting of an offer, in the shape of the settings registry (ADR-078)."""

    key = serializers.CharField(help_text="`booking.offer.<field>`; the field is the key's tail.")
    type = serializers.ChoiceField(choices=SETTING_TYPES)
    minimum = serializers.IntegerField(allow_null=True)
    maximum = serializers.IntegerField(allow_null=True)
    unit = serializers.ChoiceField(choices=SETTING_UNITS, allow_null=True)
    values = SetupOptionValueSerializer(
        many=True, allow_null=True, help_text="The variants of an `enum`, in order."
    )
    default = serializers.JSONField(help_text="What a new offer gets when nothing is said.")
    label = LocalizedTextSerializer()  # type: ignore[assignment]
    help = LocalizedTextSerializer(allow_null=True)
    description = serializers.CharField(help_text="What the value does, for the assistant.")
    scopes = serializers.ListField(child=serializers.CharField())
    depends_on = serializers.CharField(allow_null=True)
    strategy = serializers.ChoiceField(choices=SETTING_STRATEGIES)


class _BoundsSerializer(serializers.Serializer[dict[str, Any]]):
    minimum = serializers.IntegerField()
    maximum = serializers.IntegerField()


class RefundThresholdBoundsSerializer(serializers.Serializer[dict[str, Any]]):
    max_rows = serializers.IntegerField(help_text="How many thresholds an offer may have.")
    min_days_before = _BoundsSerializer()
    refund_percent = _BoundsSerializer()


class SetupOptionsSerializer(serializers.Serializer[dict[str, Any]]):
    keys = SetupOptionSerializer(many=True)
    refund_thresholds = RefundThresholdBoundsSerializer(
        required=False,
        help_text="The bounds of an offer's `cancellation_refunds` — a list, so not one of "
        "`keys`.",
    )
    cancel_reasons = serializers.ListField(
        child=serializers.ChoiceField(choices=CANCEL_REASONS),
        required=False,
        help_text="The reasons the company may give when it calls a booking off that change "
        "what goes back to the customer.",
    )


class PresetTextSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField()
    description = serializers.CharField()


class PresetLabelsSerializer(serializers.Serializer[dict[str, Any]]):
    pl = PresetTextSerializer()
    en = PresetTextSerializer()


class PresetSerializer(serializers.Serializer[dict[str, Any]]):
    """What a company may start an offer from (ADR-072 §10)."""

    id = serializers.CharField(help_text="`core.<key>`, or a product's own namespace.")
    version = serializers.IntegerField(help_text="The latest version; applying names it.")
    readiness = serializers.ChoiceField(
        choices=("ready", "soon"),
        help_text="`ready` can be applied now; `soon` is shown and refused with "
        "`preset_not_ready`.",
    )
    labels = PresetLabelsSerializer()
    time_model = serializers.ChoiceField(
        choices=("slot", "range", "session"),
        help_text="`slot`: a start from the grid; `range`: a period from–to; `session`: "
        "seats in an occurrence.",
    )
    booked_subject = serializers.ChoiceField(
        choices=("staff", "unit", "unit_group", "seat"), help_text="What a booking takes."
    )
    booked_staff = serializers.ChoiceField(
        choices=("required", "optional", "none"), help_text="Whether a person does it."
    )
    place = serializers.ChoiceField(choices=("business", "customer", "online", "pickup_return"))
    required_inputs = serializers.ListField(
        child=serializers.CharField(),
        help_text="What the preset needs from the company before the offer can run, as keys.",
    )
    catalog_category = serializers.CharField(
        allow_null=True, help_text="A suggested category of the public catalogue."
    )
    online_booking = serializers.ChoiceField(
        choices=("ready", "soon"),
        help_text="Whether customers book it through the company's site. `soon`: the company "
        "sets the offer and its prices and the team books in the panel; an offer made from "
        "the preset starts hidden from online booking („rezerwacja przez stronę — wkrótce”).",
    )


class PresetListSerializer(serializers.Serializer[dict[str, Any]]):
    presets = PresetSerializer(many=True)


class SetupSerializer(serializers.Serializer[dict[str, Any]]):
    services = ServiceSetupSerializer(many=True)
    locations = PlaceSetupSerializer(many=True)
    resources = ResourceSetupSerializer(many=True)
    groups = GroupSetupSerializer(many=True)
    staff = SetupPersonSerializer(many=True)
    appointment_kinds = AppointmentKindSerializer(
        many=True,
        help_text=(
            "The kinds of visit the company's modules provide (ADR-050); empty when none. "
            'A service without one (`""`) is a plain visit.'
        ),
    )


def _bounded(field: str, **kwargs: Any) -> serializers.IntegerField:
    """An offer's number with the bounds `OFFER_SETTINGS` declares for it."""
    setting = offer_setting(field)
    assert setting.minimum is not None and setting.maximum is not None
    return serializers.IntegerField(
        min_value=setting.minimum,
        max_value=setting.maximum,
        help_text=setting.model_description,
        **kwargs,
    )


def _expected_version() -> serializers.IntegerField:
    return serializers.IntegerField(
        min_value=1,
        help_text="The version the change was made on, as the last read gave it; another "
        "one answers 409 `booking_version_conflict`.",
    )


class ServiceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new service."""

    name = serializers.CharField(max_length=160)
    time_model = serializers.ChoiceField(
        choices=[TimeModel.SLOT.value, TimeModel.RANGE.value],
        required=False,
        help_text=offer_setting("time_model").model_description,
    )
    range_unit = serializers.ChoiceField(
        choices=[RangeUnit.NIGHT.value, RangeUnit.DAY.value],
        required=False,
        help_text=offer_setting("range_unit").model_description,
    )
    range_start_local = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text=offer_setting("range_start_local").model_description,
    )
    range_end_local = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text=offer_setting("range_end_local").model_description,
    )
    group_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=50,
        required=False,
        help_text="For a `range` service: the groups of units it is booked in.",
    )
    duration_minutes = _bounded("duration_minutes", required=False, allow_null=True)
    buffer_before_minutes = _bounded("buffer_before_minutes", required=False)
    buffer_after_minutes = _bounded("buffer_after_minutes", required=False)
    minimum_notice_minutes = _bounded("minimum_notice_minutes", required=False)
    staff_count = _bounded("staff_count", required=False)
    public_staff_choice = serializers.ChoiceField(choices=StaffChoice.choices, required=False)
    slot_step_minutes = serializers.ChoiceField(
        choices=SLOT_STEPS,
        required=False,
        help_text=offer_setting("slot_step_minutes").model_description,
    )
    online = serializers.BooleanField(
        required=False, help_text=offer_setting("online").model_description
    )
    payment_policy = serializers.ChoiceField(
        choices=PaymentPolicy.choices,
        required=False,
        help_text=offer_setting("payment_policy").model_description,
    )
    confirmation = serializers.ChoiceField(
        choices=Confirmation.choices,
        required=False,
        help_text=offer_setting("confirmation").model_description,
    )
    response_hours = _bounded("response_hours", required=False)
    deposit_percent = _bounded("deposit_percent", required=False)
    transfer_due_days = _bounded("transfer_due_days", required=False)
    balance_due_days_before = _bounded("balance_due_days_before", required=False, allow_null=True)
    cancellation_refunds = RefundThresholdSerializer(  # type: ignore[call-arg]
        many=True,
        required=False,
        # The list's own bound (DRF passes it to the list serializer).
        max_length=REFUND_THRESHOLDS["max_rows"],
        help_text=_REFUNDS_HELP
        + " More back for less notice is refused (`thresholds_not_descending`), and so "
        "are two rows for the same number of days (`duplicate_threshold`).",
    )
    cancellation_applies_to = serializers.ChoiceField(
        choices=RefundBasis.values,
        required=False,
        help_text=offer_setting("cancellation_applies_to").model_description,
    )
    active = serializers.BooleanField(required=False)
    #: A new service only: the kind of visit a module provides (ADR-050).
    appointment_kind = serializers.CharField(max_length=64, required=False, allow_blank=True)
    staff_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100, required=False)
    location_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=50, required=False
    )
    resource_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=50, required=False
    )
    materials = MaterialInputSerializer(many=True, required=False)


class PresetApplyInputSerializer(serializers.Serializer[dict[str, Any]]):
    """An offer started from a preset (ADR-072 §10): the offer only, switched off."""

    preset_id = serializers.CharField(
        max_length=80, help_text="A preset's id from the presets list; only `ready` ones apply."
    )
    version = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, help_text="Null takes the latest version."
    )
    name = serializers.CharField(max_length=160)
    duration_minutes = _bounded("duration_minutes", required=False, allow_null=True)
    staff_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=100,
        required=False,
        allow_null=True,
        help_text="Who does it; null leaves the offer with nobody yet — nobody is picked.",
    )
    location_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=50,
        required=False,
        allow_null=True,
        help_text="Where it is offered; null leaves the offer without a place yet.",
    )


class ServiceUpdateSerializer(ServiceInputSerializer):
    """A change to a service: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    appointment_kind = None  # type: ignore[assignment]
    expected_version = _expected_version()


class PlaceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new place where the company works."""

    name = serializers.CharField(max_length=160)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)
    online = serializers.BooleanField(
        required=False, help_text="Shown on the booking form on the company's site (B2)."
    )


class PlaceUpdateSerializer(PlaceInputSerializer):
    """A change to a place: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    expected_version = _expected_version()


class ResourceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new resource a visit can take, or a unit a stay takes (a room, a
    device, a cottage, a kayak)."""

    name = serializers.CharField(max_length=160)
    active = serializers.BooleanField(required=False)
    group_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="The pool of identical units it joins; null takes it out of one.",
    )
    location_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="The company's place where the unit is."
    )
    capacity = serializers.IntegerField(
        min_value=1,
        max_value=1000,
        required=False,
        allow_null=True,
        help_text="How many people it takes; null where that makes no sense.",
    )
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class GroupInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new pool of identical units, e.g. „Domek 6-os.”."""

    name = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)


class GroupUpdateSerializer(GroupInputSerializer):
    """A change to a group: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    expected_version = _expected_version()


class UnitBlockInputSerializer(serializers.Serializer[dict[str, Any]]):
    """The company keeps the unit for itself from `starts_at` to `ends_at`."""

    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(
        max_length=160,
        required=False,
        allow_blank=True,
        default="",
        help_text="For the company only, e.g. „remont”; never shown to customers.",
    )


class UnitBlockSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    resource_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField()
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=TimeOffSource.choices, help_text="`manual`, or `ical` for an imported one."
    )
    holds = serializers.BooleanField(
        help_text="False for a block that could not take its time (it overlapped a booking); "
        "the unit is still busy then."
    )


class UnitBlockListSerializer(serializers.Serializer[dict[str, Any]]):
    items = UnitBlockSerializer(many=True)


def _weekdays() -> serializers.ListField:
    return serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        max_length=7,
        required=False,
        help_text="Weekdays, 0 = Monday … 6 = Sunday; empty — any.",
    )


class BookingRuleInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A season's rules for exactly one of an offer, a group or a unit."""

    name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    service_id = serializers.UUIDField(required=False, allow_null=True)
    group_id = serializers.UUIDField(required=False, allow_null=True)
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    starts_on = serializers.DateField(help_text="First local day of the season.")
    ends_on = serializers.DateField(help_text="Last local day of the season, included.")
    min_length = serializers.IntegerField(
        min_value=1,
        max_value=1000,
        required=False,
        allow_null=True,
        help_text="Shortest booking, in the offer's time units (nights, days, hours).",
    )
    max_length = serializers.IntegerField(
        min_value=1, max_value=1000, required=False, allow_null=True
    )
    length_multiple = serializers.IntegerField(
        min_value=1,
        max_value=365,
        required=False,
        allow_null=True,
        help_text="7 — whole weeks only.",
    )
    start_weekdays = _weekdays()
    end_weekdays = _weekdays()
    notice_hours = serializers.IntegerField(
        min_value=0,
        max_value=24 * 365,
        required=False,
        allow_null=True,
        help_text="At least this many hours before its start a booking can be made.",
    )
    window_days = serializers.IntegerField(
        min_value=1,
        max_value=730,
        required=False,
        allow_null=True,
        help_text="At most this many days ahead a booking can be made.",
    )
    closed = serializers.BooleanField(required=False, help_text="No bookings in this season.")
    buffer_after_minutes = serializers.IntegerField(
        min_value=0,
        max_value=60 * 24 * 7,
        required=False,
        allow_null=True,
        help_text="The break after a booking (cleaning); null — the offer's own.",
    )
    active = serializers.BooleanField(required=False)


class BookingRuleUpdateSerializer(BookingRuleInputSerializer):
    starts_on = serializers.DateField(required=False)
    ends_on = serializers.DateField(required=False)
    expected_version = _expected_version()


class BookingRuleSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    service_id = serializers.UUIDField(allow_null=True)
    group_id = serializers.UUIDField(allow_null=True)
    resource_id = serializers.UUIDField(allow_null=True)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    min_length = serializers.IntegerField(allow_null=True)
    max_length = serializers.IntegerField(allow_null=True)
    length_multiple = serializers.IntegerField(allow_null=True)
    start_weekdays = serializers.ListField(child=serializers.IntegerField())
    end_weekdays = serializers.ListField(child=serializers.IntegerField())
    notice_hours = serializers.IntegerField(allow_null=True)
    window_days = serializers.IntegerField(allow_null=True)
    closed = serializers.BooleanField()
    buffer_after_minutes = serializers.IntegerField(allow_null=True)
    active = serializers.BooleanField()
    version = serializers.IntegerField()


class BookingRulePreviewSerializer(BookingRuleSerializer):
    changes = _changes()


class BookingRuleListSerializer(serializers.Serializer[dict[str, Any]]):
    items = BookingRuleSerializer(many=True)


class BookingClosureInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Days the company, or one of its places, takes no bookings."""

    location_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Null — the whole company."
    )
    starts_on = serializers.DateField(help_text="First closed local day.")
    ends_on = serializers.DateField(help_text="Last closed local day, included.")
    note = serializers.CharField(max_length=160, required=False, allow_blank=True)


class BookingClosureUpdateSerializer(BookingClosureInputSerializer):
    starts_on = serializers.DateField(required=False)
    ends_on = serializers.DateField(required=False)
    expected_version = _expected_version()


class BookingClosureSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    location_id = serializers.UUIDField(allow_null=True)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    note = serializers.CharField()
    version = serializers.IntegerField()


class BookingClosurePreviewSerializer(BookingClosureSerializer):
    changes = _changes()


class BookingClosureListSerializer(serializers.Serializer[dict[str, Any]]):
    items = BookingClosureSerializer(many=True)


class CopyYearInputSerializer(serializers.Serializer[dict[str, Any]]):
    year = serializers.IntegerField(
        min_value=2000, max_value=2100, help_text="Items starting in this year are copied."
    )


class CopyYearResultSerializer(serializers.Serializer[dict[str, Any]]):
    count = serializers.IntegerField(help_text="How many items the copy made (would make).")


class ResourceUpdateSerializer(ResourceInputSerializer):
    """A change to a resource: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    expected_version = _expected_version()


class CustomerAnonymizedSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    anonymized_at = serializers.DateTimeField()


class SlotSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    staff_id = serializers.UUIDField()
    resource_id = serializers.UUIDField(allow_null=True)


class SlotListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SlotSerializer(many=True)


class SlotDayListSerializer(serializers.Serializer[dict[str, Any]]):
    items = serializers.ListField(child=serializers.DateField())


class SlotTimeSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class SlotTimeListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SlotTimeSerializer(many=True)


class SlotStaffSerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    #: The resource that goes with this person at this start, for the create call.
    resource_id = serializers.UUIDField(allow_null=True)


class StaffSlotTimeSerializer(SlotTimeSerializer):
    #: Who is free at this start; only the panel sees it (ADR-058 §8).
    staff = SlotStaffSerializer(many=True)


class StaffSlotTimeListSerializer(serializers.Serializer[dict[str, Any]]):
    items = StaffSlotTimeSerializer(many=True)


class LocationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()


class StaffSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    membership_id = serializers.UUIDField(allow_null=True)


class PublicServiceSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    #: Lets a vertical's screen offer only its own kind of visit (ADR-050).
    appointment_kind = serializers.CharField()


class PublicChoiceServiceSerializer(PublicServiceSerializer):
    confirmation = serializers.ChoiceField(
        choices=Confirmation.choices,
        required=False,
        help_text="`on_request` — a booking of this service waits for the company's "
        "answer (`pending_request`) before it is confirmed.",
    )
    response_hours = serializers.IntegerField(
        required=False,
        help_text="With `on_request`: how many hours the company has to answer.",
    )
    #: „Do kogo?”: none, a team or a person (answer 2, 24.09).
    staff_choice = serializers.CharField()
    #: The teams able to take it, or the people shown to customers who do it.
    team_ids = serializers.ListField(child=serializers.UUIDField())
    person_ids = serializers.ListField(child=serializers.UUIDField())


class PublicNameSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ServiceSerializer(PublicServiceSerializer):
    #: How many people one visit needs (ADR-058 §2).
    staff_count = serializers.IntegerField()
    #: What the public form lets a customer choose: none, team or person.
    public_staff_choice = serializers.CharField()
    #: Produkty z magazynu, które wizyta tej usługi zabiera.
    materials = MaterialInputSerializer(many=True, required=False)
    #: False, gdy materiał tej usługi rozlicza jej moduł (ADR-055) albo nie ma magazynu.
    takes_materials = serializers.BooleanField(required=False)


class ResourceSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()


class CatalogSerializer(serializers.Serializer[dict[str, Any]]):
    locations = LocationSerializer(many=True)
    staff = StaffSerializer(many=True)
    services = ServiceSerializer(many=True)
    resources = ResourceSerializer(many=True)
    #: A module offers the company's places (GET /booking/places/) in the visit form.
    place_search = serializers.BooleanField(required=False)


class PublicOnlineSerializer(serializers.Serializer[dict[str, Any]]):
    paused = serializers.BooleanField()
    resume_on = serializers.DateField(allow_null=True, help_text="The day booking resumes.")
    horizon_days = serializers.IntegerField(
        help_text="How many days, today included, the form offers (booking.online.horizon_days)."
    )
    last_day = serializers.DateField(help_text="The last day a customer may book a visit online.")
    period_last_day = serializers.DateField(
        required=False,
        help_text="The last day a stay booked online may begin: the platform's bound of a "
        "period calendar. A season's own window ahead may end earlier (`rule_window`); "
        "`horizon_days` is about visits and does not limit stays.",
    )
    contact = serializers.ChoiceField(
        choices=["email", "phone", "email_or_phone", "email_and_phone"],
        help_text="What the form requires of the customer (booking.online.contact).",
    )


class PublicDocumentSerializer(serializers.Serializer[dict[str, Any]]):
    """A document of the company the customer accepts while booking."""

    kind = serializers.ChoiceField(choices=["booking_terms", "privacy_policy"])
    statement = serializers.CharField(
        help_text="What the customer states by ticking, in the booking's language."
    )
    text_id = serializers.UUIDField(
        help_text="The text in force in this language; send it back in `consents.documents`."
    )
    version = serializers.IntegerField(help_text="The number of the version in force.")
    effective_from = serializers.DateField()
    url = serializers.CharField(help_text="Where anybody reads the document.")


class PublicConsentsSerializer(serializers.Serializer[dict[str, Any]]):
    """What a booking form shows before the customer books (ADR-073 §9)."""

    locale = serializers.CharField(
        help_text="The booking's language: the one asked for when the company has it, "
        "otherwise the company's first."
    )
    documents = PublicDocumentSerializer(
        many=True,
        help_text="The documents in force that have a text in this language, in the order "
        "to show them; empty when the company has published none. Never a text in "
        "another language.",
    )


class PublicExtraSerializer(serializers.Serializer[dict[str, Any]]):
    """An extra of a service on the booking form."""

    id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    name = serializers.CharField(help_text="In the language asked for, where translated.")
    basis = serializers.ChoiceField(choices=ExtraBasis.choices)
    mandatory = serializers.BooleanField(
        help_text="On every booking of the service; the others the customer picks."
    )
    max_quantity = serializers.IntegerField()
    unit_gross_minor = serializers.IntegerField(
        help_text="What one of it comes to, tax included. The quote is what counts."
    )


class PublicStayUnitSerializer(serializers.Serializer[dict[str, Any]]):
    """A unit an offer lists by itself: the guest books this very one."""

    id = serializers.UUIDField(help_text="Send it as `resource_id`.")
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    capacity = serializers.IntegerField(
        allow_null=True, help_text="How many people it takes; null — nobody counts."
    )


class PublicStayGroupSerializer(serializers.Serializer[dict[str, Any]]):
    """A group of identical units: the guest books the group, the server picks
    the unit (ADR-072 §3)."""

    id = serializers.UUIDField(help_text="Send it as `group_id`.")
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    capacity = serializers.IntegerField(
        allow_null=True,
        help_text="The most people one of its units takes; null — nobody counts.",
    )
    units = serializers.IntegerField(help_text="How many units the group has.")


class PublicStayOfferSerializer(serializers.Serializer[dict[str, Any]]):
    """An offer booked from–to on the form: nights or days."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    range_unit = serializers.CharField(
        help_text="`night` — booked from the arrival day to the departure day; `day` — "
        "from the first day to the last, both included."
    )
    range_start_local = serializers.TimeField(
        allow_null=True, help_text="Check-in or pickup, the company's wall clock."
    )
    range_end_local = serializers.TimeField(
        allow_null=True, help_text="Check-out or return, the company's wall clock."
    )
    confirmation = serializers.ChoiceField(
        choices=Confirmation.choices,
        help_text="`on_request` — a booking waits for the company's answer "
        "(`pending_request`) before it is confirmed.",
    )
    response_hours = serializers.IntegerField(
        help_text="With `on_request`: how many hours the company has to answer."
    )
    groups = PublicStayGroupSerializer(many=True)
    units = PublicStayUnitSerializer(many=True)


class PublicParticipantCategorySerializer(serializers.Serializer[dict[str, Any]]):
    """Who may come besides standard people („Dziecko”, „Pies”)."""

    id = serializers.UUIDField(help_text="Send it as `participants[].category_id`.")
    name = serializers.CharField(help_text="In the language asked for, where translated.")
    counts_towards_capacity = serializers.BooleanField(
        help_text="Whether one of them takes a place in a unit's capacity."
    )


class PublicCatalogSerializer(serializers.Serializer[dict[str, Any]]):
    """The catalogue without the staff list: only teams by name and people the
    company shows its customers (ADR-058 §8)."""

    locations = LocationSerializer(many=True)
    services = PublicChoiceServiceSerializer(many=True)
    resources = ResourceSerializer(many=True)
    teams = PublicNameSerializer(many=True)
    people = PublicNameSerializer(many=True)
    stays = PublicStayOfferSerializer(
        many=True,
        required=False,
        help_text="The offers booked from–to (nights, days) the company takes on its "
        "form, each with what a guest chooses between; booked through `…/stays/`. An "
        "offer with nothing to book online is not listed.",
    )
    participant_categories = PublicParticipantCategorySerializer(
        many=True,
        required=False,
        help_text="Who may come to a stay besides standard people; empty when the form "
        "has no stays.",
    )
    extras = PublicExtraSerializer(
        many=True, required=False, help_text="What the services add to their price."
    )
    currency = serializers.CharField(
        required=False, help_text="The currency of the company's prices, ISO 4217."
    )
    #: The organization's zone: the days and times offered are its wall clock.
    timezone = serializers.CharField()
    online = PublicOnlineSerializer(
        help_text="Whether the company takes online bookings now (ADR-078, booking.online)."
    )
    locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="The company's languages: a booking page in another one is not "
        "offered (ADR-071 pkt 21).",
    )
    locale = serializers.CharField(
        help_text="The language the names are in: the one asked for when the company has "
        "it, otherwise the company's own (TL12b)."
    )


class PersonSerializer(serializers.Serializer[dict[str, Any]]):
    """A person of the company as booking keeps them (ADR-058 §1)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    #: The person's account; null: no account (a subcontractor) or not yet.
    membership_id = serializers.UUIDField(allow_null=True)
    #: The invitation the person was added under; accepting it links the account.
    invitation_id = serializers.UUIDField(allow_null=True)
    #: Null for whoever may not see it: management and the person only (ADR-058 §9).
    phone = serializers.CharField(allow_null=True)
    #: False: a former employee.
    active = serializers.BooleanField()
    #: The services the person does; with hours, that is "takes visits".
    service_ids = serializers.ListField(child=serializers.UUIDField())
    has_hours = serializers.BooleanField()
    #: The teams the person belongs to (ADR-058 §2).
    team_ids = serializers.ListField(child=serializers.UUIDField())
    #: „Pokazuj klientom”: the name customers see; null: not shown (ADR-058 §8).
    public_name = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class PersonPublicInputSerializer(serializers.Serializer[dict[str, Any]]):
    shown = serializers.BooleanField()
    #: The name for customers, e.g. with a title; empty: the person's own.
    name = serializers.CharField(max_length=160, required=False, allow_blank=True)


class PersonListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PersonSerializer(many=True)


class PersonListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    #: Only the caller's own entry ("my card").
    mine = serializers.BooleanField(default=False)


class WorkingHoursSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    #: 0 is Monday; the times are the organization's wall clock.
    weekday = serializers.IntegerField()
    local_start = serializers.TimeField()
    local_end = serializers.TimeField()
    location_id = serializers.UUIDField()
    location_name = serializers.CharField()


class TimeOffSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    #: Null for whoever may not see it: an illness is health data (ADR-058 §9).
    reason = serializers.CharField(allow_null=True)


class PersonDetailSerializer(PersonSerializer):
    hours = WorkingHoursSerializer(many=True)
    #: Current and coming absences.
    time_off = TimeOffSerializer(many=True)
    hours_version = serializers.IntegerField(
        help_text="The version of the person's week; a change of the hours names it "
        "(`expected_version`)."
    )


class PersonHoursPreviewSerializer(PersonDetailSerializer):
    """The person as the change of hours would leave them; nothing is saved."""

    changes = _changes()


class PersonInvitationInputSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField()
    role = serializers.SlugField(max_length=64)


class WeeklyHoursInputSerializer(serializers.Serializer[dict[str, Any]]):
    """The same hours on the chosen weekdays, as "Add employee" asks for them."""

    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), min_length=1, max_length=7
    )
    local_start = serializers.TimeField()
    local_end = serializers.TimeField()
    #: Omitted: the organization's only place of work.
    location_id = serializers.UUIDField(required=False, allow_null=True)


class PersonCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(min_length=1, max_length=160)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    #: An e-mail and a role: the person gets an invitation to the panel.
    invitation = PersonInvitationInputSerializer(required=False, allow_null=True)
    #: An existing member's own entry, when they have none yet.
    membership_id = serializers.UUIDField(required=False, allow_null=True)
    service_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    hours = WeeklyHoursInputSerializer(required=False, allow_null=True)
    #: "Hours like …": another person's week instead of `hours`.
    copy_hours_from = serializers.UUIDField(required=False, allow_null=True)
    #: The teams the person joins (ADR-058 §2).
    team_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)


class PersonUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(min_length=1, max_length=160, required=False)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    #: Links an entry added without an account to a team member's (null: unlinks).
    membership_id = serializers.UUIDField(required=False, allow_null=True)


class PersonServicesInputSerializer(serializers.Serializer[dict[str, Any]]):
    service_ids = serializers.ListField(child=serializers.UUIDField())


class HoursRuleInputSerializer(serializers.Serializer[dict[str, Any]]):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    local_start = serializers.TimeField()
    local_end = serializers.TimeField()
    location_id = serializers.UUIDField()


class PersonHoursInputSerializer(serializers.Serializer[dict[str, Any]]):
    rules = serializers.ListField(
        child=HoursRuleInputSerializer(),
        max_length=70,
        help_text="The person's whole week, rule by rule; an empty list clears it. A refusal "
        "names the rule: `rules.<i>.location_id`, `rules.<i>.local_end`, `rules.<i>.local_start`.",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="The week's version (`hours_version`) the change was made on; another one "
        "answers 409 `booking_version_conflict`.",
    )


class TimeOffInputSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")


class TimeOffCreatedSerializer(serializers.Serializer[dict[str, Any]]):
    time_off = TimeOffSerializer()
    #: The person's visits the absence runs into; they stay until someone moves them.
    conflicts = serializers.IntegerField()


class PersonInvitationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()


class IntervalSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class AwayIntervalSerializer(IntervalSerializer):
    #: Null for whoever may not see it (ADR-058 §9).
    reason = serializers.CharField(allow_null=True)


class PersonDaySerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    #: Working hours that day, as instants.
    works = IntervalSerializer(many=True)
    time_off = AwayIntervalSerializer(many=True)
    #: Visits that occupy the person, buffers included.
    busy = IntervalSerializer(many=True)


class PeopleDaySerializer(serializers.Serializer[dict[str, Any]]):
    date = serializers.DateField()
    timezone = serializers.CharField()
    items = PersonDaySerializer(many=True)


class StaffMetricSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    value = serializers.IntegerField()
    #: "count", "minutes" or "money" (minor units of the organization's currency).
    unit = serializers.CharField()
    #: A number's parts, e.g. visits as the lead and in the crew.
    parts = serializers.DictField(child=serializers.IntegerField())
    #: The same number over the period before; null for a state like today's stock.
    previous = serializers.IntegerField(allow_null=True)


class StaffFactGroupSerializer(serializers.Serializer[dict[str, Any]]):
    #: The module that counts: "calendar", "inventory", a product's own.
    provider = serializers.CharField()
    metrics = StaffMetricSerializer(many=True)


class StaffFactsSerializer(serializers.Serializer[dict[str, Any]]):
    """A person's numbers for a period (team plan, phase 5)."""

    period_from = serializers.DateField()
    period_to = serializers.DateField()
    previous_from = serializers.DateField()
    previous_to = serializers.DateField()
    groups = StaffFactGroupSerializer(many=True)


class StaffEventSerializer(serializers.Serializer[dict[str, Any]]):
    at = serializers.DateTimeField()
    kind = serializers.CharField()
    event = serializers.CharField()
    #: What the panel needs to tell the event: names, numbers, times.
    params = serializers.DictField()
    value = serializers.IntegerField(allow_null=True)
    unit = serializers.CharField(allow_blank=True)


class StaffHistorySerializer(serializers.Serializer[dict[str, Any]]):
    period_from = serializers.DateField()
    period_to = serializers.DateField()
    #: The kinds the viewer may filter by.
    kinds = serializers.ListField(child=serializers.CharField())
    items = StaffEventSerializer(many=True)
    #: Pass as `before` for the next, older page; null: nothing older.
    next_before = serializers.DateTimeField(allow_null=True)


class PerformanceMetricSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    unit = serializers.CharField()


class PerformanceColumnSerializer(serializers.Serializer[dict[str, Any]]):
    provider = serializers.CharField()
    metrics = PerformanceMetricSerializer(many=True)


class PerformanceRowSerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    membership_id = serializers.UUIDField(allow_null=True)
    team_ids = serializers.ListField(child=serializers.UUIDField())
    #: provider → metric key → value.
    groups = serializers.DictField(child=serializers.DictField(child=serializers.IntegerField()))


class PerformanceSerializer(serializers.Serializer[dict[str, Any]]):
    period_from = serializers.DateField()
    period_to = serializers.DateField()
    columns = PerformanceColumnSerializer(many=True)
    items = PerformanceRowSerializer(many=True)


class StayInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A stay or rental from the panel: a range offer, a unit or a group, dates."""

    service_id = serializers.UUIDField()
    resource_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="This very unit."
    )
    group_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Any free unit of this group — the server picks the least busy one. With "
        "neither, any unit the offer lists.",
    )
    start_date = serializers.DateField(help_text="Arrival day (nights) or first day (days).")
    end_date = serializers.DateField(
        help_text="Departure day (nights) or last day, included (days)."
    )
    customer = CustomerInputSerializer()
    customer_notes = serializers.CharField(required=False, allow_blank=True, max_length=500)
    participants = _participants()
    extras = _extras()
    quote_digest = _quote_digest()


class StayMoveSerializer(serializers.Serializer[dict[str, Any]]):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    quote_digest = _quote_digest()


class StayPlanSerializer(serializers.Serializer[dict[str, Any]]):
    """What a booking or a move of a stay would take; nothing is saved."""

    resource_id = serializers.UUIDField(help_text="The unit the stay would take.")
    resource_name = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    length = serializers.IntegerField(help_text="Nights or days.")
    range_unit = serializers.CharField()
    quote = BookingQuoteSerializer(
        required=False,
        allow_null=True,
        help_text="What the stay would cost; null for a move of a booking made before quotes.",
    )


class DateListSerializer(serializers.Serializer[dict[str, Any]]):
    items = serializers.ListField(child=serializers.DateField())


class OccupancyUnitSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    group_id = serializers.UUIDField(allow_null=True, help_text="Its pool of identical units.")
    group_name = serializers.CharField(allow_null=True)
    location_id = serializers.UUIDField(allow_null=True, help_text="Where the unit is.")
    capacity = serializers.IntegerField(allow_null=True)


class OccupancyHeldSerializer(serializers.Serializer[dict[str, Any]]):
    unit_id = serializers.UUIDField()
    kind = serializers.ChoiceField(
        choices=["stay", "visit", "block"],
        help_text="`stay` — a booking by dates; `visit` — a visit that takes the unit; "
        "`block` — the unit taken out (renovation, owner's use).",
    )
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    appointment_id = serializers.UUIDField(allow_null=True)
    block_id = serializers.UUIDField(allow_null=True)
    title = serializers.CharField(
        help_text="The booking's name (a module's, else the customer's), or the block's reason; "
        "empty for somebody else's booking the caller may not see."
    )
    status = serializers.CharField(
        help_text="The booking's status; empty for a block and for a booking not shown."
    )
    gross_minor = serializers.IntegerField(
        allow_null=True,
        help_text="What the booking comes to, tax included, from its frozen quote; null for a "
        "block, a booking without a price and one not shown.",
    )
    currency = serializers.CharField(allow_null=True, help_text="Of `gross_minor`, ISO 4217.")


class OccupancySerializer(serializers.Serializer[dict[str, Any]]):
    """The company's units against days (ADR-072 phase 2d)."""

    date_from = serializers.DateField(help_text="First local day of the window.")
    date_to = serializers.DateField(help_text="Last local day of the window, included.")
    timezone = serializers.CharField()
    units = OccupancyUnitSerializer(many=True)
    held = OccupancyHeldSerializer(many=True)
    closures = BookingClosureSerializer(many=True)
