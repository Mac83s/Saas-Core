from typing import Any, cast

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

HealthSerializer = inline_serializer(
    name="Health",
    fields={
        "status": serializers.ChoiceField(choices=["ok", "degraded"]),
        "deployment": serializers.CharField(),
        "version": serializers.CharField(),
        "correlation_id": serializers.UUIDField(),
        "checks": serializers.DictField(child=serializers.CharField()),
    },
)


def _dependency_checks() -> dict[str, str]:
    if not settings.HEALTH_CHECK_DEPENDENCIES:
        return {"database": "skipped", "cache": "skipped"}

    checks: dict[str, str] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:  # health endpoint intentionally converts infrastructure errors
        checks["database"] = "error"

    try:
        cache.set("health:probe", "ok", timeout=5)
        checks["cache"] = "ok" if cache.get("health:probe") == "ok" else "error"
    except Exception:  # health endpoint intentionally converts infrastructure errors
        checks["cache"] = "error"
    return checks


def _payload(request: Request, checks: dict[str, str]) -> dict[str, Any]:
    healthy = all(result in {"ok", "skipped"} for result in checks.values())
    return {
        "status": "ok" if healthy else "degraded",
        "deployment": settings.DEPLOYMENT,
        "version": settings.APPLICATION_VERSION,
        "correlation_id": cast(Any, request).correlation_id,
        "checks": checks,
    }


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: HealthSerializer, 503: OpenApiResponse(HealthSerializer)})
    def get(self, request: Request) -> Response:
        payload = _payload(request, _dependency_checks())
        response_status = (
            status.HTTP_200_OK
            if payload["status"] == "ok"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return Response(payload, status=response_status)


class LivenessView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: HealthSerializer})
    def get(self, request: Request) -> Response:
        return Response(_payload(request, {"process": "ok"}))
