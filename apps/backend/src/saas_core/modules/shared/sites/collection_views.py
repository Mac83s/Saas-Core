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

from .collections import (
    SectionPaths,
    cancel_entry_publication_schedule,
    collection_paths,
    create_collection,
    create_entry,
    create_entry_translation,
    entry_tags,
    get_entry_draft,
    list_collections,
    list_entries,
    list_entry_translations,
    publish_entry,
    save_entry_draft,
    schedule_entry_publication,
    set_collection_automation_policy,
    set_collection_navigation,
    set_collection_paths,
    set_entry_tags,
    update_entry_metadata,
    withdraw_entry,
)
from .content_type_limit import ContentTypesLimit
from .content_types import (
    SCHEMA_TYPES,
    ContentTypeSwitch,
    delete_content_type,
    list_content_types,
    switch_off_content_type,
    switch_on_content_type,
    update_content_type,
)
from .models import ContentCollection, ContentEntry, ContentEntryPublication
from .serializers import (
    AutomationPolicySerializer,
    CollectionNavigationSerializer,
    CollectionPathsResultSerializer,
    CollectionPathsSerializer,
    ContentCollectionCreateSerializer,
    ContentCollectionSerializer,
    ContentEntryCreateSerializer,
    ContentEntryDraftSaveSerializer,
    ContentEntryDraftSerializer,
    ContentEntryListSerializer,
    ContentEntryMetadataSerializer,
    ContentEntryPublicationSerializer,
    ContentEntrySerializer,
    ContentEntryTranslationCreateSerializer,
    ContentTagSerializer,
    ContentTypesSerializer,
    ContentTypeSwitchSerializer,
    ContentTypeUpdateResultSerializer,
    ContentTypeUpdateSerializer,
    CursorQuerySerializer,
    EntryScheduleSerializer,
    EntryScheduleStateSerializer,
    EntryTagsSaveSerializer,
    PageSummarySerializer,
)
from .services import set_page_automation_policy
from .views import CURSOR_PARAMETER, LIMIT_PARAMETER, _draft_author

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
)


def _collection_payload(collection: ContentCollection) -> dict[str, Any]:
    return {
        "id": str(collection.id),
        "site_id": str(collection.site_id),
        "key": collection.key,
        "name": collection.name,
        "kind": collection.kind,
        "base_path": collection.base_path,
        "locale_paths": dict(collection.locale_paths or {}),
        "paths": collection_paths(collection),
        "automation_policy": collection.automation_policy,
        "show_in_navigation": collection.show_in_navigation,
        "schema_type": collection.schema_type,
        "in_site_feed": collection.in_site_feed,
        "archived": collection.archived_at is not None,
        "archived_at": collection.archived_at,
    }


def _entry_payload(entry: ContentEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "collection_id": str(entry.collection_id),
        "slug": entry.slug,
        "locale": entry.locale,
        "title": entry.title,
        "excerpt": entry.excerpt,
        "author_name": entry.author_name,
        "state": entry.state,
        "version": entry.version,
        "published_at": entry.published_at,
        # Which publication is live. The panel keys a republish on it, so
        # pressing the button twice in a row is one publication while
        # pressing it again after the first has landed is a second.
        "publication_id": (
            str(entry.current_publication_id)
            if entry.current_publication_id
            else None
        ),
        "noindex": entry.noindex,
        "draft_author": _draft_author(entry.current_draft),
        "translation_group": str(entry.translation_group),
        # Carried in the listing rather than fetched per row: an operator
        # scanning a blog needs to see at a glance which article is waiting and
        # which one failed on Monday morning.
        "schedule_state": entry.schedule_state,
        "scheduled_publish_at": entry.scheduled_publish_at,
        "schedule_error": entry.schedule_error,
        "tags": [
            {"slug": link.tag.slug, "name": link.tag.name}
            for link in sorted(entry.tag_links.all(), key=lambda item: item.tag.slug)
        ],
        "translation_of": (
            str(entry.translation_of_id) if entry.translation_of_id else None
        ),
        "pending_reason": entry.pending_reason,
    }


def _draft_payload(draft: Any) -> dict[str, Any]:
    return {
        "entry_id": str(draft.entry.id),
        "version": draft.entry.version,
        "blocks": draft.version.blocks if draft.version else [],
        "media_asset_ids": [str(asset_id) for asset_id in draft.media_asset_ids],
    }


def _publication_payload(publication: ContentEntryPublication) -> dict[str, Any]:
    return {
        "id": str(publication.id),
        "entry_id": str(publication.entry_id),
        "sequence": publication.sequence,
        "snapshot_hash": publication.snapshot_hash,
    }


class ContentCollectionListCreateView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_collections_list",
        summary="List a site's sections of entries",
        description="The content types of one site — its blog and whatever the company made "
        "beside it — each with its name in the addresses per language (`base_path`, "
        "`locale_paths`), where its index answers (`paths`), what its entries are to search "
        "engines (`schema_type`), whether they are in the site's feeds (`in_site_feed`) and "
        "whether the type is switched off (`archived`). An integration sees the sections its "
        "grants name.",
        tags=["sites"],
        responses={
            200: ContentCollectionSerializer(many=True),
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, site_id: UUID) -> Response:
        return Response(
            [_collection_payload(item) for item in list_collections(site_id=site_id)]
        )

    @extend_schema(
        operation_id="sites_collections_create",
        summary="Create a section of entries",
        description="Opens a blog, news or guide section on a site. `base_path` is its name "
        "in the addresses of the site's own language (`/blog/`); `locale_paths` may name it "
        "differently in other languages (`/de/ratgeber/`), and a language left out follows "
        "`base_path`. A name is refused when another section or a page has it in that "
        "language (`section_path_taken`) or when it is reserved (`slug_reserved`). A site's "
        "first section takes the site's own entitlement; a further one — a further content "
        "type — is refused where the platform offers none (`content_types_not_offered`), "
        "when the plan's limit of types beyond the first is used up (`quota_exceeded`) or the "
        "subscription does not allow adding now (`plan_access_denied`); the types the site "
        "has stay as they are. `GET /api/v1/sites/{site_id}/content-types/` says beforehand "
        "whether one more is allowed.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=ContentCollectionCreateSerializer,
        responses={
            200: ContentCollectionSerializer,
            201: ContentCollectionSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        serializer = ContentCollectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collection, created = create_collection(
            site_id=site_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _collection_payload(collection),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


def _limit_payload(limit: ContentTypesLimit) -> dict[str, Any]:
    return {
        "allowed": limit.allowed,
        "code": limit.code,
        "message": limit.message,
        "offered": limit.offered,
        "additional_max": limit.additional_max,
        "additional_used": limit.additional_used,
    }


class ContentTypesView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_content_types_list",
        summary="List a site's content types and whether it may have one more",
        description="The site's content types, the first made first — the blog leads — with "
        "how many entries each has and in which languages; switched-off types are listed and "
        "marked. `limit` is the platform's and the plan's word on making one more type: a "
        "site's first takes nothing but the site, a further one needs the platform's offer "
        "and room in the plan's limit of switched-on types beyond the first. `schema_types` "
        "lists what a type's entries may be to search engines. An integration sees the types "
        "its grants name.",
        tags=["sites"],
        responses={
            200: ContentTypesSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, site_id: UUID) -> Response:
        found = list_content_types(site_id=site_id)
        return Response({
            "types": [
                {
                    "collection": _collection_payload(row.collection),
                    "entries": row.entries,
                    "published": row.published,
                    "locales": list(row.locales),
                }
                for row in found.types
            ],
            "limit": _limit_payload(found.limit),
            "schema_types": list(SCHEMA_TYPES),
        })


_SETTINGS_RULES = (
    "`name` is the type's name — the heading of its list on the site; `schema_type` says "
    "what its entries are to search engines (`BlogPosting`, `NewsArticle`, `Article`, or "
    "`WebPage` for plain pages without an article node); `in_site_feed` whether they are in "
    "the site's RSS and Atom feeds. A field left out stays. All three are read when a page "
    "is asked for: the heading of the type's list, the structured data and the feeds change "
    "at once and nothing is republished. The site's menu is the exception — it names the "
    "type as the site's last publication did, so a new name reaches the menu with the site's "
    "next publication. The type's addresses are changed by `sites_collection_paths_set`. A "
    "switched-off type is refused (`content_type_archived`)."
)


class ContentTypeSettingsView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_content_type_update",
        summary="Change a content type's name, kind of content and place in the feeds",
        description=_SETTINGS_RULES,
        tags=["sites"],
        request=ContentTypeUpdateSerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The values are sent as they should be: a repeat sets the "
                "same values and changes nothing (`changed: false`).",
            }
        },
        responses={
            200: ContentTypeUpdateResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, collection_id: UUID) -> Response:
        serializer = ContentTypeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collection, changed = update_content_type(
            collection_id=collection_id, **serializer.validated_data
        )
        return Response({"collection": _collection_payload(collection), "changed": changed})


class ContentTypeSettingsPreviewView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_content_type_update_preview",
        summary="Preview a change of a content type's name, kind of content and feeds",
        description="Validates the values and answers with the type as it would be, without "
        "saving. " + _SETTINGS_RULES,
        tags=["sites"],
        request=ContentTypeUpdateSerializer,
        extensions={"x-dry-run": True},
        responses={
            200: ContentTypeUpdateResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, collection_id: UUID) -> Response:
        serializer = ContentTypeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collection, changed = update_content_type(
            collection_id=collection_id, **serializer.validated_data, dry_run=True
        )
        return Response({"collection": _collection_payload(collection), "changed": changed})


def _switch_payload(result: ContentTypeSwitch) -> dict[str, Any]:
    return {
        "collection": _collection_payload(result.collection),
        "changed": result.changed,
        "published": result.published,
        "scheduled": result.scheduled,
        "paths": result.paths,
        "restorable": result.restorable,
        "restore_problem": result.restore_problem,
        "restore_problem_code": result.restore_problem_code,
    }


_SWITCH_OFF_RULES = (
    "From the moment it is saved every address of the type — its list, entries, subjects' "
    "archives and their later pages — answers 404 and the type leaves the menu, the feeds, "
    "the sitemap and other pages' language links. Nothing is removed: entries stay as they "
    "are but are neither edited nor published while the type is off — a person may still "
    "withdraw one, so that it does not return with the type; publications planned for later "
    "are called off (`scheduled`), and the type's addresses stay taken, so switching it on "
    "brings everything back. A switched-off type does not count to the "
    "plan's limit and switching it on needs room in it: `restorable` says whether the plan "
    "as it is would let the type back. A person's decision: an integration and the assistant "
    "are refused (`person_required`)."
)
_SWITCH_ON_RULES = (
    "The type's list and every entry that was out answer again at the addresses they had, "
    "at once; the type is back in the menu where it was set to be, in the feeds and the "
    "sitemap. Needs the platform's offer and room in the plan's limit, like making a type: "
    "`content_types_not_offered`, `quota_exceeded`, `plan_access_denied`. Publications "
    "called off when it was switched off stay called off. A person's decision "
    "(`person_required`)."
)
_SWITCH_EXEMPT = {
    "x-quality-exempt": {
        "idempotency-key": "The call names a state, not a step: a repeat finds the type "
        "already so and changes nothing (`changed: false`).",
        "error-400": "The request has no body; a refusal is 403, 404 or — for switching on "
        "without room in the plan — the documented 400 of the limit.",
    }
}


class ContentTypeSwitchOffView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_content_type_switch_off",
        summary="Switch a content type off",
        description=_SWITCH_OFF_RULES,
        tags=["sites"],
        request=None,
        extensions=_SWITCH_EXEMPT,
        responses={
            200: ContentTypeSwitchSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def post(self, _request: Request, collection_id: UUID) -> Response:
        return Response(_switch_payload(switch_off_content_type(collection_id=collection_id)))


class ContentTypeSwitchOffPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_content_type_switch_off_preview",
        summary="Preview switching a content type off",
        description="Answers with what switching the type off would do — the addresses that "
        "stop answering, the entries behind them, the publications called off and whether "
        "the plan would let the type back — without saving. " + _SWITCH_OFF_RULES,
        tags=["sites"],
        request=None,
        extensions={"x-dry-run": True},
        responses={
            200: ContentTypeSwitchSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def post(self, _request: Request, collection_id: UUID) -> Response:
        return Response(
            _switch_payload(switch_off_content_type(collection_id=collection_id, dry_run=True))
        )


class ContentTypeSwitchOnView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_content_type_switch_on",
        summary="Switch a content type back on",
        description=_SWITCH_ON_RULES,
        tags=["sites"],
        request=None,
        extensions=_SWITCH_EXEMPT,
        responses={
            200: ContentTypeSwitchSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def post(self, _request: Request, collection_id: UUID) -> Response:
        return Response(_switch_payload(switch_on_content_type(collection_id=collection_id)))


class ContentTypeDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_content_type_delete",
        summary="Remove a content type that has no entries",
        description="Removes a type without a single entry — a draft counts "
        "(`content_type_not_empty`); a type with entries is switched off instead. Its names "
        "in addresses become free and its former names stop leading anywhere. A person's "
        "decision (`person_required`).",
        tags=["sites"],
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "Nothing is removed twice: a repeat answers 404.",
            }
        },
        responses={
            204: None,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def delete(self, _request: Request, collection_id: UUID) -> Response:
        delete_content_type(collection_id=collection_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ContentEntryListCreateView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entries_list",
        tags=["sites"],
        parameters=[CURSOR_PARAMETER, LIMIT_PARAMETER],
        responses={
            200: ContentEntryListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, collection_id: UUID) -> Response:
        query = CursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, next_cursor = list_entries(
            collection_id=collection_id,
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response({
            "items": [_entry_payload(entry) for entry in rows],
            "next_cursor": next_cursor,
        })

    @extend_schema(
        operation_id="sites_entries_create",
        summary="Create an entry in a collection",
        description="A new article in one of the company's content languages; 400 "
        "`locale_not_enabled` or `locale_not_in_registry` on `locale` (ADR-071 pkt 3).",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=ContentEntryCreateSerializer,
        responses={
            200: ContentEntrySerializer,
            201: ContentEntrySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, collection_id: UUID) -> Response:
        serializer = ContentEntryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry, created = create_entry(
            collection_id=collection_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _entry_payload(entry),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ContentEntryDraftView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_draft_retrieve",
        tags=["sites"],
        responses={
            200: ContentEntryDraftSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, entry_id: UUID) -> Response:
        return Response(_draft_payload(get_entry_draft(entry_id=entry_id)))

    @extend_schema(
        operation_id="sites_entry_draft_save",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=ContentEntryDraftSaveSerializer,
        responses={
            200: ContentEntryDraftSerializer,
            201: ContentEntryDraftSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, entry_id: UUID) -> Response:
        serializer = ContentEntryDraftSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _, created = save_entry_draft(
            entry_id=entry_id,
            expected_version=serializer.validated_data["expected_version"],
            blocks=serializer.validated_data["blocks"],
            media_asset_ids=serializer.validated_data.get("media_asset_ids", []),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _draft_payload(get_entry_draft(entry_id=entry_id)),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ContentEntryPublicationView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_publish",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=None,
        responses={
            200: ContentEntryPublicationSerializer,
            201: ContentEntryPublicationSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, entry_id: UUID) -> Response:
        publication, created = publish_entry(
            entry_id=entry_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            # Asked for by name: a person's publication of a translation is
            # their acceptance of it; an integration's is not (the service
            # checks who asks).
            person_decision=True,
        )
        return Response(
            _publication_payload(publication),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        operation_id="sites_entry_withdraw",
        tags=["sites"],
        responses={
            200: ContentEntrySerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def delete(self, _request: Request, entry_id: UUID) -> Response:
        return Response(_entry_payload(withdraw_entry(entry_id=entry_id)))


class ContentCollectionPolicyView(APIView):
    """Changing who may write a collection is a person's decision, so this is
    session-only — a credential must not be able to widen its own reach."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_collection_policy_set",
        summary="Choose who writes a section's entries",
        description="People only, proposals to accept, or the content automation (ADR-035). "
        "A person's choice: an integration is refused.",
        tags=["sites"],
        request=AutomationPolicySerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The whole policy is sent each time: a repeat sets the same "
                "value and changes nothing.",
            }
        },
        responses={
            200: ContentCollectionSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, collection_id: UUID) -> Response:
        serializer = AutomationPolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collection = set_collection_automation_policy(
            collection_id=collection_id,
            policy=serializer.validated_data["automation_policy"],
        )
        return Response(_collection_payload(collection))


class PageAutomationPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_policy_set",
        summary="Choose who writes a page's content",
        description="People only, proposals to accept, or the content automation (ADR-035). "
        "A person's choice: an integration is refused, and the assistant acting for a person "
        "needs that person's consent (person_required).",
        tags=["sites"],
        request=AutomationPolicySerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The whole policy is sent each time: a repeat sets the same "
                "value and changes nothing.",
            }
        },
        responses={
            200: PageSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID) -> Response:
        serializer = AutomationPolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        page = set_page_automation_policy(
            page_id=page_id,
            policy=serializer.validated_data["automation_policy"],
        )
        return Response({
            "id": str(page.id),
            "site_id": str(page.site_id),
            "name": page.name,
            "key": page.key,
            "version": page.version,
            "current_draft_id": (
                str(page.current_draft_id) if page.current_draft_id else None
            ),
            "current_draft_hash": (
                page.current_draft.content_hash if page.current_draft else None
            ),
            "automation_policy": page.automation_policy,
            "draft_author": _draft_author(page.current_draft),
            "created_at": page.created_at,
            "updated_at": page.updated_at,
        })


class ContentCollectionNavigationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_collection_navigation_set",
        summary="Show or hide a section in the site's menu",
        description="Whether the published menu links to the section's index. Visible after "
        "the site's next publication, like every menu change. A person's choice: an "
        "integration is refused.",
        tags=["sites"],
        request=CollectionNavigationSerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The whole value is sent each time: a repeat sets the same "
                "value and changes nothing.",
            }
        },
        responses={
            200: ContentCollectionSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, collection_id: UUID) -> Response:
        serializer = CollectionNavigationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collection = set_collection_navigation(
            collection_id=collection_id,
            show=serializer.validated_data["show_in_navigation"],
        )
        return Response(_collection_payload(collection))


def _paths_result(result: SectionPaths) -> dict[str, Any]:
    return {
        "collection": {**_collection_payload(result.collection), "paths": result.paths},
        "moved": list(result.moved),
        "changed": result.changed,
    }


_PATHS_RULES = (
    "`base_path` names the section in the addresses of the site's own language, "
    "`locale_paths` in others; the whole set is sent each time and a language left out "
    "follows `base_path`. Every address under a name that stops being the section's — the "
    "index, articles, subjects' archives and their later pages — answers one 308 to today's; "
    "nothing is republished and articles keep their slugs. Refused per field: "
    "`section_path_taken` (another section or a page has the name in that language), "
    "`slug_reserved`, `section_path_invalid`, `section_path_source_locale`, "
    "`locale_not_enabled`. A person's decision: an integration and the assistant are refused "
    "(`person_required`)."
)


class ContentCollectionPathsView(APIView):
    """A section's names in the site's addresses. Session-only: moving an
    address costs what it earned, which is not an optimiser's trade to make."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_collection_paths_set",
        summary="Rename a section in the site's addresses",
        description=_PATHS_RULES
        + " When the change moves an address visitors can open today (`moved` of the preview "
        "is not empty) a `reason` is required (`redirect_reason_required`).",
        tags=["sites"],
        request=CollectionPathsSerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "The whole set of names is sent each time: a repeat sets "
                "the same names and changes nothing.",
            }
        },
        responses={
            200: CollectionPathsResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, collection_id: UUID) -> Response:
        serializer = CollectionPathsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _paths_result(
                set_collection_paths(collection_id=collection_id, **serializer.validated_data)
            )
        )


class ContentCollectionPathsPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_collection_paths_preview",
        summary="Preview renaming a section in the site's addresses",
        description="Validates the names and answers with the section's addresses as they "
        "would be and the addresses that would move, without saving. " + _PATHS_RULES,
        tags=["sites"],
        request=CollectionPathsSerializer,
        extensions={"x-dry-run": True},
        responses={
            200: CollectionPathsResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, collection_id: UUID) -> Response:
        serializer = CollectionPathsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _paths_result(
                set_collection_paths(
                    collection_id=collection_id, **serializer.validated_data, dry_run=True
                )
            )
        )


class ContentEntryTranslationView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_translations_list",
        tags=["sites"],
        responses={
            200: ContentEntrySerializer(many=True),
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, entry_id: UUID) -> Response:
        return Response([
            _entry_payload(item) for item in list_entry_translations(entry_id=entry_id)
        ])

    @extend_schema(
        operation_id="sites_entry_translation_create",
        summary="Start an entry in another language",
        description="A sibling entry in the same translation group, in one of the company's "
        "content languages; it is published on its own (ADR-070 pkt 16).",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=ContentEntryTranslationCreateSerializer,
        responses={
            200: ContentEntrySerializer,
            201: ContentEntrySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, entry_id: UUID) -> Response:
        serializer = ContentEntryTranslationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        translation, created = create_entry_translation(
            entry_id=entry_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _entry_payload(translation),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ContentEntryMetadataView(APIView):
    """What an article says about itself apart from its text: title, excerpt,
    author and indexing (ADR-070 pkt 16)."""

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_metadata_update",
        summary="Change an entry's title, excerpt, author or indexing",
        description="A field left out keeps its value; visitors see the change with the "
        "entry's next publication. On a translation, a person's title or excerpt is "
        "theirs: a translation job proposes beside it rather than over it.",
        tags=["sites"],
        request=ContentEntryMetadataSerializer,
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "Each field sent is set to its value: a repeat sets the "
                "same values, changes nothing and records no history entry.",
            }
        },
        responses={
            200: ContentEntrySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def patch(self, request: Request, entry_id: UUID) -> Response:
        serializer = ContentEntryMetadataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = update_entry_metadata(entry_id=entry_id, **serializer.validated_data)
        return Response(_entry_payload(entry))


def _schedule_payload(entry: Any) -> dict[str, Any]:
    return {
        "entry_id": entry.id,
        "schedule_state": entry.schedule_state,
        "scheduled_publish_at": entry.scheduled_publish_at,
        "schedule_error": entry.schedule_error,
    }


class EntryScheduleView(APIView):
    """Asks for an article to go live later, or calls that off."""

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_schedule_set",
        tags=["sites"],
        request=EntryScheduleSerializer,
        responses={
            200: EntryScheduleStateSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, entry_id: UUID) -> Response:
        serializer = EntryScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = schedule_entry_publication(
            entry_id=entry_id, publish_at=serializer.validated_data["publish_at"]
        )
        return Response(_schedule_payload(entry))

    @extend_schema(
        operation_id="sites_entry_schedule_cancel",
        tags=["sites"],
        responses={
            200: EntryScheduleStateSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def delete(self, _request: Request, entry_id: UUID) -> Response:
        return Response(
            _schedule_payload(cancel_entry_publication_schedule(entry_id=entry_id))
        )


class EntryTagsView(APIView):
    """What one article is about, replaced as a whole set.

    Replacing rather than adding is what makes it safe to send the same list
    twice: an automation replaying a change set must not slowly accumulate
    every subject it has ever suggested.
    """

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_entry_tags_set",
        tags=["sites"],
        request=EntryTagsSaveSerializer,
        responses={
            200: ContentTagSerializer(many=True),
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, entry_id: UUID) -> Response:
        serializer = EntryTagsSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tags = set_entry_tags(
            entry_id=entry_id, names=serializer.validated_data["names"]
        )
        return Response([{"slug": tag.slug, "name": tag.name} for tag in tags])

    @extend_schema(
        operation_id="sites_entry_tags_list",
        tags=["sites"],
        responses={
            200: ContentTagSerializer(many=True),
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, entry_id: UUID) -> Response:
        return Response([
            {"slug": tag.slug, "name": tag.name}
            for tag in entry_tags(entry_id=entry_id)
        ])
