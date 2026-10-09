"""Categories and tags over HTTP (ADR-079 pkt 24–26). The views validate
shape; `taxonomies` decides everything else."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.shared.notifications.api_key_middleware import IsSessionOrApiKey

from .models import ContentTag
from .serializers import ContentEntryCategorySerializer
from .taxonomies import (
    TaxonomySegments,
    TermChange,
    TermList,
    TermRemoval,
    TermRow,
    change_term_address,
    create_term,
    delete_term,
    entry_terms,
    list_terms,
    set_entry_categories,
    set_taxonomy_segments,
    set_term_names,
    update_term,
)
from .taxonomy_serializers import (
    TERM_KIND_CHOICES,
    EntryCategoriesSaveSerializer,
    TaxonomySegmentsSaveSerializer,
    TaxonomySegmentsSerializer,
    TermAddressSerializer,
    TermChangeSerializer,
    TermCreateSerializer,
    TermListQuerySerializer,
    TermListSerializer,
    TermNamesSerializer,
    TermRemovalSerializer,
    TermSerializer,
    TermUpdateSerializer,
)

_ERRORS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}
_READ_ERRORS = {403: ProblemDetailsSerializer, 404: ProblemDetailsSerializer}

_SET_VALUES = {
    "x-quality-exempt": {
        "idempotency-key": "The values are sent as they should be: a repeat sets the same "
        "values and changes nothing.",
    }
}

_SHOWS_AT_ONCE = (
    " What a term is called and where a category hangs shows to visitors at once, with no "
    "publication; which entries an archive lists changes only when an entry is published."
    " Because of that, making, renaming, moving and naming terms is a person's decision: an "
    "integration and the assistant are refused (`person_required`)."
)


def _term_payload(row: TermRow) -> dict[str, Any]:
    term = row.term
    return {
        "id": str(term.id),
        "key": term.slug,
        "name": term.name,
        "parent_id": str(term.parent_id) if term.parent_id else None,
        "position": term.position,
        "depth": row.depth,
        "names": {
            locale: {"text": name.text, "origin": name.origin, "state": name.state}
            for locale, name in row.names.items()
        },
        "slugs": row.slugs,
        "paths": row.paths,
        "locked": list(row.locked),
        "entries": row.entries,
        "entries_elsewhere": row.entries_elsewhere,
        "published": row.published,
        "removable": row.removable,
    }


def _list_payload(found: TermList) -> dict[str, Any]:
    return {
        "kind": found.kind,
        "collection_id": str(found.collection.id),
        "taxonomy_id": str(found.taxonomy.id) if found.taxonomy is not None else None,
        "default_locale": found.site.default_locale,
        "locales": list(found.locales),
        "segments": found.segments,
        "max_depth": found.max_depth,
        "max_per_entry": found.max_per_entry,
        "terms": [_term_payload(row) for row in found.terms],
    }


def _change_payload(change: TermChange) -> dict[str, Any]:
    return {
        "term": _term_payload(change.row),
        "changed": change.changed,
        "moved": list(change.moved),
        "takes_over": list(change.takes_over),
        "published": change.published,
    }


def _removal_payload(removal: TermRemoval) -> dict[str, Any]:
    return {
        "removable": removal.removable,
        "removed": removal.removed,
        "drafts": removal.drafts,
        "published": removal.published,
        "children": removal.children,
    }


def _segments_payload(result: TaxonomySegments) -> dict[str, Any]:
    return {
        "segments": result.segments,
        "moved": list(result.moved),
        "changed": result.changed,
    }


def _category_payload(term: ContentTag) -> dict[str, Any]:
    return {
        "id": str(term.id),
        "key": term.slug,
        "name": term.name,
        "parent_id": str(term.parent_id) if term.parent_id else None,
    }


class ContentTypeTermsView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_terms_list",
        summary="A content type's categories, or the site's tags as that type shows them",
        description="`kind=categories`: the type's own categories as a tree. `kind=tags`: "
        "the site's tags, shared by every content type, with the addresses their archives "
        "have under this type. Each term comes with its name per language, its address per "
        "language and whether that is closed, how many entries are filed under it, how many "
        "its archive lists to visitors per language (read from publications), and whether "
        "it can be removed. `max_depth` and `max_per_entry` are the limits to keep.",
        tags=["sites"],
        parameters=[
            OpenApiParameter(
                name="kind",
                type=str,
                location=OpenApiParameter.QUERY,
                enum=[choice for choice, _label in TERM_KIND_CHOICES],
                description="Which vocabulary; `categories` when left out.",
            )
        ],
        responses={200: TermListSerializer, 400: ProblemDetailsSerializer, **_READ_ERRORS},
    )
    def get(self, request: Request, collection_id: UUID) -> Response:
        query = TermListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            _list_payload(
                list_terms(collection_id=collection_id, kind=query.validated_data["kind"])
            )
        )

    @extend_schema(
        operation_id="sites_term_create",
        summary="Make a category of a content type, or a tag of the site",
        description="A category goes under `parent_id` when given, up to `max_depth` levels "
        "(`term_too_deep`); the type's first category starts its categories — there is "
        "nothing to switch on. The address is made from the name and follows it until the "
        "first entry carrying the term is published. A name a category beside it already "
        "has is refused (`term_name_taken`). A tag's name that means an existing tag — its "
        "key or its address in any language — answers with that tag (200). A person's "
        "decision: an integration and the assistant are refused (`person_required`); an "
        "integration makes a tag only by filing an entry under a new name.",
        tags=["sites"],
        request=TermCreateSerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "A repeat with the same name and parent answers with the "
                "term the first request made (200 instead of 201) and makes nothing twice.",
            }
        },
        responses={200: TermSerializer, 201: TermSerializer, **_ERRORS},
    )
    def post(self, request: Request, collection_id: UUID) -> Response:
        serializer = TermCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row, created = create_term(collection_id=collection_id, **serializer.validated_data)
        return Response(
            _term_payload(row),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


_UPDATE_RULES = (
    "Renames a category or a tag (`name`), moves a category under another (`parent_id`; null: "
    "to the top; at most `max_depth` levels with what is under it) and puts it at `position` "
    "among those beside it. A field left out keeps its value. No address moves: a category's "
    "archive has the same address wherever it hangs, and a new name changes the address only "
    "while no entry carrying the term has been published." + _SHOWS_AT_ONCE
)


class ContentTypeTermView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_term_update",
        summary="Rename, move or reorder a category or a tag",
        description=_UPDATE_RULES,
        tags=["sites"],
        request=TermUpdateSerializer,
        extensions=_SET_VALUES,
        responses={200: TermChangeSerializer, **_ERRORS},
    )
    def patch(self, request: Request, collection_id: UUID, term_id: UUID) -> Response:
        serializer = TermUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _change_payload(
                update_term(
                    term_id=term_id, collection_id=collection_id, **serializer.validated_data
                )
            )
        )

    @extend_schema(
        operation_id="sites_term_delete",
        summary="Remove a category or a tag that nothing carries",
        description="Refused while an entry is filed under it in the panel or an entry's "
        "current publication names it (`term_in_use`, 409) — otherwise an archive visitors "
        "can open would become a 404; the preview says what holds it. Categories under a "
        "removed one move one level up. Its addresses become free. A person's decision: an "
        "integration and the assistant are refused (`person_required`).",
        tags=["sites"],
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "Removing what is already gone answers 404 and removes "
                "nothing else.",
            }
        },
        responses={200: TermRemovalSerializer, **_READ_ERRORS, 409: ProblemDetailsSerializer},
    )
    def delete(self, _request: Request, collection_id: UUID, term_id: UUID) -> Response:
        return Response(_removal_payload(delete_term(term_id=term_id, collection_id=collection_id)))


class ContentTypeTermPreviewView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_term_update_preview",
        summary="Preview renaming, moving or reordering a category or a tag",
        description="Validates and answers with the term as it would be and `published` — "
        "how many published entries are under it, whose archives would change at once — "
        "without saving. " + _UPDATE_RULES,
        tags=["sites"],
        request=TermUpdateSerializer,
        extensions={"x-dry-run": True},
        responses={200: TermChangeSerializer, **_ERRORS},
    )
    def post(self, request: Request, collection_id: UUID, term_id: UUID) -> Response:
        serializer = TermUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _change_payload(
                update_term(
                    term_id=term_id,
                    collection_id=collection_id,
                    **serializer.validated_data,
                    dry_run=True,
                )
            )
        )


class ContentTypeTermRemovalPreviewView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_term_delete_preview",
        summary="Whether a category or a tag can be removed, and what holds it",
        description="Answers without removing: `removable`, how many entries are filed "
        "under the term in the panel (`drafts`), how many entries' current publications "
        "carry it (`published`) and how many categories under it would move one level up.",
        tags=["sites"],
        request=None,
        extensions={"x-dry-run": True},
        responses={200: TermRemovalSerializer, **_READ_ERRORS},
    )
    def post(self, _request: Request, collection_id: UUID, term_id: UUID) -> Response:
        return Response(
            _removal_payload(
                delete_term(term_id=term_id, collection_id=collection_id, dry_run=True)
            )
        )


class ContentTypeTermNamesView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_term_names_set",
        summary="Name a category or a tag in the site's other languages",
        description="A person's names by language code, for the languages that change; an "
        "empty name removes it. The translation engine never overwrites a name written "
        "here and offers the term only in languages still without one. Where the term's "
        "address in a language is still open it is made from the name; if the archive there "
        "already answered under the site's language's address it moves once and closes — "
        "`moved` says from where to where — and the old address answers one 308. Published "
        "at once when the caller may publish, otherwise with the site's next publication. "
        "A person's decision: an integration and the assistant are refused "
        "(`person_required`).",
        tags=["sites"],
        request=TermNamesSerializer,
        extensions=_SET_VALUES,
        responses={200: TermChangeSerializer, **_ERRORS},
    )
    def put(self, request: Request, collection_id: UUID, term_id: UUID) -> Response:
        serializer = TermNamesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _change_payload(
                set_term_names(
                    term_id=term_id,
                    collection_id=collection_id,
                    names=serializer.validated_data["names"],
                )
            )
        )


_ADDRESS_RULES = (
    "Gives the term's archive another address in one language; in the site's own language "
    "it also moves every language without an address of its own. The old address answers "
    "one 308 from the moment this is saved, nothing is republished, and the address is "
    "closed afterwards: the name no longer changes it. An address another term of the same "
    "vocabulary has is refused (`term_slug_taken`); one that only redirects to another term "
    "can be taken — `takes_over` of the preview names the redirect that stops, and saving "
    "needs `take_over_former` (`term_slug_former` without it)."
)


class ContentTypeTermAddressView(APIView):
    """Session-only: moving an address costs what it earned, which is not an
    optimiser's trade to make."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_term_address_set",
        summary="Change the address of a category's or a tag's archive",
        description=_ADDRESS_RULES
        + " When the change moves an archive visitors could open (`moved` of the preview is "
        "not empty) a `reason` is required (`redirect_reason_required`). A person's "
        "decision (`person_required`).",
        tags=["sites"],
        request=TermAddressSerializer,
        extensions=_SET_VALUES,
        responses={200: TermChangeSerializer, **_ERRORS},
    )
    def put(self, request: Request, collection_id: UUID, term_id: UUID) -> Response:
        serializer = TermAddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _change_payload(
                change_term_address(
                    term_id=term_id, collection_id=collection_id, **serializer.validated_data
                )
            )
        )


class ContentTypeTermAddressPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_term_address_preview",
        summary="Preview changing the address of a category's or a tag's archive",
        description="Validates and answers with the term as it would be, the archives that "
        "would move (`moved`) and the redirects of other terms that would stop "
        "(`takes_over`), without saving. " + _ADDRESS_RULES,
        tags=["sites"],
        request=TermAddressSerializer,
        extensions={"x-dry-run": True},
        responses={200: TermChangeSerializer, **_ERRORS},
    )
    def post(self, request: Request, collection_id: UUID, term_id: UUID) -> Response:
        serializer = TermAddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _change_payload(
                change_term_address(
                    term_id=term_id,
                    collection_id=collection_id,
                    **serializer.validated_data,
                    dry_run=True,
                )
            )
        )


_SEGMENT_RULES = (
    "The word for „category” in a content type's addresses — `/<type>/<word>/<category>/` — "
    "in the site's own language (`segment`) and per other language (`locale_segments`; a "
    "language left out follows `segment`). The whole set is sent each time. Every category "
    "archive under a word that stops being the type's answers one 308 to today's from the "
    "moment this is saved. Never `tag` and never a language's word for „page” "
    "(`taxonomy_segment_reserved`). The type must have categories (`taxonomy_not_found`)."
)


class ContentTypeCategorySegmentsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_category_segments_set",
        summary="Change the word for „category” in a content type's addresses",
        description=_SEGMENT_RULES
        + " When archives visitors could open move (`moved` of the preview is not empty) a "
        "`reason` is required (`redirect_reason_required`). A person's decision.",
        tags=["sites"],
        request=TaxonomySegmentsSaveSerializer,
        extensions=_SET_VALUES,
        responses={200: TaxonomySegmentsSerializer, **_ERRORS},
    )
    def put(self, request: Request, collection_id: UUID) -> Response:
        serializer = TaxonomySegmentsSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _segments_payload(
                set_taxonomy_segments(collection_id=collection_id, **serializer.validated_data)
            )
        )


class ContentTypeCategorySegmentsPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_category_segments_preview",
        summary="Preview changing the word for „category” in a content type's addresses",
        description="Validates and answers with the words as they would be and what would "
        "move, without saving. " + _SEGMENT_RULES,
        tags=["sites"],
        request=TaxonomySegmentsSaveSerializer,
        extensions={"x-dry-run": True},
        responses={200: TaxonomySegmentsSerializer, **_ERRORS},
    )
    def post(self, request: Request, collection_id: UUID) -> Response:
        serializer = TaxonomySegmentsSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _segments_payload(
                set_taxonomy_segments(
                    collection_id=collection_id, **serializer.validated_data, dry_run=True
                )
            )
        )


class EntryCategoriesView(APIView):
    """The categories one entry is filed under, replaced as a whole set."""

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_categories_set",
        summary="File an entry under categories of its content type",
        description="Replaces the whole set (at most `max_per_entry`); the entry's tags are "
        "not touched. A category of another content type is refused (`term_not_of_type`). "
        "Visitors see the change when the entry is next published: an archive lists what "
        "publications carry. An integration files an entry by the entry's own rule — a "
        "grant for its content type and a type that takes automation's drafts — as it sets "
        "the entry's tags.",
        tags=["sites"],
        request=EntryCategoriesSaveSerializer,
        extensions=_SET_VALUES,
        responses={200: ContentEntryCategorySerializer(many=True), **_ERRORS},
    )
    def put(self, request: Request, entry_id: UUID) -> Response:
        serializer = EntryCategoriesSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        categories = set_entry_categories(
            entry_id=entry_id, term_ids=serializer.validated_data["term_ids"]
        )
        return Response([_category_payload(term) for term in categories])

    @extend_schema(
        operation_id="sites_entry_categories_list",
        summary="The categories an entry is filed under in the panel",
        description="What the entry's draft is filed under — what its next publication will "
        "carry, not necessarily what visitors see now.",
        tags=["sites"],
        responses={200: ContentEntryCategorySerializer(many=True), **_READ_ERRORS},
    )
    def get(self, _request: Request, entry_id: UUID) -> Response:
        return Response([
            _category_payload(term) for term in entry_terms(entry_id=entry_id).categories
        ])
