from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .serializers import (
    BillingSessionSerializer,
    CheckoutCreateSerializer,
    EntitlementSupportReportSerializer,
    StripeWebhookReceiptSerializer,
)
from .services import create_customer_portal, create_setup_checkout
from .support import entitlement_support_report
from .webhooks import InvalidStripeWebhook, StripeWebhookConflict, ingest_stripe_webhook


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        auth=[],
        operation_id="billing_stripe_webhook",
        tags=["billing"],
        request={"application/json": OpenApiTypes.OBJECT},
        responses={
            200: StripeWebhookReceiptSerializer,
            202: StripeWebhookReceiptSerializer,
            400: StripeWebhookReceiptSerializer,
            409: StripeWebhookReceiptSerializer,
            503: StripeWebhookReceiptSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        try:
            receipt = ingest_stripe_webhook(
                payload=request.body,
                signature=request.headers.get("Stripe-Signature", ""),
            )
        except InvalidStripeWebhook:
            return Response({"received": False}, status=status.HTTP_400_BAD_REQUEST)
        except StripeWebhookConflict:
            return Response({"received": False}, status=status.HTTP_409_CONFLICT)
        except ImproperlyConfigured:
            return Response(
                {"received": False},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {"received": True},
            status=(status.HTTP_202_ACCEPTED if receipt.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class BillingCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="billing_checkout_create",
        tags=["billing"],
        request=CheckoutCreateSerializer,
        responses={
            200: BillingSessionSerializer,
            201: BillingSessionSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            502: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = CheckoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_setup_checkout(
            plan_key=serializer.validated_data["plan"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            {
                "id": result.checkout.stripe_checkout_session_id,
                "url": result.checkout.checkout_url,
                "expires_at": result.checkout.expires_at,
            },
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class BillingPortalView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="billing_portal_create",
        tags=["billing"],
        request=None,
        responses={
            200: BillingSessionSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            502: ProblemDetailsSerializer,
        },
    )
    def post(self, _request: Request) -> Response:
        result = create_customer_portal()
        return Response({"id": result.session_id, "url": result.url})


class BillingEntitlementSupportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="billing_entitlement_support",
        tags=["billing"],
        responses={
            200: EntitlementSupportReportSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request) -> Response:
        return Response(entitlement_support_report())
