"""Versioned, constrained intake for a separately reviewed SCR generation."""

from typing import Any
from uuid import UUID

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.shared.notifications.api_key_middleware import IsSessionOrApiKey

from .blueprints import import_blueprint, read_blueprint_catalog, read_blueprint_receipt

ERRORS = {code: ProblemDetailsSerializer for code in (400, 401, 403, 404, 409, 422, 429)}


class BlueprintSlotSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    kind = serializers.ChoiceField(choices=["text"])
    max_length = serializers.IntegerField(min_value=1)
    default = serializers.CharField(allow_blank=True)


class BlueprintTemplateSerializer(serializers.Serializer[Any]):
    id = serializers.CharField()
    version = serializers.IntegerField(min_value=1)
    labels = serializers.DictField(child=serializers.CharField())
    slots = BlueprintSlotSerializer(many=True)


class BlueprintCatalogSerializer(serializers.Serializer[Any]):
    contract_version = serializers.IntegerField()
    site_id = serializers.UUIDField()
    catalog_hash = serializers.CharField()
    templates = BlueprintTemplateSerializer(many=True)


class BlueprintInputSerializer(serializers.Serializer[Any]):
    generation_id = serializers.UUIDField()
    catalog_hash = serializers.RegexField(r"^[a-f0-9]{64}$")
    template_id = serializers.CharField(max_length=120)
    template_version = serializers.IntegerField(min_value=1)
    slots = serializers.DictField(
        child=serializers.CharField(max_length=2000, trim_whitespace=False)
    )
    locale = serializers.ChoiceField(choices=["pl", "en"])
    name = serializers.CharField(max_length=160, trim_whitespace=False)
    key = serializers.RegexField(r"^[a-z0-9_-]{1,80}$")
    idempotency_key = serializers.CharField(max_length=120, trim_whitespace=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Unknown blueprint fields."]})
        if isinstance(data.get("slots"), dict) and any(
            not isinstance(value, str) for value in data["slots"].values()
        ):
            raise serializers.ValidationError({"slots": ["Only plain text is allowed."]})
        result: dict[str, Any] = super().to_internal_value(data)
        result["generation_id"] = str(result["generation_id"])
        if result["locale"] not in settings.SITES_SUPPORTED_LOCALES:
            raise serializers.ValidationError({"locale": ["Unsupported locale."]})
        return result


class BlueprintResultSerializer(serializers.Serializer[Any]):
    generation_id = serializers.UUIDField()
    site_id = serializers.UUIDField()
    page_id = serializers.UUIDField()
    proposal_id = serializers.UUIDField()
    draft_version = serializers.IntegerField(min_value=1)
    request_hash = serializers.CharField()
    published = serializers.BooleanField()


class BlueprintReceiptSerializer(serializers.Serializer[Any]):
    found = serializers.BooleanField()
    result = BlueprintResultSerializer(allow_null=True)


class BlueprintCatalogView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_blueprint_catalog",
        tags=["sites"],
        parameters=[OpenApiParameter("site_id", UUID, required=True)],
        responses={200: BlueprintCatalogSerializer, **ERRORS},
    )
    def get(self, request: Request) -> Response:
        field = serializers.UUIDField()
        site_id = field.run_validation(request.query_params.get("site_id"))
        response = Response(read_blueprint_catalog(site_id=site_id))
        response["Cache-Control"] = "private, no-store"
        return response


class BlueprintDraftView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_blueprint_draft_receipt",
        tags=["sites"],
        parameters=[OpenApiParameter("idempotency_key", str, required=True)],
        responses={200: BlueprintReceiptSerializer, **ERRORS},
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        key = serializers.CharField(max_length=120).run_validation(
            request.query_params.get("idempotency_key")
        )
        response = Response(read_blueprint_receipt(site_id=site_id, idempotency_key=key))
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(
        operation_id="sites_blueprint_draft_create",
        tags=["sites"],
        request=BlueprintInputSerializer,
        responses={200: BlueprintResultSerializer, 201: BlueprintResultSerializer, **ERRORS},
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        serializer = BlueprintInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result, created = import_blueprint(site_id=site_id, document=serializer.validated_data)
        response = Response(result, status=201 if created else 200)
        response["Cache-Control"] = "private, no-store"
        return response
