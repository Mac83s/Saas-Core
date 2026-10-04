"""The panel's and the assistant's API of the price list (ADR-072 §6, phases
3a and 3c): prices of offers, groups and units, who comes when it changes the
price, and the extras and deposits of offers. Every write is a setup write
with its preview (§11)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .models import (
    Extra,
    ExtraBasis,
    ExtraKind,
    ParticipantCategory,
    PriceBasis,
    PriceChange,
    PriceRule,
    VatCode,
)
from .prices import (
    GROSS,
    MAX_HISTORY_PAGE,
    NET,
    amounts_are_gross,
    copy_prices_to_next_year,
    delete_price,
    list_categories,
    list_extras,
    list_price_changes,
    list_prices,
    price_list_on,
    save_category,
    save_extra,
    save_price,
)
from .serializers import (
    CopyYearInputSerializer,
    CopyYearResultSerializer,
    _changes,
    _expected_version,
    _weekdays,
)
from .views import (
    _PREVIEW,
    _PREVIEW_NOTE,
    _SETUP_PROBLEMS,
    _UPDATE_NOTE,
    _VERSION_QUERY,
    _WRITE_NOTE,
    IDEMPOTENCY,
    _expected,
    _idem,
    _update,
    _with_changes,
)

#: A protective bound, not a business rule: 1 000 000.00 of the currency.
MAX_AMOUNT_MINOR = 100_000_000


def _amount(**kwargs: Any) -> serializers.IntegerField:
    return serializers.IntegerField(min_value=0, max_value=MAX_AMOUNT_MINOR, **kwargs)


class CategoryPriceSerializer(serializers.Serializer[dict[str, Any]]):
    category_id = serializers.UUIDField()
    amount_minor = _amount(help_text="What one participant of the category pays.")


class LengthDiscountSerializer(serializers.Serializer[dict[str, Any]]):
    min_length = serializers.IntegerField(
        min_value=2, max_value=1000, help_text="From this many time units of the offer."
    )
    percent = serializers.IntegerField(min_value=1, max_value=100)


class PriceRuleInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A price of exactly one of an offer, a group of units or a unit."""

    name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    service_id = serializers.UUIDField(required=False, allow_null=True)
    group_id = serializers.UUIDField(required=False, allow_null=True)
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    starts_on = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="First local day of the season; null with `ends_on` — the base price.",
    )
    ends_on = serializers.DateField(
        required=False, allow_null=True, help_text="Last local day of the season, included."
    )
    weekdays = _weekdays()
    local_from = serializers.TimeField(
        required=False,
        allow_null=True,
        help_text="With `local_to`: the local hours it prices, by a booking's start.",
    )
    local_to = serializers.TimeField(required=False, allow_null=True)
    basis = serializers.ChoiceField(
        choices=PriceBasis.choices,
        help_text="`per_booking`; `per_time_unit` — a night or a day of a stay, not for a "
        "visit; `per_person`; `per_group` — one price for the group that comes.",
    )
    amount_minor = _amount(
        help_text="In minor units of the company's currency (grosze), gross or net as the "
        "company set it (`pricing.entry.amounts`)."
    )
    vat_code = serializers.ChoiceField(
        choices=VatCode.choices,
        required=False,
        help_text="The tax rate as a code: 23, 8, 5, 0, `zw` (exempt), `np` (outside VAT).",
    )
    included_people = serializers.IntegerField(
        min_value=0,
        max_value=1000,
        required=False,
        allow_null=True,
        help_text="How many people the amount covers; null — everybody who comes.",
    )
    extra_person_amount_minor = _amount(
        required=False,
        allow_null=True,
        help_text="What each person beyond `included_people` adds; required with it — 0 "
        "says they come free.",
    )
    extra_person_per_time_unit = serializers.BooleanField(
        required=False,
        help_text="Further people and priced categories pay per night or day, not once. "
        "Only for `per_time_unit`.",
    )
    category_prices = serializers.ListField(
        child=CategoryPriceSerializer(),
        required=False,
        max_length=20,
        help_text="A participant category's own amount instead of a person's.",
    )
    length_discounts = serializers.ListField(
        child=LengthDiscountSerializer(),
        required=False,
        max_length=10,
        help_text="For `per_time_unit`: the percent off the stay of the longest threshold "
        "it reaches. A longer threshold must give a higher percent.",
    )
    active = serializers.BooleanField(required=False)


class PriceRuleUpdateSerializer(PriceRuleInputSerializer):
    basis = serializers.ChoiceField(choices=PriceBasis.choices, required=False)
    amount_minor = _amount(required=False)
    expected_version = _expected_version()


class PriceRuleSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    service_id = serializers.UUIDField(allow_null=True)
    group_id = serializers.UUIDField(allow_null=True)
    resource_id = serializers.UUIDField(allow_null=True)
    starts_on = serializers.DateField(allow_null=True)
    ends_on = serializers.DateField(allow_null=True)
    weekdays = serializers.ListField(child=serializers.IntegerField())
    local_from = serializers.TimeField(allow_null=True)
    local_to = serializers.TimeField(allow_null=True)
    basis = serializers.ChoiceField(choices=PriceBasis.choices)
    amount_minor = serializers.IntegerField()
    currency = serializers.CharField(help_text="The company's currency, ISO 4217.")
    vat_code = serializers.ChoiceField(choices=VatCode.choices)
    included_people = serializers.IntegerField(allow_null=True)
    extra_person_amount_minor = serializers.IntegerField(allow_null=True)
    extra_person_per_time_unit = serializers.BooleanField()
    category_prices = CategoryPriceSerializer(many=True)
    length_discounts = LengthDiscountSerializer(many=True)
    active = serializers.BooleanField()
    version = serializers.IntegerField()


class PriceRulePreviewSerializer(PriceRuleSerializer):
    changes = _changes()


class PriceRuleListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PriceRuleSerializer(many=True)
    amounts = serializers.ChoiceField(
        choices=[GROSS, NET],
        help_text="How the company's amounts are read (`pricing.entry.amounts`); a "
        "customer always sees gross.",
    )


class PriceHistoryQuerySerializer(serializers.Serializer[dict[str, Any]]):
    price_id = serializers.UUIDField(
        required=False,
        help_text="Only this price's lines — also of a price deleted since. Without it, "
        "the whole price list's.",
    )
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=MAX_HISTORY_PAGE, default=25)


class PriceChangeActorSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField()
    email = serializers.CharField()


class PriceChangeSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    price_id = serializers.UUIDField(help_text="The price the line is about.")
    change = serializers.ChoiceField(
        choices=PriceChange.choices,
        help_text="`baseline` — the price as it stood when the record began; `created`, "
        "`updated`, `deleted` — a write since.",
    )
    recorded_at = serializers.DateTimeField()
    actor = PriceChangeActorSerializer(
        allow_null=True, help_text="Who wrote it; null for the baseline."
    )
    acting_via = serializers.CharField(
        allow_blank=True, help_text="`assistant` when the person's assistant wrote it for them."
    )
    amount_minor = serializers.IntegerField(
        help_text="The amount after the write, in minor units of `currency`; a deleted "
        "price's last amount."
    )
    previous_amount_minor = serializers.IntegerField(
        allow_null=True,
        help_text="The amount before the write; null for a price just made and for the baseline.",
    )
    currency = serializers.CharField(help_text="ISO 4217.")
    price = PriceRuleSerializer(
        help_text="The whole price as the write left it — for a deletion, as it last was."
    )


class PriceChangePageSerializer(serializers.Serializer[dict[str, Any]]):
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    recorded_since = serializers.DateTimeField(
        allow_null=True,
        help_text="The company's first line: the record is complete from then on. Null — "
        "the company never had a price.",
    )
    items = PriceChangeSerializer(many=True)


class PriceListOnQuerySerializer(serializers.Serializer[dict[str, Any]]):
    day = serializers.DateField(
        help_text="A day in the company's time zone: the price list as it stood when that "
        "day ended. Today or a later day: as it stands now."
    )


class PriceListOnSerializer(serializers.Serializer[dict[str, Any]]):
    day = serializers.DateField()
    as_of = serializers.DateTimeField(help_text="The moment the list is read at.")
    recorded_since = serializers.DateTimeField(
        allow_null=True, help_text="The company's first line of the record; null — none yet."
    )
    items = PriceRuleSerializer(
        many=True,
        help_text="Every price that existed then, switched-off ones included (`active`), "
        "each as it was — not as it is today.",
    )


class ParticipantCategoryInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Who comes, when it changes the price: a child, a senior, a dog."""

    name = serializers.CharField(max_length=160)
    counts_towards_capacity = serializers.BooleanField(
        required=False,
        help_text="Whether a participant of it takes a place in a unit's capacity and may "
        "be one of the people a price includes. A dog does not.",
    )
    active = serializers.BooleanField(required=False)


class ParticipantCategoryUpdateSerializer(ParticipantCategoryInputSerializer):
    name = serializers.CharField(max_length=160, required=False)
    expected_version = _expected_version()


class ParticipantCategorySerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    counts_towards_capacity = serializers.BooleanField()
    active = serializers.BooleanField()
    version = serializers.IntegerField()


class ParticipantCategoryPreviewSerializer(ParticipantCategorySerializer):
    changes = _changes()


class ParticipantCategoryListSerializer(serializers.Serializer[dict[str, Any]]):
    items = ParticipantCategorySerializer(many=True)


class ExtraInputSerializer(serializers.Serializer[dict[str, Any]]):
    """What an offer adds to its price, or the deposit it holds."""

    service_id = serializers.UUIDField(help_text="The offer it belongs to.")
    name = serializers.CharField(max_length=160)
    kind = serializers.ChoiceField(
        choices=ExtraKind.choices,
        required=False,
        help_text="`charge` — the customer pays it; `security_deposit` — held and given "
        "back: one amount per booking, no tax, never part of the total.",
    )
    basis = serializers.ChoiceField(
        choices=ExtraBasis.choices,
        required=False,
        help_text="`per_booking`, `per_person`; for a stay also `per_time_unit` and "
        "`per_person_per_time_unit` (a local tax).",
    )
    amount_minor = _amount(
        help_text="In minor units of the company's currency, gross or net as the price list."
    )
    vat_code = serializers.ChoiceField(
        choices=VatCode.choices,
        required=False,
        help_text="23, 8, 5, 0, `zw` (exempt), `np` (outside VAT — what the company only "
        "collects, like a local tax).",
    )
    mandatory = serializers.BooleanField(
        required=False, help_text="On every booking of the offer; otherwise the customer picks."
    )
    max_quantity = serializers.IntegerField(
        min_value=1,
        max_value=100,
        required=False,
        help_text="How many of an optional one a booking may take.",
    )
    active = serializers.BooleanField(required=False)


class ExtraUpdateSerializer(ExtraInputSerializer):
    service_id = None  # type: ignore[assignment]
    name = serializers.CharField(max_length=160, required=False)
    amount_minor = _amount(required=False)
    expected_version = _expected_version()


class ExtraSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=ExtraKind.choices)
    basis = serializers.ChoiceField(choices=ExtraBasis.choices)
    amount_minor = serializers.IntegerField()
    currency = serializers.CharField()
    vat_code = serializers.ChoiceField(choices=VatCode.choices)
    mandatory = serializers.BooleanField()
    max_quantity = serializers.IntegerField()
    active = serializers.BooleanField()
    version = serializers.IntegerField()


class ExtraPreviewSerializer(ExtraSerializer):
    changes = _changes()


class ExtraListSerializer(serializers.Serializer[dict[str, Any]]):
    items = ExtraSerializer(many=True)


def _extra_payload(value: Extra) -> dict[str, Any]:
    return {
        "id": value.id,
        "service_id": value.service_id,
        "name": value.name,
        "kind": value.kind,
        "basis": value.basis,
        "amount_minor": value.amount_minor,
        "currency": value.currency,
        "vat_code": value.vat_code,
        "mandatory": value.mandatory,
        "max_quantity": value.max_quantity,
        "active": value.active,
        "version": value.version,
    }


def _price_payload(value: PriceRule) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "service_id": value.service_id,
        "group_id": value.group_id,
        "resource_id": value.resource_id,
        "starts_on": value.starts_on,
        "ends_on": value.ends_on,
        "weekdays": value.weekdays,
        "local_from": value.local_from,
        "local_to": value.local_to,
        "basis": value.basis,
        "amount_minor": value.amount_minor,
        "currency": value.currency,
        "vat_code": value.vat_code,
        "included_people": value.included_people,
        "extra_person_amount_minor": value.extra_person_amount_minor,
        "extra_person_per_time_unit": value.extra_person_per_time_unit,
        "category_prices": value.category_prices,
        "length_discounts": value.length_discounts,
        "active": value.active,
        "version": value.version,
    }


def _category_payload(value: ParticipantCategory) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "counts_towards_capacity": value.counts_towards_capacity,
        "active": value.active,
        "version": value.version,
    }


@method_decorator(csrf_protect, name="dispatch")
class PriceRuleListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_prices_list",
        summary="List the price list",
        description="Every price of the company's offers, groups and units, switched-off "
        "ones included, and how its amounts are read. For a day and an hour one price "
        "applies: one for some days only (a season, weekdays, hours) over a base price, "
        "whoever it is for; between two of one kind the unit's over its group's over the "
        "offer's, then a season's over one without dates, the narrower one (weekdays, "
        "hours) over the wider, then the later start.",
        tags=["booking"],
        responses={200: PriceRuleListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({
            "items": [_price_payload(item) for item in list_prices()],
            "amounts": GROSS if amounts_are_gross() else NET,
        })

    @extend_schema(
        operation_id="booking_price_create",
        summary="Add a price",
        description="A price of exactly one offer, group or unit: the base price without "
        "dates, a season's with them, a weekend's or a peak's with weekdays and hours. Its "
        "currency is the company's." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=PriceRuleInputSerializer,
        responses={201: PriceRuleSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = PriceRuleInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_price(
            price_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_price_payload(saved.value), status=201)


class PriceHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_price_history_list",
        summary="List the record of price changes",
        description="Every write of a price since the record began, newest first, a page at "
        "a time: the price as the write left it, the amount before and after, who wrote it "
        "and when. Append-only — nothing in it is ever changed or removed — so it answers "
        "what a price was on a past day, also for a price deleted since. `price_id` narrows "
        "it to one price.",
        tags=["booking"],
        parameters=[PriceHistoryQuerySerializer],
        responses={
            200: PriceChangePageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = PriceHistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        found = list_price_changes(**dict(query.validated_data))
        return Response({
            **found,
            "items": [{**item, "price": _price_payload(item["price"])} for item in found["items"]],
        })


class PriceListOnView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_prices_on_day",
        summary="Read the price list of a past day",
        description="The company's price list as it stood when `day` ended in its time "
        "zone, read from the append-only record of price changes — each price as it was "
        "then, including ones changed or deleted since. Which of them applied on a booked "
        "day follows the same order as today's list. A day before the record began is "
        "400 `before_price_history`: the record does not know those prices.",
        tags=["booking"],
        parameters=[PriceListOnQuerySerializer],
        responses={
            200: PriceListOnSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = PriceListOnQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        found = price_list_on(query.validated_data["day"])
        return Response({**found, "items": [_price_payload(item) for item in found["items"]]})


@method_decorator(csrf_protect, name="dispatch")
class PriceRuleCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_price_create_preview",
        summary="Check a price without adding it",
        description="Validates a price as `booking_price_create` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=PriceRuleInputSerializer,
        responses={200: PriceRulePreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = PriceRuleInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_price(price_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_price_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class PriceRuleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_price_update",
        summary="Change a price",
        description="Changes a price's amount, dates or terms, or switches it off. Bookings "
        "already made keep the price they were quoted." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=PriceRuleUpdateSerializer,
        responses={200: PriceRuleSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, price_id: UUID) -> Response:
        s = PriceRuleUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_price(
            price_id=price_id, data=data, expected_version=version, idempotency_key=_idem(request)
        )
        return Response(_price_payload(saved.value))

    @extend_schema(
        operation_id="booking_price_delete",
        summary="Delete a price",
        description="Removes the price; bookings already made keep the price they were "
        "quoted." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY, _VERSION_QUERY],
        responses={204: None, **_SETUP_PROBLEMS},
    )
    def delete(self, request: Request, price_id: UUID) -> Response:
        delete_price(
            price_id=price_id, expected_version=_expected(request), idempotency_key=_idem(request)
        )
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class PriceRuleUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_price_update_preview",
        summary="Check a change to a price without saving it",
        description="Validates a change as `booking_price_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=PriceRuleUpdateSerializer,
        responses={200: PriceRulePreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, price_id: UUID) -> Response:
        s = PriceRuleUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_price(price_id=price_id, data=data, expected_version=version, preview=True)
        return Response(_with_changes(_price_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class PriceRuleCopyYearView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_prices_copy_year",
        summary="Copy a year's season prices to the next year",
        description="Every price whose season starts in `year` again a year later, as new "
        "prices; the weekdays move, so check the dates after. Base prices have no dates and "
        "are not copied." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=CopyYearInputSerializer,
        responses={201: CopyYearResultSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = CopyYearInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = copy_prices_to_next_year(
            year=s.validated_data["year"], idempotency_key=_idem(request)
        )
        return Response({"count": len(saved.value)}, status=201)


@method_decorator(csrf_protect, name="dispatch")
class PriceRuleCopyYearPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_prices_copy_year_preview",
        summary="Count the prices a copy to the next year would make",
        description="Answers as `booking_prices_copy_year` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=CopyYearInputSerializer,
        responses={200: CopyYearResultSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = CopyYearInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = copy_prices_to_next_year(year=s.validated_data["year"], preview=True)
        return Response({"count": len(saved.value)})


@method_decorator(csrf_protect, name="dispatch")
class ParticipantCategoryListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_participant_categories_list",
        summary="List the participant categories",
        description="Who comes when it changes the price — a child, a senior, a dog — "
        "switched-off ones included. A participant without a category is a standard person.",
        tags=["booking"],
        responses={200: ParticipantCategoryListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({"items": [_category_payload(item) for item in list_categories()]})

    @extend_schema(
        operation_id="booking_participant_category_create",
        summary="Add a participant category",
        description="A kind of participant a price may price on its own. Whether it counts "
        "towards a unit's capacity decides if it may be one of the people a price includes."
        + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ParticipantCategoryInputSerializer,
        responses={201: ParticipantCategorySerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = ParticipantCategoryInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_category(
            category_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_category_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class ParticipantCategoryCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_participant_category_create_preview",
        summary="Check a participant category without adding it",
        description="Validates a category as `booking_participant_category_create` would."
        + _PREVIEW_NOTE,
        tags=["booking"],
        request=ParticipantCategoryInputSerializer,
        responses={200: ParticipantCategoryPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = ParticipantCategoryInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_category(category_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_category_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class ParticipantCategoryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_participant_category_update",
        summary="Change a participant category",
        description="Renames a category, changes whether it counts towards capacity, or "
        "switches it off. A category is never deleted: bookings name it." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ParticipantCategoryUpdateSerializer,
        responses={200: ParticipantCategorySerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, category_id: UUID) -> Response:
        s = ParticipantCategoryUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_category(
            category_id=category_id,
            data=data,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(_category_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class ParticipantCategoryUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_participant_category_update_preview",
        summary="Check a change to a participant category without saving it",
        description="Validates a change as `booking_participant_category_update` would."
        + _PREVIEW_NOTE,
        tags=["booking"],
        request=ParticipantCategoryUpdateSerializer,
        responses={200: ParticipantCategoryPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, category_id: UUID) -> Response:
        s = ParticipantCategoryUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_category(
            category_id=category_id, data=data, expected_version=version, preview=True
        )
        return Response(_with_changes(_category_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class ExtraListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_extras_list",
        summary="List the offers' extras and deposits",
        description="What each offer adds to its price — mandatory or picked by the "
        "customer — and the security deposit it holds, switched-off ones included.",
        tags=["booking"],
        responses={200: ExtraListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({"items": [_extra_payload(item) for item in list_extras()]})

    @extend_schema(
        operation_id="booking_extra_create",
        summary="Add an extra or a deposit to an offer",
        description="A charge on top of the offer's price — once, per person, per night or "
        "day, or per person and night — or a security deposit, which is held and given "
        "back and never part of the total. Its currency is the company's." + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ExtraInputSerializer,
        responses={201: ExtraSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = ExtraInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_extra(
            extra_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_extra_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class ExtraCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_extra_create_preview",
        summary="Check an extra without adding it",
        description="Validates an extra as `booking_extra_create` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=ExtraInputSerializer,
        responses={200: ExtraPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = ExtraInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_extra(extra_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_extra_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class ExtraDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_extra_update",
        summary="Change an extra",
        description="Changes an extra's name, amount or terms, or switches it off. An extra "
        "is never deleted: bookings name it, and keep the amount they were quoted." + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=ExtraUpdateSerializer,
        responses={200: ExtraSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, extra_id: UUID) -> Response:
        s = ExtraUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_extra(
            extra_id=extra_id, data=data, expected_version=version, idempotency_key=_idem(request)
        )
        return Response(_extra_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class ExtraUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_extra_update_preview",
        summary="Check a change to an extra without saving it",
        description="Validates a change as `booking_extra_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=ExtraUpdateSerializer,
        responses={200: ExtraPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, extra_id: UUID) -> Response:
        s = ExtraUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_extra(extra_id=extra_id, data=data, expected_version=version, preview=True)
        return Response(_with_changes(_extra_payload(saved.value), saved.changes))
