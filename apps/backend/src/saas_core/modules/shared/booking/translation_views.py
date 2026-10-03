"""The panel's and the assistant's API of booking items in other languages
(TL12b): a list of each language with each field's state, and a setup write
with its preview (ADR-072 §11)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.content_protocol.units import unit_state
from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .item_translations import (
    Translatable,
    item_units,
    list_item_translations,
    row_targets,
    save_item_translation,
    translatable,
)
from .models import ItemTranslation

KINDS = [
    "service",
    "location",
    "resource",
    "group",
    "team",
    "participant_category",
    "extra",
]
KIND = OpenApiParameter(
    "kind",
    str,
    OpenApiParameter.PATH,
    enum=KINDS,
    description="service, location, resource (a unit), group (of units), team, "
    "participant_category or extra.",
)
IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
_PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}


class ItemTranslationInputSerializer(serializers.Serializer[dict[str, Any]]):
    expected_version = serializers.IntegerField(
        min_value=0,
        help_text="The language's version this change was made on; 0 for a language the item "
        "does not have yet. Another version is 409 `booking_version_conflict`.",
    )
    texts = serializers.DictField(
        child=serializers.CharField(allow_blank=True, max_length=2000),
        help_text="By field: `name`, and `description` for a unit or a group. An empty text "
        "removes the translation; an absent field stays as it is.",
    )


class ItemTranslationUnitSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField(help_text="The field: name or description.")
    source_text = serializers.CharField(help_text="The item's own text.")
    text = serializers.CharField(allow_blank=True, help_text="The translation; empty: none.")
    status = serializers.ChoiceField(
        choices=["fresh", "stale", "missing", "blocked", "copied", "unverified"],
        help_text="Against the item's current text (translation-sources.md §4).",
    )
    origin = serializers.CharField(
        allow_blank=True, help_text="Who wrote it: human, ai, integration…; empty: nobody."
    )


class ItemTranslationSerializer(serializers.Serializer[dict[str, Any]]):
    locale = serializers.CharField()
    version = serializers.IntegerField(help_text="0 for a language the item does not have yet.")
    units = ItemTranslationUnitSerializer(many=True)


class ItemTranslationListSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.CharField()
    item_id = serializers.UUIDField()
    source_locale = serializers.CharField(help_text="The language the item is written in.")
    languages = ItemTranslationSerializer(
        many=True, help_text="Every other language of the company, translated or not."
    )


def _language(
    entry: Translatable, item: Any, locale: str, row: ItemTranslation | None
) -> dict[str, Any]:
    units = item_units(entry, item)
    targets = row_targets(row, units)
    rows = []
    for unit in units:
        target = targets.get(unit.key)
        rows.append({
            "key": unit.key,
            "source_text": unit.text,
            "text": target.text if target else "",
            "status": unit_state(unit, target).status,
            "origin": target.provenance.origin if target and target.provenance else "",
        })
    return {"locale": locale, "version": row.version if row else 0, "units": rows}


class ItemTranslationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_item_translations_list",
        summary="A booking item's translations, language by language",
        description="A service's, a place's, a unit's, a group's or a team's name (and "
        "description) in every other language of the company: the item's own text, the "
        "translation, its state against the current text and who wrote it, with the version "
        "to send with a change.",
        tags=["booking"],
        parameters=[KIND],
        responses={
            200: ItemTranslationListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, kind: str, item_id: UUID) -> Response:
        entry, item, own, rows = list_item_translations(kind, item_id)
        return Response({
            "kind": entry.kind,
            "item_id": item.id,
            "source_locale": own,
            "languages": [_language(entry, item, code, row) for code, row in rows],
        })


def _input(request: Request) -> tuple[dict[str, str], int]:
    s = ItemTranslationInputSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    return dict(s.validated_data["texts"]), s.validated_data["expected_version"]


def _idem(request: Request) -> str:
    from .views import _idem as idempotency_key

    return idempotency_key(request)


@method_decorator(csrf_protect, name="dispatch")
class ItemTranslationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_item_translation_update",
        summary="Write a booking item in another language",
        description="A person's name (and description) of a service, place, unit, group or "
        "team in a language of the company, at the version they saw. Only the fields sent "
        "change; the history keeps it. A repeated Idempotency-Key answers the first result "
        "again; the key reused on another request is 409 `booking_idempotency_conflict`.",
        tags=["booking"],
        parameters=[KIND, IDEMPOTENCY],
        request=ItemTranslationInputSerializer,
        responses={200: ItemTranslationSerializer, **_PROBLEMS},
    )
    def put(self, request: Request, kind: str, item_id: UUID, locale: str) -> Response:
        texts, version = _input(request)
        saved = save_item_translation(
            kind=kind,
            item_id=item_id,
            locale=locale,
            texts=texts,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        entry = translatable(kind)
        item = getattr(saved.value, entry.relation)
        return Response(_language(entry, item, locale, saved.value))


@method_decorator(csrf_protect, name="dispatch")
class ItemTranslationPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="booking_item_translation_preview",
        summary="Check a booking item's translation without saving it",
        description="Validates a change as `booking_item_translation_update` would. Nothing is "
        "saved: the answer is the language as the write would leave it, or the same 400, 404 "
        "and 409 the write would answer.",
        tags=["booking"],
        parameters=[KIND],
        request=ItemTranslationInputSerializer,
        responses={200: ItemTranslationSerializer, **_PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, kind: str, item_id: UUID, locale: str) -> Response:
        texts, version = _input(request)
        saved = save_item_translation(
            kind=kind,
            item_id=item_id,
            locale=locale,
            texts=texts,
            expected_version=version,
            preview=True,
        )
        entry = translatable(kind)
        item = getattr(saved.value, entry.relation)
        return Response(_language(entry, item, locale, saved.value))
