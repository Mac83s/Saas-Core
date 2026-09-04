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

from .overview import customer_billing_overview
from .serializers import (
    BillingDetailsSerializer,
    BillingDetailsStateSerializer,
    BillingSessionSerializer,
    CheckoutCreateSerializer,
    CustomerBillingOverviewSerializer,
    EntitlementSupportReportSerializer,
    StripeWebhookReceiptSerializer,
    TrialActivationCreateSerializer,
    TrialActivationResultSerializer,
)
from .services import (
    activate_customer_trial,
    create_customer_portal,
    create_setup_checkout,
    missing_billing_details,
    update_billing_details,
)
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
class BillingDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="billing_details_update",
        tags=["billing"],
        request=BillingDetailsSerializer,
        responses={
            200: BillingDetailsStateSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request) -> Response:
        serializer = BillingDetailsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = update_billing_details(changes=dict(serializer.validated_data))
        return Response(
            {
                **serializer.validated_data,
                "missing": missing_billing_details(profile),
            }
        )


class BillingOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="billing_overview_retrieve",
        tags=["billing"],
        responses={
            200: CustomerBillingOverviewSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request) -> Response:
        return Response(customer_billing_overview())


@method_decorator(csrf_protect, name="dispatch")
class BillingTrialActivationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="billing_trial_activation_create",
        tags=["billing"],
        request=TrialActivationCreateSerializer,
        responses={
            200: TrialActivationResultSerializer,
            201: TrialActivationResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            502: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = TrialActivationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = activate_customer_trial(
            checkout_session_id=serializer.validated_data["checkout_session_id"]
        )
        return Response(
            {
                "id": result.activation.id,
                "status": result.activation.status,
                "created": result.created,
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
