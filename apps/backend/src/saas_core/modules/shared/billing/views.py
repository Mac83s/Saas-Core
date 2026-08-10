from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import StripeWebhookReceiptSerializer
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
