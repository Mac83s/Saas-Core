"""The settings API (ADR-078 pkt 11): the schema, and per group a read, a
preview and a change.

Each group gets its own operations and serializers, built from its
declaration, so the contract is typed per group and a new key changes that
group's fingerprint (`pnpm api:check`). A field is the key's last segment.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.urls import URLPattern, path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .authorization import authorize
from .permissions import ORGANIZATION_READ
from .serializers import LocalizedTextSerializer, SettingOptionSerializer
from .settings_registry import (
    SOURCES,
    SettingGroup,
    SettingSpec,
    registered_areas,
    registered_groups,
    schema_entry,
    typed_text,
    words_type,
)
from .settings_service import GroupState, SettingsChange, change_settings, read_group, schema

PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}
IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia: powtórka zwraca pierwszą zmianę.",
)


class SettingsGroupSchemaSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="The group, e.g. booking.reminders.")
    module = serializers.CharField()
    area = serializers.CharField(help_text="The panel's area the group belongs to.")
    title = LocalizedTextSerializer()
    description = LocalizedTextSerializer()
    permission = serializers.CharField(help_text="Who may change the company's values.")
    can_change = serializers.BooleanField(help_text="Whether the caller may change them now.")
    locked = serializers.CharField(
        allow_blank=True, help_text="Why the plan does not let the company change them; empty."
    )
    keys = SettingOptionSerializer(many=True)
    step_up = serializers.BooleanField(
        help_text="A change asks for a fresh code from the authenticator app first "
        "(403 step_up_required; POST /api/v1/auth/step-up/, then repeat)."
    )
    api = serializers.CharField(
        allow_null=True,
        help_text="The module's own endpoint for a group it stores itself; null: "
        "…/current/settings/<group>/.",
    )


class SettingAreaSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="The area, e.g. security; a group's `area` names it.")
    title = LocalizedTextSerializer()
    description = LocalizedTextSerializer()
    page = serializers.CharField(
        allow_null=True,
        help_text="The module's own panel page; null: the generic /panel/settings/<key>.",
    )


class SettingsSchemaSerializer(serializers.Serializer[dict[str, Any]]):
    areas = SettingAreaSerializer(
        many=True, help_text="The places of „Ustawienia” that hold a group, in menu order."
    )
    groups = SettingsGroupSchemaSerializer(many=True)


class SettingEffectSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.CharField()
    resource = serializers.CharField()
    resource_id = serializers.CharField(allow_blank=True)
    summary = LocalizedTextSerializer()


@method_decorator(csrf_protect, name="dispatch")
class SettingsSchemaView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="organization_settings_schema_retrieve",
        summary="What the company may set",
        description="Every settings group the company has, with its keys, types, bounds, "
        "allowed values and labels (pl, en), the default, who may change it and whether "
        "the plan lets the company change it now (ADR-078). The one source of a setting's "
        "variants for the panel and the assistant.",
        tags=["organizations"],
        responses={200: SettingsSchemaSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        context = authorize(ORGANIZATION_READ)
        groups = schema(context)
        held = {group.area for group, _can_change, _locked in groups}
        # A product's words for this kind of organization (UX-082).
        kind = words_type(context.organization_id)

        def words(address: str, texts: Any) -> dict[str, str]:
            return dict(typed_text(address, texts, kind) or texts)

        return Response({
            "areas": [
                {
                    "key": area.key,
                    "title": words(f"area:{area.key}.title", area.title),
                    "description": words(f"area:{area.key}.description", area.description),
                    "page": area.page,
                }
                for area in registered_areas()
                if area.key in held
            ],
            "groups": [
                {
                    "key": group.key,
                    "module": group.module,
                    "area": group.area,
                    "title": words(f"group:{group.key}.title", group.title),
                    "description": words(f"group:{group.key}.description", group.description),
                    "permission": group.permission,
                    "can_change": can_change,
                    "locked": locked,
                    "keys": [schema_entry(spec, kind) for spec in group.settings],
                    "api": group.api,
                    "step_up": bool(group.step_up_reason),
                }
                for group, can_change, locked in groups
            ],
        })


def settings_urlpatterns() -> list[URLPattern]:
    patterns = [path("current/settings/schema/", SettingsSchemaView.as_view())]
    for group in registered_groups():
        if group.api is not None:
            continue  # An entity group's module serves its own API.
        read, preview = _group_views(group)
        patterns += [
            path(f"current/settings/{group.key}/", read.as_view()),
            path(f"current/settings/{group.key}/preview/", preview.as_view()),
        ]
    return patterns


def _group_views(group: SettingGroup) -> tuple[type[APIView], type[APIView]]:
    name = "".join(part.title() for part in group.key.replace("_", ".").split("."))
    slug = group.key.replace(".", "_")
    values = _serializer(
        f"{name}SettingsValues",
        {spec.field: _field(spec, allow_null=spec.default is None) for spec in group.settings},
    )
    sources = _serializer(
        f"{name}SettingsSources",
        {spec.field: serializers.ChoiceField(choices=SOURCES) for spec in group.settings},
    )
    state = _serializer(
        f"{name}Settings",
        {
            "group": serializers.CharField(),
            "version": serializers.CharField(help_text="The group's version token."),
            "values": values(help_text="The values that apply, by field."),
            "sources": sources(help_text="Where each value comes from."),
            "can_change": serializers.BooleanField(),
            "locked": serializers.CharField(allow_blank=True),
        },
    )
    change = _serializer(
        f"{name}SettingsChange",
        {
            "expected_version": serializers.CharField(
                help_text="The version token read with the values; a stale one is a 409."
            ),
            "reset": serializers.ListField(
                child=serializers.ChoiceField(choices=list(group.fields)),
                required=False,
                default=list,
                help_text="Fields given back to the default (the platform's or the code's).",
            ),
            **{
                spec.field: _field(spec, required=False, allow_null=True) for spec in group.settings
            },
        },
    )
    preview = _serializer(
        f"{name}SettingsPreview",
        {
            "version": serializers.CharField(help_text="The version token the preview read."),
            "values": values(help_text="The values after the change, by field."),
            "changes": serializers.DictField(
                child=serializers.DictField(),
                help_text="Each field that would change: {from, to}.",
            ),
            "effects": SettingEffectSerializer(many=True),
        },
    )
    title = group.title["en"]

    def run(request: Request, *, preview_only: bool) -> SettingsChange:
        data = change(data=request.data)
        data.is_valid(raise_exception=True)
        given = {
            field: value.isoformat() if isinstance(value, date) else value
            for field, value in data.validated_data.items()
            if field in group.fields
        }
        return change_settings(
            group.key,
            changes=given,
            reset=data.validated_data.get("reset") or [],
            expected_version=data.validated_data["expected_version"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            preview=preview_only,
        )

    @method_decorator(csrf_protect, name="dispatch")
    class GroupView(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(
            operation_id=f"organization_settings_{slug}_retrieve",
            summary=f"Read the company's settings: {title}",
            description=f"{group.description['en']} The values that apply, where each comes "
            "from (code, platform or the company) and the group's version token.",
            tags=["organizations"],
            responses={200: state, 403: ProblemDetailsSerializer, 404: ProblemDetailsSerializer},
        )
        def get(self, _request: Request) -> Response:
            return Response(_state(read_group(group.key)))

        @extend_schema(
            operation_id=f"organization_settings_{slug}_update",
            summary=f"Change the company's settings: {title}",
            description="Changes the given fields, guarded by `expected_version` (a stale "
            "one answers 409 settings_version_conflict). A field left out or null stays as it "
            "is; `reset` gives fields back to the default. A repeat with the same "
            "Idempotency-Key answers the first change.",
            tags=["organizations"],
            parameters=[IDEMPOTENCY_PARAMETER],
            request=change,
            responses={200: state, **PROBLEMS},
        )
        def patch(self, request: Request) -> Response:
            run(request, preview_only=False)
            return Response(_state(read_group(group.key)))

    @method_decorator(csrf_protect, name="dispatch")
    class PreviewView(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(
            operation_id=f"organization_settings_{slug}_preview",
            summary=f"See what a change of the company's settings would do: {title}",
            description="The same checks as the change, and nothing saved: the values "
            "after, what changes and what that does (e.g. reminders it re-plans).",
            tags=["organizations"],
            request=change,
            responses={200: preview, **PROBLEMS},
            extensions={"x-dry-run": True},
        )
        def post(self, request: Request) -> Response:
            result = run(request, preview_only=True)
            return Response({
                "version": result.version,
                "values": dict(result.after),
                "changes": dict(result.changes),
                "effects": [
                    {
                        "kind": effect.kind,
                        "resource": effect.resource,
                        "resource_id": effect.resource_id,
                        "summary": dict(effect.summary),
                    }
                    for effect in result.effects
                ],
            })

    GroupView.__name__ = f"{name}SettingsView"
    PreviewView.__name__ = f"{name}SettingsPreviewView"
    return GroupView, PreviewView


def _state(state: GroupState) -> dict[str, Any]:
    return {
        "group": state.group.key,
        "version": state.version,
        "values": {field: resolved.value for field, resolved in state.values.items()},
        "sources": {field: resolved.source for field, resolved in state.values.items()},
        "can_change": state.can_change,
        "locked": state.locked,
    }


def _serializer(name: str, fields: dict[str, Any]) -> type[serializers.Serializer[Any]]:
    return type(f"{name}Serializer", (serializers.Serializer,), dict(fields))


def _field(spec: SettingSpec, **options: Any) -> serializers.Field[Any, Any, Any, Any]:
    options.setdefault("help_text", spec.model_description)
    if spec.type == "bool":
        return serializers.BooleanField(**options)
    if spec.type == "int":
        if spec.minimum is not None:
            options["min_value"] = spec.minimum
        if spec.maximum is not None:
            options["max_value"] = spec.maximum
        return serializers.IntegerField(**options)
    if spec.type == "date":
        return serializers.DateField(**options)
    if spec.type == "enum":
        return serializers.ChoiceField(choices=[value for value, _ in spec.values], **options)
    if spec.max_length is not None:
        options["max_length"] = spec.max_length
    return serializers.CharField(allow_blank=True, **options)
