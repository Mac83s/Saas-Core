from __future__ import annotations

import hashlib
import json
from uuid import UUID

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.shared.billing.authorization import authorize_entitled

from .models import ApiKey, WebhookEndpoint
from .security import verify_provider_webhook
from .serializers import (
    ApiKeyCreateSerializer,
    ApiKeyListSerializer,
    ApiKeySerializer,
    DataExportCreateSerializer,
    DataExportSerializer,
    MessageStatusSerializer,
    PreferenceSerializer,
    ProviderStatusSerializer,
    SupportHealthSerializer,
    SupportRetrySerializer,
    TemplateCatalogSerializer,
    TemplatePreviewResultSerializer,
    TemplatePreviewSerializer,
    WebhookCreateSerializer,
    WebhookListSerializer,
    WebhookSerializer,
)
from .services import (
    create_data_export,
    create_webhook_endpoint,
    get_preferences,
    ingest_provider_status,
    issue_api_key,
    issue_export_token,
    preview_email,
    resolve_data_export,
    revoke_api_key,
    rotate_api_key,
    support_health,
    support_retry_message,
    support_retry_webhook,
    upsert_preferences,
)
from .templates import template_catalog

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    "Idempotency-Key", str, OpenApiParameter.HEADER, required=True
)


class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notification_preferences_get",
        tags=["notifications"],
        responses={200: PreferenceSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        value = get_preferences()
        return Response({"locale": value.locale, "marketing_enabled": value.marketing_enabled})

    @extend_schema(
        operation_id="notification_preferences_update",
        tags=["notifications"],
        request=PreferenceSerializer,
        responses={200: PreferenceSerializer, 403: ProblemDetailsSerializer},
    )
    def put(self, request: Request) -> Response:
        serializer = PreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = upsert_preferences(**serializer.validated_data)
        return Response({"locale": value.locale, "marketing_enabled": value.marketing_enabled})


class TemplateCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notification_templates_list",
        tags=["notifications"],
        responses={200: TemplateCatalogSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        authorize_entitled("notifications.manage", "notifications.enabled")
        return Response({"items": template_catalog()})


@method_decorator(csrf_protect, name="dispatch")
class TemplatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notification_template_preview",
        tags=["notifications"],
        request=TemplatePreviewSerializer,
        responses={200: TemplatePreviewResultSerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = TemplatePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(preview_email(**serializer.validated_data))


@method_decorator(csrf_protect, name="dispatch")
class ApiKeyListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_api_keys_list",
        tags=["integrations"],
        responses={200: ApiKeyListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        authorize("integrations.manage")
        return Response({
            "items": [_api_key_payload(item) for item in ApiKey.all_objects.order_by("-created_at")]
        })

    @extend_schema(
        operation_id="integration_api_keys_create",
        tags=["integrations"],
        request=ApiKeyCreateSerializer,
        responses={201: ApiKeySerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ApiKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued = issue_api_key(**serializer.validated_data)
        return Response(
            {**_api_key_payload(issued.api_key), "secret": issued.secret},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class ApiKeyRotateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_api_keys_rotate",
        tags=["integrations"],
        request=None,
        responses={201: ApiKeySerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request, key_id: UUID) -> Response:
        del request
        issued = rotate_api_key(key_id=key_id)
        return Response(
            {**_api_key_payload(issued.api_key), "secret": issued.secret},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_protect, name="dispatch")
class ApiKeyRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_api_keys_revoke",
        tags=["integrations"],
        request=None,
        responses={200: ApiKeySerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request, key_id: UUID) -> Response:
        del request
        return Response(_api_key_payload(revoke_api_key(key_id=key_id)))


@method_decorator(csrf_protect, name="dispatch")
class WebhookListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_webhooks_list",
        tags=["integrations"],
        responses={200: WebhookListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        authorize("integrations.manage")
        return Response({
            "items": [
                _webhook_payload(item)
                for item in WebhookEndpoint.all_objects.order_by("-created_at")
            ]
        })

    @extend_schema(
        operation_id="integration_webhooks_create",
        tags=["integrations"],
        request=WebhookCreateSerializer,
        responses={201: WebhookSerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = WebhookCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        endpoint, secret = create_webhook_endpoint(**serializer.validated_data)
        return Response(
            {**_webhook_payload(endpoint), "secret": secret}, status=status.HTTP_201_CREATED
        )


class SupportHealthView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notification_support_health",
        tags=["notifications-support"],
        responses={200: SupportHealthSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response(support_health())


@method_decorator(csrf_protect, name="dispatch")
class SupportMessageRetryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notification_support_message_retry",
        tags=["notifications-support"],
        request=SupportRetrySerializer,
        responses={200: MessageStatusSerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request, message_id: UUID) -> Response:
        serializer = SupportRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = support_retry_message(message_id=message_id, **serializer.validated_data)
        return Response({"id": message.id, "status": message.status})


@method_decorator(csrf_protect, name="dispatch")
class SupportWebhookRetryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notification_support_webhook_retry",
        tags=["notifications-support"],
        request=SupportRetrySerializer,
        responses={200: MessageStatusSerializer, 403: ProblemDetailsSerializer},
    )
    def post(self, request: Request, delivery_id: UUID) -> Response:
        serializer = SupportRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = support_retry_webhook(delivery_id=delivery_id, **serializer.validated_data)
        return Response({"id": delivery.id, "status": delivery.status})


class DataExportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_exports_get",
        tags=["integrations"],
        responses={200: DataExportSerializer, 404: ProblemDetailsSerializer},
    )
    def get(self, request: Request, export_id: UUID) -> Response:
        del request
        authorize("integrations.manage")
        from .models import DataExport

        export = DataExport.all_objects.filter(pk=export_id).first()
        if export is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("Eksport nie istnieje.")
        return Response({
            "id": export.id,
            "status": export.status,
            "expires_at": export.expires_at,
            "download_token": (issue_export_token(export) if export.status == "ready" else None),
        })


@method_decorator(csrf_protect, name="dispatch")
class DataExportCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_exports_create",
        tags=["integrations"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=DataExportCreateSerializer,
        responses={
            200: DataExportSerializer,
            201: DataExportSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = DataExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        export, created = create_data_export(
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            {
                "id": export.id,
                "status": export.status,
                "expires_at": export.expires_at,
                "download_token": issue_export_token(export) if export.status == "ready" else None,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class DataExportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="integration_exports_download",
        tags=["integrations"],
        parameters=[OpenApiParameter("token", str, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.BINARY, 404: ProblemDetailsSerializer},
    )
    def get(self, request: Request, export_id: UUID) -> HttpResponse:
        export = resolve_data_export(
            export_id=export_id, token=request.query_params.get("token", "")
        )
        response = HttpResponse(export.content, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{export.kind}-{export.id}.json"'
        response["Cache-Control"] = "private, no-store"
        return response


@method_decorator(csrf_exempt, name="dispatch")
class ProviderStatusWebhookView(APIView):
    authentication_classes: list[type[BaseAuthentication]] = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="notification_provider_status",
        tags=["notifications-provider"],
        request=ProviderStatusSerializer,
        responses={200: None, 202: None, 400: ProblemDetailsSerializer},
    )
    def post(self, request: Request) -> Response:
        raw = request.body
        if len(raw) > 65_536:
            raise ParseError("Webhook przekracza limit rozmiaru.")
        verify_provider_webhook(
            body=raw,
            timestamp=request.headers.get("X-Provider-Timestamp", ""),
            signature=request.headers.get("X-Provider-Signature", ""),
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        serializer = ProviderStatusSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        _, created = ingest_provider_status(
            **serializer.validated_data,
            payload_digest=hashlib.sha256(raw).hexdigest(),
        )
        return Response(status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


def _api_key_payload(value: ApiKey) -> dict[str, object]:
    return {
        "id": value.id,
        "name": value.name,
        "prefix": value.prefix,
        "scopes": value.scopes,
        "revoked_at": value.revoked_at,
        "expires_at": value.expires_at,
        "created_at": value.created_at,
    }


def _webhook_payload(value: WebhookEndpoint) -> dict[str, object]:
    return {
        "id": value.id,
        "name": value.name,
        "url": value.url,
        "events": value.events,
        "active": value.active,
        "secret_hint": value.secret_hint,
        "created_at": value.created_at,
    }
