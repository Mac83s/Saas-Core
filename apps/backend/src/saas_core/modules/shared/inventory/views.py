from __future__ import annotations

from typing import Any, cast
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

from . import services
from .serializers import (
    InventoryAdjustInputSerializer,
    InventoryBalanceSerializer,
    InventoryCategorySerializer,
    InventoryIssueInputSerializer,
    InventoryItemInputSerializer,
    InventoryItemSerializer,
    InventoryMovementSerializer,
    InventoryReceiptInputSerializer,
    StockDocumentCorrectionSerializer,
    StockDocumentInputSerializer,
    StockDocumentSerializer,
    StockLocationSerializer,
    SupplierSerializer,
)

ERRORS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}
TAGS = ["inventory"]


def _valid(serializer_class: Any, request: Request, *, partial: bool = False) -> dict[str, Any]:
    serializer = serializer_class(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _uuid(request: Request, name: str) -> UUID | None:
    raw = request.query_params.get(name)
    return UUID(raw) if raw else None


def _http(request: Request) -> HttpRequest:
    return cast(HttpRequest, request)


def _lines(raw: list[dict[str, Any]] | None) -> list[services.LineInput] | None:
    if raw is None:
        return None
    return [
        services.LineInput(
            item_id=line["item_id"],
            quantity=line["quantity"],
            unit_price_minor=line.get("unit_price_minor"),
            note=line.get("note", ""),
        )
        for line in raw
    ]


@method_decorator(csrf_protect, name="dispatch")
class InventoryCategoryListView(APIView):
    """Kategorie firmy; zestaw startowy deklaruje produkt."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: InventoryCategorySerializer(many=True), **ERRORS},
        operation_id="inventory_category_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        return Response(InventoryCategorySerializer(services.list_categories(), many=True).data)

    @extend_schema(
        request=InventoryCategorySerializer,
        responses={201: InventoryCategorySerializer, **ERRORS},
        operation_id="inventory_category_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(InventoryCategorySerializer, request)
        category = services.create_category(request=_http(request), name=data["name"])
        return Response(InventoryCategorySerializer(category).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryCategoryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryCategorySerializer,
        responses={200: InventoryCategorySerializer, **ERRORS},
        operation_id="inventory_category_update",
        tags=TAGS,
    )
    def patch(self, request: Request, category_id: UUID) -> Response:
        data = _valid(InventoryCategorySerializer, request)
        category = services.rename_category(
            request=_http(request), category_id=category_id, name=data["name"]
        )
        return Response(InventoryCategorySerializer(category).data)

    @extend_schema(
        responses={204: None, **ERRORS},
        operation_id="inventory_category_delete",
        tags=TAGS,
    )
    def delete(self, request: Request, category_id: UUID) -> Response:
        services.delete_category(request=_http(request), category_id=category_id)
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class StockLocationListView(APIView):
    """Magazyny firmy i zapasy osób."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: StockLocationSerializer(many=True), **ERRORS},
        operation_id="inventory_location_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        return Response(StockLocationSerializer(services.list_locations(), many=True).data)

    @extend_schema(
        request=StockLocationSerializer,
        responses={201: StockLocationSerializer, **ERRORS},
        operation_id="inventory_location_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(StockLocationSerializer, request)
        location = services.create_warehouse(request=_http(request), name=data["name"])
        return Response(StockLocationSerializer(location).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class StockLocationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=StockLocationSerializer,
        responses={200: StockLocationSerializer, **ERRORS},
        operation_id="inventory_location_update",
        tags=TAGS,
    )
    def patch(self, request: Request, location_id: UUID) -> Response:
        data = _valid(StockLocationSerializer, request, partial=True)
        location = services.update_location(
            request=_http(request), location_id=location_id, data=data
        )
        return Response(StockLocationSerializer(location).data)


@method_decorator(csrf_protect, name="dispatch")
class SupplierListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: SupplierSerializer(many=True), **ERRORS},
        operation_id="inventory_supplier_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        return Response(SupplierSerializer(services.list_suppliers(), many=True).data)

    @extend_schema(
        request=SupplierSerializer,
        responses={201: SupplierSerializer, **ERRORS},
        operation_id="inventory_supplier_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        supplier = services.save_supplier(
            request=_http(request), data=_valid(SupplierSerializer, request)
        )
        return Response(SupplierSerializer(supplier).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class SupplierDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SupplierSerializer,
        responses={200: SupplierSerializer, **ERRORS},
        operation_id="inventory_supplier_update",
        tags=TAGS,
    )
    def patch(self, request: Request, supplier_id: UUID) -> Response:
        supplier = services.save_supplier(
            request=_http(request),
            supplier_id=supplier_id,
            data=_valid(SupplierSerializer, request, partial=True),
        )
        return Response(SupplierSerializer(supplier).data)


@method_decorator(csrf_protect, name="dispatch")
class InventoryItemListView(APIView):
    """Katalog towarów firmy: jedna pozycja to jeden SKU."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("category", str, description="Id albo klucz kategorii."),
            OpenApiParameter("q", str, description="Nazwa, SKU albo EAN."),
        ],
        responses={200: InventoryItemSerializer(many=True), **ERRORS},
        operation_id="inventory_item_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        items = services.list_items(
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
        item = services.create_item(
            request=_http(request), data=_valid(InventoryItemInputSerializer, request)
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
        item = services.update_item(
            request=_http(request),
            item_id=item_id,
            data=_valid(InventoryItemInputSerializer, request, partial=True),
        )
        return Response(InventoryItemSerializer(item).data)


class InventoryBalanceView(APIView):
    """Stany jednego miejsca; bez parametrów — magazyn główny."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("location_id", str, description="Jedno miejsce składowania."),
            OpenApiParameter("holder_id", str, description="Zapas jednej osoby."),
            OpenApiParameter("mine", bool, description="Mój zapas na dziś."),
        ],
        responses={200: InventoryBalanceSerializer(many=True), **ERRORS},
        operation_id="inventory_balance_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        rows = services.balances(
            location_id=_uuid(request, "location_id"),
            holder_id=_uuid(request, "holder_id"),
            mine=request.query_params.get("mine") == "true",
        )
        return Response(InventoryBalanceSerializer(rows, many=True).data)


class InventoryMovementView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("item_id", str, description="Historia jednej pozycji."),
            OpenApiParameter("location_id", str, description="Historia jednego miejsca."),
        ],
        responses={200: InventoryMovementSerializer(many=True), **ERRORS},
        operation_id="inventory_movement_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        rows = services.movements(
            item_id=_uuid(request, "item_id"), location_id=_uuid(request, "location_id")
        )[:200]
        return Response(InventoryMovementSerializer(rows, many=True).data)


@method_decorator(csrf_protect, name="dispatch")
class StockDocumentListView(APIView):
    """Dokumenty magazynowe: PZ, WZ, RW, PW, MM, INW."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, description="Rodzaj dokumentu."),
            OpenApiParameter("status", str, description="draft albo posted."),
        ],
        responses={200: StockDocumentSerializer(many=True), **ERRORS},
        operation_id="inventory_document_list",
        tags=TAGS,
    )
    def get(self, request: Request) -> Response:
        rows = services.list_documents(
            kind=request.query_params.get("kind", ""),
            status=request.query_params.get("status", ""),
        )
        return Response(StockDocumentSerializer(rows, many=True).data)

    @extend_schema(
        request=StockDocumentInputSerializer,
        responses={201: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_document_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(StockDocumentInputSerializer, request)
        document = services.create_document(
            request=_http(request),
            kind=data.pop("kind"),
            lines=_lines(data.pop("lines", [])) or [],
            data=data,
        )
        return Response(StockDocumentSerializer(document).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class StockDocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_document_read",
        tags=TAGS,
    )
    def get(self, request: Request, document_id: UUID) -> Response:
        return Response(StockDocumentSerializer(services.get_document(document_id)).data)

    @extend_schema(
        request=StockDocumentInputSerializer,
        responses={200: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_document_update",
        tags=TAGS,
    )
    def patch(self, request: Request, document_id: UUID) -> Response:
        data = _valid(StockDocumentInputSerializer, request, partial=True)
        data.pop("kind", None)
        document = services.update_document(
            request=_http(request),
            document_id=document_id,
            lines=_lines(data.pop("lines", None)),
            data=data,
        )
        return Response(StockDocumentSerializer(document).data)


@method_decorator(csrf_protect, name="dispatch")
class StockDocumentPostView(APIView):
    """Zatwierdzenie: wiersze stają się ruchami, dokument dostaje numer."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_document_post",
        tags=TAGS,
    )
    def post(self, request: Request, document_id: UUID) -> Response:
        document = services.post_document(request=_http(request), document_id=document_id)
        return Response(StockDocumentSerializer(document).data)


@method_decorator(csrf_protect, name="dispatch")
class StockDocumentCorrectView(APIView):
    """Korekta: nowy dokument, który cofa ruchy zatwierdzonego."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=StockDocumentCorrectionSerializer,
        responses={201: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_document_correct",
        tags=TAGS,
    )
    def post(self, request: Request, document_id: UUID) -> Response:
        data = _valid(StockDocumentCorrectionSerializer, request)
        correction = services.correct_document(
            request=_http(request), document_id=document_id, note=data.get("note", "")
        )
        return Response(StockDocumentSerializer(correction).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryReceiptView(APIView):
    """Skrót: przyjęcie do magazynu głównego z ceną z faktury (PZ)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryReceiptInputSerializer,
        responses={201: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_receipt_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(InventoryReceiptInputSerializer, request)
        document = services.receive(
            request=_http(request),
            item_id=data["item_id"],
            quantity=data["quantity"],
            unit_cost_minor=data["unit_cost_minor"],
            note=data.get("note", ""),
        )
        return Response(StockDocumentSerializer(document).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryIssueView(APIView):
    """Skrót: wydanie osobie — pakiet, z którym wyjeżdża w teren (MM)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryIssueInputSerializer,
        responses={201: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_issue_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(InventoryIssueInputSerializer, request)
        document = services.issue(
            request=_http(request),
            item_id=data["item_id"],
            holder_id=data["holder_id"],
            quantity=data["quantity"],
            note=data.get("note", ""),
        )
        return Response(StockDocumentSerializer(document).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryReturnView(APIView):
    """Skrót: zwrot niewykorzystanego towaru do magazynu głównego (MM)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryIssueInputSerializer,
        responses={201: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_return_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(InventoryIssueInputSerializer, request)
        document = services.give_back(
            request=_http(request),
            item_id=data["item_id"],
            holder_id=data["holder_id"],
            quantity=data["quantity"],
            note=data.get("note", ""),
        )
        return Response(StockDocumentSerializer(document).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class InventoryAdjustView(APIView):
    """Skrót: korekta stanu z powodem — nadwyżka PW, ubytek RW."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InventoryAdjustInputSerializer,
        responses={201: StockDocumentSerializer, **ERRORS},
        operation_id="inventory_adjustment_create",
        tags=TAGS,
    )
    def post(self, request: Request) -> Response:
        data = _valid(InventoryAdjustInputSerializer, request)
        document = services.adjust(
            request=_http(request),
            item_id=data["item_id"],
            holder_id=data.get("holder_id"),
            quantity=data["quantity"],
            note=data["note"],
        )
        return Response(StockDocumentSerializer(document).data, status=201)
