"""The „Platforma" panel's API (platform settings plan, phase 2; S-T5, S-T7):
the platform's values of the settings registry for its operators — what each
key is now and where from, a preview of a change, the change itself with a
reason, and its history. Only an operator on a session signed in through MFA
gets in; a level-2 key also needs a fresh code from the app (step-up)."""

from __future__ import annotations

from typing import Any, cast

from django.urls import path
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.identity.operators import operator_level, require_operator
from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.core.identity.step_up import require_step_up

from .platform_settings import (
    PlatformValue,
    change_platform_setting,
    companies_following,
    platform_history,
    platform_spec,
    read_platform_setting,
    value_after,
)
from .serializers import LocalizedTextSerializer, SettingOptionSerializer
from .settings_registry import (
    check_value,
    registered_areas,
    registered_groups,
    schema_entry,
)

PROBLEMS = {400: ProblemDetailsSerializer, 403: ProblemDetailsSerializer}


class IsPlatformOperator(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        require_operator(request)
        return True


class PlatformKeySerializer(SettingOptionSerializer):
    value = serializers.JSONField(help_text="The value in force for the platform.")
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=["platform", "deployment", "code"],
        help_text="platform: an operator set it; deployment: the server's .env; code: default.",
    )
    operator_level = serializers.IntegerField(
        help_text="1: any operator changes it; 2: a platform administrator, with a code."
    )
    can_change = serializers.BooleanField(help_text="Whether this operator may change it.")


class PlatformGroupSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    area = serializers.CharField()
    title = LocalizedTextSerializer()
    description = LocalizedTextSerializer()
    keys = PlatformKeySerializer(many=True)


class PlatformAreaSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    title = LocalizedTextSerializer()
    description = LocalizedTextSerializer()


class PlatformSchemaSerializer(serializers.Serializer[dict[str, Any]]):
    operator_level = serializers.IntegerField(help_text="This operator's level: 1 or 2.")
    areas = PlatformAreaSerializer(many=True)
    groups = PlatformGroupSerializer(many=True)


class PlatformChangeSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.JSONField(
        allow_null=True,
        help_text="The new value; null gives the key back to the deployment's or the code's.",
    )
    reason = serializers.CharField(max_length=500, help_text="Why — it stays in the key's history.")


class PlatformPreviewSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    current = serializers.JSONField()
    proposed = serializers.JSONField()
    companies_following = serializers.IntegerField(
        allow_null=True,
        help_text="Companies with no value of their own, which the change reaches at once; "
        "null for a key companies do not set.",
    )


class PlatformValueSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    value = serializers.JSONField()
    source = serializers.CharField()  # type: ignore[assignment]
    operator_level = serializers.IntegerField()


class PlatformHistoryItemSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.JSONField(help_text="null: given back to the deployment's or the code's.")
    operator = serializers.EmailField()
    reason = serializers.CharField()
    created_at = serializers.DateTimeField()


class PlatformHistorySerializer(serializers.Serializer[dict[str, Any]]):
    items = PlatformHistoryItemSerializer(many=True)


def _value_payload(key: str, current: PlatformValue | None = None) -> dict[str, Any]:
    current = current or read_platform_setting(key)
    return {
        "key": key,
        "value": current.value,
        "source": current.source,
        "operator_level": current.operator_level,
    }


class PlatformSettingsView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(
        operation_id="platform_settings_list",
        summary="The platform's settings",
        description="Every key the platform sets (class A), by group and area: the value in "
        "force and where it comes from, its bounds and variants, who may change it and "
        "whether this operator may. Operators only, on a session signed in through MFA.",
        tags=["platform"],
        responses={200: PlatformSchemaSerializer, **PROBLEMS},
    )
    def get(self, request: Request) -> Response:
        level = operator_level(cast(User, request.user))
        groups = []
        for group in registered_groups():
            keys = [spec for spec in group.settings if "platform" in spec.scopes]
            if not keys:
                continue
            groups.append({
                "key": group.key,
                "area": group.area,
                "title": dict(group.title),
                "description": dict(group.description),
                "keys": [
                    {
                        **schema_entry(spec),
                        **{
                            name: value
                            for name, value in _value_payload(spec.key).items()
                            if name != "key"
                        },
                        "can_change": level >= spec.operator_level,
                    }
                    for spec in keys
                ],
            })
        held = {group["area"] for group in groups}
        return Response({
            "operator_level": level,
            "areas": [
                {
                    "key": area.key,
                    "title": dict(area.title),
                    "description": dict(area.description),
                }
                for area in registered_areas()
                if area.key in held
            ],
            "groups": groups,
        })


class PlatformSettingView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(
        operation_id="platform_setting_update",
        summary="Change a platform setting",
        description="A new value, or null to give the key back to the deployment's or the "
        "code's, with a reason; one append-only entry. A level-2 key needs a level-2 "
        "operator and a fresh code from the authenticator app (403 step_up_required; POST "
        "/api/v1/auth/step-up/, then repeat).",
        tags=["platform"],
        request=PlatformChangeSerializer,
        responses={200: PlatformValueSerializer, **PROBLEMS},
        examples=[OpenApiExample("Set", value={"value": 48, "reason": "Pilot"})],
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The same value with the same reason from the same "
                "operator writes nothing new and answers the value in force.",
            }
        },
    )
    def post(self, request: Request, key: str) -> Response:
        user = cast(User, request.user)
        spec = platform_spec(key)
        data = PlatformChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        # A code is asked only of someone the key's level lets in at all.
        if spec.operator_level >= 2 and operator_level(user) >= spec.operator_level:
            require_step_up(user_id=user.pk, reason="platform")
        entry = change_platform_setting(
            key, data.validated_data["value"], operator=user, reason=data.validated_data["reason"]
        )
        return Response(_value_payload(key, value_after(entry)))


class PlatformSettingPreviewView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(
        operation_id="platform_setting_preview",
        summary="What a platform setting's change would do",
        description="Checks the value as the change would and says how many companies "
        "follow the platform's value (none of their own), so the change reaches them at "
        "once. Writes nothing.",
        tags=["platform"],
        request=PlatformChangeSerializer,
        responses={200: PlatformPreviewSerializer, **PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, key: str) -> Response:
        spec = platform_spec(key)
        data = PlatformChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        proposed = data.validated_data["value"]
        if proposed is not None:
            checked = check_value(spec, proposed)
            if checked is None or checked[1]:
                message, code = (checked[1], checked[2]) if checked else ("Zła wartość.", "invalid")
                raise serializers.ValidationError({"value": [message]}, code=code)
            proposed = checked[0]
        return Response({
            "key": key,
            "current": read_platform_setting(key).value,
            "proposed": proposed,
            "companies_following": companies_following(key),
        })


class PlatformSettingHistoryView(APIView):
    permission_classes = [IsPlatformOperator]

    @extend_schema(
        operation_id="platform_setting_history",
        summary="A platform setting's history",
        description="Every change of the key, newest first: the value, who and why.",
        tags=["platform"],
        responses={200: PlatformHistorySerializer, **PROBLEMS},
    )
    def get(self, request: Request, key: str) -> Response:
        return Response({
            "items": [
                {
                    "value": entry.value,
                    "operator": entry.operator.email,
                    "reason": entry.reason,
                    "created_at": entry.created_at,
                }
                for entry in platform_history(key)
            ]
        })


urlpatterns = [
    path("settings/", PlatformSettingsView.as_view(), name="platform-settings"),
    path("settings/<str:key>/", PlatformSettingView.as_view(), name="platform-setting"),
    path(
        "settings/<str:key>/preview/",
        PlatformSettingPreviewView.as_view(),
        name="platform-setting-preview",
    ),
    path(
        "settings/<str:key>/history/",
        PlatformSettingHistoryView.as_view(),
        name="platform-setting-history",
    ),
]
