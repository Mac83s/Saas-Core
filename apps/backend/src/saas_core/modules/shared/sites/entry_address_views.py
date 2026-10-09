"""The panel's API of an entry's address (ADR-079 pkt 16, „Uzupełnienie CT4”)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .entry_addresses import (
    ENTRY_SLUG_MAX,
    EntryAddressChange,
    change_entry_slug,
    read_entry_address,
)

_SLUG_HELP = "Lower-case Latin letters, digits and single hyphens."

_RULES = (
    "Before the entry was ever published its address changes freely and leaves no trace. "
    "Afterwards it is a person's decision (`person_required`): the slug it had answers one 308 "
    "to the new address, and an entry visitors can open today is published again under the "
    "new address with the content of its current publication — changes waiting in the draft "
    "stay unpublished (`unpublished_changes`). A slug another entry of the type and language "
    "answers under is refused (`entry_slug_taken`); one that only redirects to another entry "
    "can be taken — the preview's `takes_over` names the redirect that stops — with "
    "`take_over_former` (`entry_slug_former` without it)."
)

_ERRORS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}


class EntryAddressSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.RegexField(
        r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=ENTRY_SLUG_MAX,
        help_text="The new last part of the entry's address. " + _SLUG_HELP,
    )
    reason = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Why the address moves. Required when the entry answers visitors today "
        "(`moved` of the preview is not empty); kept in the history.",
    )
    take_over_former = serializers.BooleanField(
        default=False,
        help_text="Confirms that a redirect of another entry may stop (`takes_over` of the "
        "preview): the slug only redirects to that entry today.",
    )


class _MovedSerializer(serializers.Serializer[dict[str, Any]]):
    from_path = serializers.CharField(help_text="The address that stops answering.")
    to_path = serializers.CharField(help_text="Where it leads from then on, in one 308.")


class _TakenOverSerializer(serializers.Serializer[dict[str, Any]]):
    slug = serializers.CharField(help_text="The slug taken.")
    entry_id = serializers.UUIDField(help_text="The entry whose redirect stops.")
    title = serializers.CharField(help_text="That entry's title.")


class EntryAddressResultSerializer(serializers.Serializer[dict[str, Any]]):
    entry_id = serializers.UUIDField()
    locale = serializers.CharField(help_text="The entry's language.")
    previous_slug = serializers.CharField(help_text="The slug before the change.")
    slug = serializers.CharField(help_text="The slug as it is, or in a preview would be.")
    path = serializers.CharField(help_text="Where the entry answers (would answer).")
    changed = serializers.BooleanField(help_text="Whether the slug differs from today's.")
    published = serializers.BooleanField(
        help_text="The entry answers visitors today: the change publishes it again."
    )
    moved = _MovedSerializer(
        many=True,
        help_text="Addresses visitors can open today that move. Not empty: a reason is required.",
    )
    redirects = _MovedSerializer(
        many=True, help_text="Every former address that leads to the entry afterwards."
    )
    takes_over = _TakenOverSerializer(
        many=True, help_text="Redirects of other entries that stop with this change."
    )
    unpublished_changes = serializers.BooleanField(
        help_text="The draft holds changes the current publication does not; an address "
        "change leaves them unpublished."
    )


def _payload(change: EntryAddressChange) -> dict[str, Any]:
    return {
        "entry_id": str(change.entry.id),
        "locale": change.entry.locale,
        "previous_slug": change.previous_slug,
        "slug": change.slug,
        "path": change.path,
        "changed": change.changed,
        "published": change.published,
        "moved": list(change.moved),
        "redirects": list(change.redirects),
        "takes_over": list(change.takes_over),
        "unpublished_changes": change.unpublished_changes,
    }


class ContentEntryAddressView(APIView):
    """Session-only: moving an address costs what it earned, which is not an
    optimiser's trade to make (ADR-035; the contract has no such command)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_entry_address_get",
        summary="Read an entry's address and the addresses that redirect to it",
        description="The entry's slug and address today, whether it answers visitors, and "
        "every former address that leads to it with one 308.",
        tags=["sites"],
        responses={
            200: EntryAddressResultSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, entry_id: UUID) -> Response:
        return Response(_payload(read_entry_address(entry_id=entry_id)))

    @extend_schema(
        operation_id="sites_entry_address_set",
        summary="Change an entry's address",
        description=_RULES + " When the entry answers visitors today a `reason` is required "
        "(`redirect_reason_required`).",
        tags=["sites"],
        request=EntryAddressSerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The slug is sent as it should be: a repeat sets the same "
                "slug and changes nothing.",
            }
        },
        responses={200: EntryAddressResultSerializer, **_ERRORS},
    )
    def put(self, request: Request, entry_id: UUID) -> Response:
        serializer = EntryAddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_payload(change_entry_slug(entry_id=entry_id, **serializer.validated_data)))


class ContentEntryAddressPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_entry_address_preview",
        summary="Preview changing an entry's address",
        description="Validates and answers with the address as it would be, what would "
        "redirect (`moved`, `redirects`), the redirects of other entries that would stop "
        "(`takes_over`) and whether the draft holds unpublished changes, without saving. " + _RULES,
        tags=["sites"],
        request=EntryAddressSerializer,
        extensions={"x-dry-run": True},
        responses={200: EntryAddressResultSerializer, **_ERRORS},
    )
    def post(self, request: Request, entry_id: UUID) -> Response:
        serializer = EntryAddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _payload(
                change_entry_slug(entry_id=entry_id, **serializer.validated_data, dry_run=True)
            )
        )
