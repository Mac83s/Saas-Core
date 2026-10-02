"""Operator reads: what the port can do now and what it has cost (ADR-068 pkt 8).

Staff on a managed session after MFA only — the same gate as the operator
admin, until the settings plan brings its operator gate. No endpoint of a
company reads the telemetry.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce, TruncDay
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.admin_site import is_mfa_operator
from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from . import admission
from .api import budget_state, task_status
from .budgets import current_budgets, micros
from .models import EntryKind, UsageEntry
from .registry import registered_tasks
from .types import ModelContext

GROUPS = {"task": "task", "model": "resolved_model", "organization": "organization_id"}


class IsMfaOperator(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return is_mfa_operator(request)


class TaskStatusSerializer(serializers.Serializer[dict[str, Any]]):
    task = serializers.CharField()
    available = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True)
    until = serializers.DateTimeField(allow_null=True)
    model = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())


class LevelSerializer(serializers.Serializer[dict[str, Any]]):
    level = serializers.CharField()
    spent_usd_micros = serializers.IntegerField()
    cap_usd_micros = serializers.IntegerField(allow_null=True)


class StatusSerializer(serializers.Serializer[dict[str, Any]]):
    tasks = TaskStatusSerializer(many=True)
    budgets = serializers.DictField(child=LevelSerializer(many=True))
    key_month_limit_usd_micros = serializers.IntegerField()


class UsageRowSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(allow_null=True)
    calls = serializers.IntegerField()
    known_cost_usd_micros = serializers.IntegerField()
    estimated_usd_micros = serializers.IntegerField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    credits = serializers.IntegerField()


class UsageQuerySerializer(serializers.Serializer[dict[str, Any]]):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    group_by = serializers.ChoiceField(
        choices=["task", "model", "organization", "day"], default="task"
    )


class ModelPortStatusView(APIView):
    permission_classes = [IsMfaOperator]

    @extend_schema(
        operation_id="model_port_platform_status",
        summary="Model port status",
        description="Every task with its availability and the reason, its model's capabilities, "
        "and the spend against each ceiling (ADR-068). Operator only.",
        tags=["model-port"],
        responses={200: StatusSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        context = ModelContext(organization_id=None, purpose="probe")
        statuses = [task_status(key) for key in registered_tasks()]
        return Response({
            "tasks": [
                {
                    "task": status.task,
                    "available": status.available,
                    "reason": status.reason,
                    "until": status.until,
                    "model": status.model,
                    "capabilities": sorted(status.capabilities),
                }
                for status in statuses
            ],
            "budgets": {
                key: [asdict(level) for level in budget_state(key, context).levels]
                for key in registered_tasks()
            },
            "key_month_limit_usd_micros": micros(current_budgets().key_month_limit),
        })


class ModelPortUsageView(APIView):
    permission_classes = [IsMfaOperator]

    @extend_schema(
        operation_id="model_port_platform_usage",
        summary="Model port usage",
        description="Calls, tokens, known and estimated cost, and the credits consumers settled, "
        "grouped by task, model, organization or day. Operator only.",
        tags=["model-port"],
        parameters=[
            OpenApiParameter("date_from", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("date_to", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("group_by", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: UsageRowSerializer(many=True),
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = UsageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        today = admission.now().date()
        start = query.validated_data.get("date_from") or today.replace(day=1)
        end = query.validated_data.get("date_to") or today
        rows = UsageEntry.objects.using(admission.alias()).filter(
            created_at__gte=datetime.combine(start, time.min, tzinfo=admission.now().tzinfo),
            created_at__lt=datetime.combine(
                end + timedelta(days=1), time.min, tzinfo=admission.now().tzinfo
            ),
        )
        group = query.validated_data["group_by"]
        if group == "day":
            rows = rows.annotate(key=TruncDay("created_at"))
        else:
            rows = rows.annotate(key=F(GROUPS[group]))
        calls = rows.filter(kind=EntryKind.CALL)
        result = calls.values("key").annotate(
            calls=Count("id"),
            known_cost_usd_micros=Coalesce(Sum("cost_usd_micros"), 0),
            estimated_usd_micros=Coalesce(Sum("estimate_usd_micros"), 0),
            input_tokens=Coalesce(Sum("input_tokens"), 0),
            output_tokens=Coalesce(Sum("output_tokens"), 0),
        )
        credits = dict(
            rows.filter(kind=EntryKind.SETTLEMENT)
            .values("key")
            .annotate(total=Coalesce(Sum("credits"), 0))
            .values_list("key", "total")
        )
        return Response([
            {
                **row,
                "key": None if row["key"] is None else str(row["key"]),
                "credits": int(credits.get(row["key"], 0)),
            }
            for row in result.order_by("key")
        ])
