from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .callbacks import receive_callback
from .serializers import (
    AuditListQuerySerializer,
    AuditListSerializer,
    AuditOfferSerializer,
    AuditOrderSerializer,
    AuditOrderSummarySerializer,
    AuditRequestSerializer,
    CallbackEnvelopeSerializer,
    CallbackResultSerializer,
)
from .services import list_audits, read_audit, read_audit_offer, request_audit


class AuditListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="seo_audits_list",
        parameters=[AuditListQuerySerializer],
        responses=AuditListSerializer,
    )
    def get(self, request: Request) -> Response:
        query = AuditListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, cursor = list_audits(
            cursor=query.validated_data.get("cursor"), limit=query.validated_data["limit"]
        )
        return Response(
            {
                "items": AuditOrderSummarySerializer(rows, many=True).data,
                "next_cursor": str(cursor) if cursor else None,
            },
            headers={"Cache-Control": "private, no-store"},
        )

    @method_decorator(csrf_protect)
    @extend_schema(
        request=AuditRequestSerializer,
        responses={201: AuditOrderSerializer, 200: AuditOrderSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AuditRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order, created = request_audit(
            site_id=data["site_id"],
            idempotency_key=data["idempotency_key"],
            options={"max_pages": data["max_pages"]} if "max_pages" in data else {},
            expected_credit_cost=data.get("expected_credit_cost"),
        )
        return Response(
            AuditOrderSerializer(order).data,
            status=201 if created else 200,
            headers={"Cache-Control": "private, no-store"},
        )


class AuditDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=AuditOrderSerializer)
    def get(self, request: Request, order_id: UUID) -> Response:
        return Response(
            AuditOrderSerializer(read_audit(order_id=order_id)).data,
            headers={"Cache-Control": "private, no-store"},
        )


class SsaCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=CallbackEnvelopeSerializer,
        responses=CallbackResultSerializer,
        parameters=[
            OpenApiParameter(name=name, location=OpenApiParameter.HEADER, required=True, type=str)
            for name in ("webhook-id", "webhook-timestamp", "webhook-signature")
        ],
    )
    def post(self, request: Request) -> Response:
        receive_callback(request.body, request.headers)
        return Response({"accepted": True})


class AuditOfferView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=AuditOfferSerializer)
    def get(self, request: Request) -> Response:
        return Response(read_audit_offer(), headers={"Cache-Control": "private, no-store"})
