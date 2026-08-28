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
    create_collection,
    create_entry,
    get_entry_draft,
    list_collections,
    list_entries,
    publish_entry,
    save_entry_draft,
    set_collection_automation_policy,
    withdraw_entry,
)
from .models import ContentCollection, ContentEntry, ContentEntryPublication
from .serializers import (
    AutomationPolicySerializer,
    ContentCollectionCreateSerializer,
    ContentCollectionSerializer,
    ContentEntryCreateSerializer,
    ContentEntryDraftSaveSerializer,
    ContentEntryDraftSerializer,
    ContentEntryListSerializer,
    ContentEntryPublicationSerializer,
    ContentEntrySerializer,
    CursorQuerySerializer,
    PageSummarySerializer,
)
from .services import set_page_automation_policy
from .views import CURSOR_PARAMETER, LIMIT_PARAMETER

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
        "automation_policy": collection.automation_policy,
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
        "noindex": entry.noindex,
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
        draft = get_entry_draft(entry_id=entry_id)
        return Response({
            "entry_id": str(draft.entry.id),
            "version": draft.entry.version,
            "blocks": draft.version.blocks if draft.version else [],
        })

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
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        draft = get_entry_draft(entry_id=entry_id)
        return Response(
            {
                "entry_id": str(draft.entry.id),
                "version": draft.entry.version,
                "blocks": draft.version.blocks if draft.version else [],
            },
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
        tags=["sites"],
        request=AutomationPolicySerializer,
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
        tags=["sites"],
        request=AutomationPolicySerializer,
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
            "created_at": page.created_at,
            "updated_at": page.updated_at,
        })
