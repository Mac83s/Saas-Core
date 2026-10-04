from typing import Any, cast
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .orders import list_orders, options, read_order
from .payments import record_payment, void_payment
from .refunds import record_refund, void_refund
from .serializers import (
    CommerceOptionsSerializer,
    OrderPageSerializer,
    OrderQuerySerializer,
    OrderSerializer,
    PaymentEffectSerializer,
    PaymentRecordInputSerializer,
    PaymentVoidInputSerializer,
    RefundEffectSerializer,
    RefundRecordInputSerializer,
)

_TAGS = ["commerce"]
_VERSION_LOCKED = {
    "x-quality-exempt": {
        "idempotency-key": "Locked by the order's version: a repeat at the same version "
        "answers 409 and changes nothing.",
    }
}
_WRITE_PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}


class OptionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_options_read",
        summary="What orders can hold and be filtered by",
        description="The company's currency, the statuses and channels of an order, the "
        "sources that place orders in this product with the prefix of their numbers, the "
        "kinds of a line and the tax rate codes.",
        tags=_TAGS,
        responses={200: CommerceOptionsSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        return Response(options())


class OrderListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_orders_list",
        summary="The company's orders",
        description="Newest first, a page at a time. Filter by `status`, `channel`, "
        "`source` or one customer, or search with `q` — a part of a number, of the buyer's "
        "name or of their e-mail.",
        tags=_TAGS,
        parameters=[OrderQuerySerializer],
        responses={
            200: OrderPageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = OrderQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = cast(dict[str, Any], query.validated_data)
        return Response(list_orders(query=filters.pop("q", ""), **filters))


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_read",
        summary="One order with its lines",
        description="The buyer as they were when it was placed, the lines in force with "
        "what each comes to, and what every earlier revision came to when a source priced "
        "its record again.",
        tags=_TAGS,
        responses={
            200: OrderSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, order_id: UUID) -> Response:
        return Response(read_order(order_id))


class PaymentPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_payment_preview",
        summary="What marking a payment would do",
        description="Checks the payment exactly as the write does — the order's version, "
        "the method, the amount against what is left to pay — and says what would be paid, "
        "what would be left and the order's status. Writes nothing.",
        tags=_TAGS,
        request=PaymentRecordInputSerializer,
        responses={200: PaymentEffectSerializer, **_WRITE_PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        serializer = PaymentRecordInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)
        return Response(record_payment(order_id, preview=True, **data))


@method_decorator(csrf_protect, name="dispatch")
class PaymentListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_payment_record",
        summary="Mark a payment the company received",
        description="The customer paid at the desk or the company saw their transfer: "
        "writes the payment and its ledger entry and moves the order's status "
        "(`partially_paid`, `paid`). More than what is left to pay is refused "
        "(`amount_exceeds_due`), so is a payment for a canceled order (`order_canceled`). "
        "Where the order waits for a payment (`requires_payment`), an amount that covers "
        "it marks that payment and confirms the booking the order is for; a smaller one "
        "leaves the rest awaited. Answers with the order.",
        tags=_TAGS,
        request=PaymentRecordInputSerializer,
        responses={201: OrderSerializer, **_WRITE_PROBLEMS},
        extensions=_VERSION_LOCKED,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        serializer = PaymentRecordInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)
        return Response(record_payment(order_id, **data), status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class PaymentVoidView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_payment_void",
        summary="Take back a payment marked by mistake",
        description="The payment stays in the order's history as `canceled` and the ledger "
        "gets the opposite entry, so the order owes that amount again. Not a refund: no "
        "money went back to anybody. Only a payment marked by hand can be taken back. A "
        "booking the payment confirmed stays confirmed — calling it off is the company's "
        "own decision. Answers with the order.",
        tags=_TAGS,
        request=PaymentVoidInputSerializer,
        responses={200: OrderSerializer, **_WRITE_PROBLEMS},
        extensions=_VERSION_LOCKED,
    )
    def post(self, request: Request, order_id: UUID, payment_id: UUID) -> Response:
        serializer = PaymentVoidInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)
        return Response(void_payment(order_id, payment_id, **data))


class RefundPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_refund_preview",
        summary="What marking a refund would do",
        description="Checks the refund exactly as the write does — the order's version, "
        "the method, the amount against what the customer has paid — and says what would "
        "stay paid, what the order's terms would still owe back and whether the amount "
        "needs a reason. Writes nothing.",
        tags=_TAGS,
        request=RefundRecordInputSerializer,
        responses={200: RefundEffectSerializer, **_WRITE_PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        serializer = RefundRecordInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)
        return Response(record_refund(order_id, preview=True, **data))


@method_decorator(csrf_protect, name="dispatch")
class RefundListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_refund_record",
        summary="Mark money the company gave back",
        description="The company returned money to the order's customer itself — a "
        "transfer back or cash at the desk: writes the refund and its ledger entry, so "
        "the order's `paid_minor` goes down by it. More than the customer has paid is "
        "refused (`refund_exceeds_paid`). Within what the order's terms give back "
        "(`refund_owed_minor`, settled when the order was canceled) no reason is asked "
        "for; beyond it the company says why (`reason_required`). Nothing is sent to the "
        "customer and no money moves: it records what the company did. Answers with the "
        "order.",
        tags=_TAGS,
        request=RefundRecordInputSerializer,
        responses={201: OrderSerializer, **_WRITE_PROBLEMS},
        extensions=_VERSION_LOCKED,
    )
    def post(self, request: Request, order_id: UUID) -> Response:
        serializer = RefundRecordInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)
        return Response(record_refund(order_id, **data), status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class RefundVoidView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="commerce_order_refund_void",
        summary="Take back a refund marked by mistake",
        description="The refund stays in the order's history as `canceled` and the ledger "
        "gets the opposite entry, so the order is paid that amount again and, where its "
        "terms said so, owes it back again. Answers with the order.",
        tags=_TAGS,
        request=PaymentVoidInputSerializer,
        responses={200: OrderSerializer, **_WRITE_PROBLEMS},
        extensions=_VERSION_LOCKED,
    )
    def post(self, request: Request, order_id: UUID, refund_id: UUID) -> Response:
        serializer = PaymentVoidInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)
        return Response(void_refund(order_id, refund_id, **data))
