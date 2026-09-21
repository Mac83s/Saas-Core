from __future__ import annotations

from typing import cast
from uuid import UUID

from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .serializers import (
    InventoryAdjustInputSerializer,
    InventoryBalanceSerializer,
    InventoryIssueInputSerializer,
    InventoryItemInputSerializer,
    InventoryItemSerializer,
    InventoryMovementSerializer,
    InventoryReceiptInputSerializer,
)
from .services import (
    adjust,
    balances,
    create_item,
    give_back,
    issue,
    list_items,
    movements,
    receive,
    update_item,
)

ERRORS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
}
TAGS = ["inventory"]


@method_decorator(csrf_protect, name="dispatch")
class InventoryItemListView(APIView):
    """Katalog materiałów firmy; leki są w nim kategorią."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("category", str, description="Zawęź do kategorii."),
            OpenApiParameter("q", str, description="Szukaj po nazwie."),
        ],
        responses={200: InventoryItemSerializer(many=True), **ERRORS},
        operation_id="inventory_item_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        items = list_items(
            category=request.query_params.get("category", ""),
            search=request.query_params.get("q", ""),
        )
        return Response(InventoryItemSerializer(items, many=True).data)

    @extend_schema(
        request=InventoryItemInputSerializer,
        responses={201: InventoryItemSerializer, **ERRORS},
        operation_id="inventory_item_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        serializer = InventoryItemInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = create_item(
            request=cast(HttpRequest, request), data=dict(serializer.validated_data)
        )
        return Response(InventoryItemSerializer(item).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryItemInputSerializer,
        responses={200: InventoryItemSerializer, **ERRORS},
        operation_id="inventory_item_update",
        tags=TAGS,
    )
    def patch(self, request: Request, item_id: UUID) -> Response:
        serializer = InventoryItemInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        item = update_item(
            request=cast(HttpRequest, request),
            item_id=item_id,
            data=dict(serializer.validated_data),
        )
        return Response(InventoryItemSerializer(item).data)


class InventoryBalanceView(APIView):
    """Stany: magazynu firmy, wskazanej osoby albo własne (`mine=true`)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("holder_id", str, description="Zapas jednej osoby."),
            OpenApiParameter("mine", bool, description="Mój zapas na dziś."),
        ],
        responses={200: InventoryBalanceSerializer(many=True), **ERRORS},
        operation_id="inventory_balance_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("holder_id")
        rows = balances(
            holder_id=UUID(raw) if raw else None,
            mine=request.query_params.get("mine") == "true",
        )
        return Response(InventoryBalanceSerializer(rows, many=True).data)


class InventoryMovementView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("item_id", str, description="Historia jednej pozycji.")],
        responses={200: InventoryMovementSerializer(many=True), **ERRORS},
        operation_id="inventory_movement_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("item_id")
        rows = movements(item_id=UUID(raw) if raw else None)[:200]
        return Response(InventoryMovementSerializer(rows, many=True).data)


@method_decorator(csrf_protect, name="dispatch")
class InventoryReceiptView(APIView):
    """Przyjęcie do magazynu firmy, z ceną z faktury."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryReceiptInputSerializer,
        responses={201: InventoryMovementSerializer, **ERRORS},
        operation_id="inventory_receipt_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        serializer = InventoryReceiptInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        movement = receive(
            request=cast(HttpRequest, request),
            item_id=data["item_id"],
            quantity=data["quantity"],
            unit_cost_minor=data["unit_cost_minor"],
            note=data.get("note", ""),
        )
        return Response(InventoryMovementSerializer(movement).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryIssueView(APIView):
    """Wydanie pracownikowi — pakiet, z którym wyjeżdża w teren."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryIssueInputSerializer,
        responses={201: InventoryMovementSerializer, **ERRORS},
        operation_id="inventory_issue_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        serializer = InventoryIssueInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        movement = issue(
            request=cast(HttpRequest, request),
            item_id=data["item_id"],
            holder_id=data["holder_id"],
            quantity=data["quantity"],
            note=data.get("note", ""),
        )
        return Response(InventoryMovementSerializer(movement).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryReturnView(APIView):
    """Zwrot niewykorzystanego materiału do magazynu firmy."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryIssueInputSerializer,
        responses={201: InventoryMovementSerializer, **ERRORS},
        operation_id="inventory_return_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        serializer = InventoryIssueInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        movement = give_back(
            request=cast(HttpRequest, request),
            item_id=data["item_id"],
            holder_id=data["holder_id"],
            quantity=data["quantity"],
            note=data.get("note", ""),
        )
        return Response(InventoryMovementSerializer(movement).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryAdjustView(APIView):
    """Korekta stanu: jedyna droga do poprawki, zawsze z powodem."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryAdjustInputSerializer,
        responses={201: InventoryMovementSerializer, **ERRORS},
        operation_id="inventory_adjustment_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        serializer = InventoryAdjustInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        movement = adjust(
            request=cast(HttpRequest, request),
            item_id=data["item_id"],
            holder_id=data.get("holder_id"),
            quantity=data["quantity"],
            note=data["note"],
        )
        return Response(InventoryMovementSerializer(movement).data, status=201)
