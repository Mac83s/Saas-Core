from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .orders import list_orders, options, read_order
from .serializers import (
    CommerceOptionsSerializer,
    OrderPageSerializer,
    OrderQuerySerializer,
    OrderSerializer,
)

_TAGS = ["commerce"]


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
