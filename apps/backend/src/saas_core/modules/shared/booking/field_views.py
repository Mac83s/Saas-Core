"""The panel's and the assistant's API of an offer's own form fields (ADR-072
§8, slice 5j): what a booking form asks beyond the name and the contact.
Every write is a setup write with its preview (§11)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .form_fields import FIELD_LIMITS, list_fields, save_field
from .models import FieldKind, FormField
from .serializers import _changes, _expected_version
from .views import (
    _PREVIEW,
    _PREVIEW_NOTE,
    _SETUP_PROBLEMS,
    _UPDATE_NOTE,
    _WRITE_NOTE,
    IDEMPOTENCY,
    _idem,
    _update,
    _with_changes,
)

_KIND_HELP = (
    "`text` — a line the customer types; `number`; `date` (a day); `choice` — one of "
    "`options`; `consent` — a box to tick, whose wording (`name`) goes to the consent "
    "journal word for word when ticked."
)
_OPTIONS_HELP = (
    "A choice's options in order, at least two; a booking's answer names one of them "
    "word for word. Ignored for every other kind."
)
_SENSITIVE_NOTE = (
    " What a customer answers is their personal data, kept on the booking and removed "
    "with the customer; do not ask here for health or other special-category data."
)


def _options(**kwargs: Any) -> serializers.ListField:
    return serializers.ListField(
        child=serializers.CharField(max_length=FIELD_LIMITS["max_option_length"]),
        max_length=FIELD_LIMITS["max_options"],
        help_text=_OPTIONS_HELP,
        **kwargs,
    )


class FormFieldInputSerializer(serializers.Serializer[dict[str, Any]]):
    """One thing an offer's booking form asks."""

    service_id = serializers.UUIDField(help_text="The offer whose form asks it.")
    name = serializers.CharField(
        max_length=FIELD_LIMITS["max_name_length"],
        help_text="The question as the customer reads it, in the company's first language; "
        "for a `consent`, the statement they tick.",
    )
    kind = serializers.ChoiceField(choices=FieldKind.choices, required=False, help_text=_KIND_HELP)
    options = _options(required=False)
    mandatory = serializers.BooleanField(
        required=False,
        help_text="A customer booking for themselves must answer it (tick it, for a "
        "consent), and so must a staff member booking for a customer in the panel — "
        "except a consent, which only the customer gives.",
    )
    position = serializers.IntegerField(
        min_value=0,
        max_value=1000,
        required=False,
        help_text="The order on the form, smallest first; omitted — a new field goes last.",
    )
    active = serializers.BooleanField(required=False)


class FormFieldUpdateSerializer(FormFieldInputSerializer):
    service_id = None  # type: ignore[assignment]
    name = serializers.CharField(max_length=FIELD_LIMITS["max_name_length"], required=False)
    expected_version = _expected_version()


class FormFieldSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    service_id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=FieldKind.choices, help_text=_KIND_HELP)
    options = serializers.ListField(child=serializers.CharField(), help_text=_OPTIONS_HELP)
    mandatory = serializers.BooleanField()
    position = serializers.IntegerField()
    active = serializers.BooleanField()
    version = serializers.IntegerField()


class FormFieldPreviewSerializer(FormFieldSerializer):
    changes = _changes()


class FormFieldKindSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.ChoiceField(choices=FieldKind.choices)
    label = serializers.DictField(  # type: ignore[assignment]
        child=serializers.CharField(), help_text="By language: pl, en."
    )


class FormFieldLimitsSerializer(serializers.Serializer[dict[str, Any]]):
    """What an offer's fields may be (ADR-078: read, never hard-coded)."""

    max_fields = serializers.IntegerField(help_text="Switched-on fields of one offer.")
    min_options = serializers.IntegerField()
    max_options = serializers.IntegerField()
    max_option_length = serializers.IntegerField()
    max_name_length = serializers.IntegerField()
    max_answer_length = serializers.IntegerField(
        help_text="The longest text a customer types into one field."
    )
    kinds = FormFieldKindSerializer(many=True)


class FormFieldListSerializer(serializers.Serializer[dict[str, Any]]):
    items = FormFieldSerializer(many=True)
    limits = FormFieldLimitsSerializer()


def _field_payload(value: FormField) -> dict[str, Any]:
    return {
        "id": value.id,
        "service_id": value.service_id,
        "name": value.name,
        "kind": value.kind,
        "options": value.option_list,
        "mandatory": value.mandatory,
        "position": value.position,
        "active": value.active,
        "version": value.version,
    }


class FormFieldListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_form_fields_list",
        summary="List the offers' own form fields",
        description="What each offer's booking form asks beyond the customer's name and "
        "contact, in the form's order, switched-off ones included; and what a field may "
        "be (`limits`).",
        tags=["booking"],
        responses={200: FormFieldListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, request: Request) -> Response:
        del request
        return Response({
            "items": [_field_payload(item) for item in list_fields()],
            "limits": FIELD_LIMITS,
        })

    @extend_schema(
        operation_id="booking_form_field_create",
        summary="Add a field to an offer's booking form",
        description="A question the offer's booking form asks every customer — a driving "
        "licence number, a pet's name, an arrival hour — or a consent to tick. Refused "
        "with a code on its field: `name_taken`, `options_required`, `options_too_many`, "
        "`option_too_long`, `options_repeated`, `fields_too_many`." + _SENSITIVE_NOTE + _WRITE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=FormFieldInputSerializer,
        responses={201: FormFieldSerializer, **_SETUP_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        s = FormFieldInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_field(
            field_id=None, data=dict(s.validated_data), idempotency_key=_idem(request)
        )
        return Response(_field_payload(saved.value), status=201)


@method_decorator(csrf_protect, name="dispatch")
class FormFieldCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_form_field_create_preview",
        summary="Check a form field without adding it",
        description="Validates a field as `booking_form_field_create` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=FormFieldInputSerializer,
        responses={200: FormFieldPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        s = FormFieldInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        saved = save_field(field_id=None, data=dict(s.validated_data), preview=True)
        return Response(_with_changes(_field_payload(saved.value), saved.changes))


@method_decorator(csrf_protect, name="dispatch")
class FormFieldDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_form_field_update",
        summary="Change a form field",
        description="Changes a field's question, kind, options, order or whether it is "
        "mandatory, or switches it off. A field is never deleted: bookings keep the "
        "question they were asked and their answer, whatever the field becomes."
        + _SENSITIVE_NOTE
        + _UPDATE_NOTE,
        tags=["booking"],
        parameters=[IDEMPOTENCY],
        request=FormFieldUpdateSerializer,
        responses={200: FormFieldSerializer, **_SETUP_PROBLEMS},
    )
    def patch(self, request: Request, field_id: UUID) -> Response:
        s = FormFieldUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_field(
            field_id=field_id, data=data, expected_version=version, idempotency_key=_idem(request)
        )
        return Response(_field_payload(saved.value))


@method_decorator(csrf_protect, name="dispatch")
class FormFieldUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_form_field_update_preview",
        summary="Check a change to a form field without saving it",
        description="Validates a change as `booking_form_field_update` would." + _PREVIEW_NOTE,
        tags=["booking"],
        request=FormFieldUpdateSerializer,
        responses={200: FormFieldPreviewSerializer, **_SETUP_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, field_id: UUID) -> Response:
        s = FormFieldUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data, version = _update(s.validated_data)
        saved = save_field(field_id=field_id, data=data, expected_version=version, preview=True)
        return Response(_with_changes(_field_payload(saved.value), saved.changes))
