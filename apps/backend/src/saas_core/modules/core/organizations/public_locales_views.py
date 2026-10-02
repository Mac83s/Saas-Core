"""The company's languages (ADR-071 pkt 5): read, preview a change, change."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .public_locales import (
    PublicLocalesLimit,
    PublicLocalesPlan,
    change_public_locales,
    read_public_locales,
)
from .public_locales_serializers import (
    PublicLocalesChangeSerializer,
    PublicLocalesPlanSerializer,
    PublicLocalesSerializer,
)

PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}
IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia: powtórka zwraca pierwszą zmianę.",
)


def _limit(limit: PublicLocalesLimit) -> dict[str, Any]:
    return {
        "allowed": limit.allowed,
        "additional_max": limit.additional_max,
        "reason": limit.reason,
    }


def _plan(plan: PublicLocalesPlan) -> dict[str, Any]:
    return {
        "before": list(plan.before),
        "public_locales": list(plan.after),
        "added": list(plan.added),
        "removed": list(plan.removed),
        "version": plan.version,
        "limit": _limit(plan.limit),
        "person_gates": sorted(plan.person_gates),
        "redirects": [
            {"locale": item.locale, "path": item.path, "target": item.target}
            for item in plan.redirects
        ],
    }


def _change(request: Request, *, preview: bool) -> Response:
    serializer = PublicLocalesChangeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    plan = change_public_locales(
        locales=serializer.validated_data["public_locales"],
        expected_version=serializer.validated_data["expected_version"],
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        preview=preview,
    )
    return Response(_plan(plan))


@method_decorator(csrf_protect, name="dispatch")
class PublicLocalesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="organizations_public_locales_retrieve",
        summary="Read the company's languages",
        description="The company's content languages in order (the first is its customers' "
        "language), their own version, the languages this product offers, the plan's limit "
        "and the languages that cannot be removed. The assistant reads the same through "
        "organization.public_locales.read@1.",
        tags=["organizations"],
        responses={200: PublicLocalesSerializer, **PROBLEMS},
    )
    def get(self, _request: Request) -> Response:
        state = read_public_locales()
        return Response({
            "public_locales": list(state.locales),
            "version": state.version,
            "offered": [
                {
                    "code": code,
                    "native_name": settings.LOCALE_REGISTRY[code].native_name,
                    "english_name": settings.LOCALE_REGISTRY[code].english_name,
                }
                for code in state.offered
            ],
            "limit": _limit(state.limit),
            "protected": dict(state.protected),
        })

    @extend_schema(
        operation_id="organizations_public_locales_update",
        summary="Change the company's languages",
        description="Replaces the list, guarded by `expected_version` (a stale one answers "
        "409 settings_version_conflict). Adding a language counts against the plan "
        "(`quota_exceeded`, `plan_access_denied`); removing and reordering always work, "
        "except for a site's source language (`site_default_not_removable`), and removing is "
        "a person's decision (403 person_required for the assistant without consent). The "
        "assistant changes the same through organization.public_locales.update@1.",
        tags=["organizations"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=PublicLocalesChangeSerializer,
        responses={200: PublicLocalesPlanSerializer, **PROBLEMS},
    )
    def put(self, request: Request) -> Response:
        return _change(request, preview=False)


@method_decorator(csrf_protect, name="dispatch")
class PublicLocalesPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="organizations_public_locales_preview",
        summary="See what a change of the company's languages would do",
        description="The same checks as the change, and nothing saved: what is added and "
        "removed, the version after, the plan's limit and the decisions only a person makes.",
        tags=["organizations"],
        request=PublicLocalesChangeSerializer,
        responses={200: PublicLocalesPlanSerializer, **PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request) -> Response:
        return _change(request, preview=True)
