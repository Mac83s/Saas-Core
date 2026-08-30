from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer
from saas_core.modules.shared.notifications.api_key_middleware import (
    IsSessionOrApiKey,
)

from .capabilities import read_content_capabilities
from .change_sets import (
    apply_change_set,
    change_set_diff,
    plan_change_set,
    validate_change_set,
)
from .connections import list_automation_connections, list_pending_proposals
from .inventory import inventory_etag, read_inventory
from .localization import LocaleResolution, SiteLocalizationReport
from .models import Page, PageBlock, PageTranslation, Publication, Site
from .operations import read_operation_status
from .serializers import (
    AutomationConnectionSerializer,
    ChangeSetApplySerializer,
    ChangeSetDiffSerializer,
    ChangeSetProposalSerializer,
    ChangeSetResultSerializer,
    ContentCapabilitiesSerializer,
    ContentInventorySerializer,
    ContentProposalSerializer,
    CursorQuerySerializer,
    DraftSaveSerializer,
    GrantRevokeSerializer,
    OperationStatusSerializer,
    PageCreateSerializer,
    PageDraftSerializer,
    PageListSerializer,
    PageSummarySerializer,
    PageTemplateImportSerializer,
    PageTranslationListSerializer,
    PageTranslationSaveSerializer,
    PageTranslationSerializer,
    PageTypeSerializer,
    PageUrlChangeSerializer,
    SiteCreateSerializer,
    SiteListSerializer,
    SiteLocalizationReportSerializer,
    SiteNavigationSaveSerializer,
    SiteNavigationSerializer,
    SitePublicationListSerializer,
    SitePublicationSerializer,
    SitePublishSerializer,
    SitePurposeSerializer,
    SiteRedirectSerializer,
    SiteRollbackSerializer,
    SiteSummarySerializer,
)
from .services import (
    PageDraft,
    SiteNavigation,
    change_page_url,
    create_page,
    create_site,
    delete_site_redirect,
    get_draft,
    get_draft_preview,
    get_site_localization_report,
    get_site_navigation,
    import_page_template,
    list_page_translations,
    list_pages,
    list_site_publications,
    list_site_redirects,
    list_sites,
    publish_site,
    revoke_automation_grant,
    rollback_site,
    save_draft,
    save_page_translation,
    save_site_navigation,
    set_page_type,
    set_site_purpose,
)

IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Klucz bezpiecznego ponowienia mutacji w zakresie organizacji i użytkownika.",
)
CURSOR_PARAMETER = OpenApiParameter(
    name="cursor",
    type=UUID,
    location=OpenApiParameter.QUERY,
    required=False,
)
LIMIT_PARAMETER = OpenApiParameter(
    name="limit",
    type=int,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Liczba elementów od 1 do 100; domyślnie 50.",
)


@method_decorator(csrf_protect, name="dispatch")
class SiteListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_list",
        tags=["sites"],
        parameters=[CURSOR_PARAMETER, LIMIT_PARAMETER],
        responses={
            200: SiteListSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = CursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items, next_cursor = list_sites(
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response({
            "items": [_site_summary(site) for site in items],
            "next_cursor": next_cursor,
        })

    @extend_schema(
        operation_id="sites_create",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=SiteCreateSerializer,
        responses={
            200: SiteSummarySerializer,
            201: SiteSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = SiteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_site(
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _site_summary(result.value),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class PageListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_pages_list",
        tags=["sites"],
        parameters=[CURSOR_PARAMETER, LIMIT_PARAMETER],
        responses={
            200: PageListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = CursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items, next_cursor = list_pages(
            site_id=site_id,
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response({
            "items": [_page_summary(page) for page in items],
            "next_cursor": next_cursor,
        })

    @extend_schema(
        operation_id="sites_pages_create",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=PageCreateSerializer,
        responses={
            200: PageSummarySerializer,
            201: PageSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        serializer = PageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_page(
            site_id=site_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _page_summary(result.value),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class PageDraftView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_draft_retrieve",
        tags=["sites"],
        responses={
            200: PageDraftSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, page_id: UUID) -> Response:
        return Response(_draft_summary(page_id))

    @extend_schema(
        operation_id="sites_page_draft_save",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=DraftSaveSerializer,
        responses={
            200: PageDraftSerializer,
            201: PageDraftSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID) -> Response:
        serializer = DraftSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_draft(
            page_id=page_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _draft_summary(page_id),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class PageTemplateImportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_template_import",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=PageTemplateImportSerializer,
        responses={
            200: PageDraftSerializer,
            201: PageDraftSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, page_id: UUID) -> Response:
        serializer = PageTemplateImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = import_page_template(
            page_id=page_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _draft_summary(page_id),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


class SiteNavigationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_navigation_retrieve",
        tags=["sites"],
        responses={
            200: SiteNavigationSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, site_id: UUID) -> Response:
        return Response(_navigation_summary(get_site_navigation(site_id=site_id)))

    @extend_schema(
        operation_id="sites_navigation_save",
        tags=["sites"],
        request=SiteNavigationSaveSerializer,
        responses={
            200: SiteNavigationSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, site_id: UUID) -> Response:
        serializer = SiteNavigationSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        navigation = save_site_navigation(
            site_id=site_id,
            expected_version=serializer.validated_data["expected_version"],
            items=serializer.validated_data["items"],
        )
        return Response(_navigation_summary(navigation))


def _navigation_summary(navigation: SiteNavigation) -> dict[str, Any]:
    parent_page_by_id = {item.id: item.page_id for item in navigation.items}
    return {
        "site_id": str(navigation.site.id),
        "version": navigation.site.navigation_version,
        "items": [
            {
                "page_id": str(item.page_id),
                "parent_page_id": (
                    str(parent_page_by_id[item.parent_id])
                    if item.parent_id is not None
                    else None
                ),
                "visible": item.visible,
            }
            for item in navigation.items
        ],
    }


class PageDraftPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_draft_preview_retrieve",
        tags=["sites"],
        responses={
            200: PageDraftSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, page_id: UUID, version_id: UUID) -> Response:
        return Response(_draft_payload(get_draft_preview(page_id=page_id, version_id=version_id)))


class PageTranslationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_translations_list",
        tags=["sites"],
        responses={
            200: PageTranslationListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, page_id: UUID) -> Response:
        translations = list_page_translations(page_id=page_id)
        return Response({
            "page_id": translations.page.id,
            "default_locale": translations.page.site.default_locale,
            "supported_locales": list(translations.supported_locales),
            "items": [
                _translation_summary(translation) for translation in translations.translations
            ],
        })


@method_decorator(csrf_protect, name="dispatch")
class PageTranslationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_translation_save",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=PageTranslationSaveSerializer,
        responses={
            200: PageTranslationSerializer,
            201: PageTranslationSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = PageTranslationSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_page_translation(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _translation_summary(result.value),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


class SiteLocalizationReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_localization_report_retrieve",
        tags=["sites"],
        responses={
            200: SiteLocalizationReportSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, site_id: UUID) -> Response:
        return Response(_localization_report(get_site_localization_report(site_id=site_id)))


@method_decorator(csrf_protect, name="dispatch")
class SitePublicationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_publications_list",
        tags=["sites"],
        parameters=[CURSOR_PARAMETER, LIMIT_PARAMETER],
        responses={
            200: SitePublicationListSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = CursorQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items, next_cursor = list_site_publications(
            site_id=site_id,
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        return Response({
            "items": [_publication_summary(publication) for publication in items],
            "next_cursor": next_cursor,
        })

    @extend_schema(
        operation_id="sites_publish",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=SitePublishSerializer,
        responses={
            200: SitePublicationSerializer,
            201: SitePublicationSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        serializer = SitePublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = publish_site(
            site_id=site_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _publication_summary(result.publication),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


@method_decorator(csrf_protect, name="dispatch")
class SitePublicationRollbackView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_publication_rollback",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=SiteRollbackSerializer,
        responses={
            200: SitePublicationSerializer,
            201: SitePublicationSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def post(
        self,
        request: Request,
        site_id: UUID,
        publication_id: UUID,
    ) -> Response:
        serializer = SiteRollbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = rollback_site(
            site_id=site_id,
            publication_id=publication_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _publication_summary(result.publication),
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )


def _site_summary(site: Site) -> dict[str, Any]:
    return {
        "id": site.id,
        "name": site.name,
        "slug": site.slug,
        "purpose": site.purpose,
        "default_locale": site.default_locale,
        "current_publication_id": site.current_publication_id,
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }


def _draft_author(version: Any) -> str | None:
    """Who wrote the draft that is currently waiting.

    `created_by` is always a person — for a credential it is whoever issued it —
    so the credential column is the only thing that can tell a proposal from
    the operator's own work.
    """
    if version is None:
        return None
    return "automation" if version.created_by_credential else "person"


def _page_summary(page: Page) -> dict[str, Any]:
    draft = page.current_draft
    return {
        "id": page.id,
        "site_id": page.site_id,
        "name": page.name,
        "key": page.key,
        "version": page.version,
        "current_draft_id": page.current_draft_id,
        "current_draft_hash": draft.content_hash if draft is not None else None,
        "page_type": page.page_type,
        "automation_policy": page.automation_policy,
        "draft_author": _draft_author(draft),
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }


def _publication_summary(publication: Publication) -> dict[str, Any]:
    return {
        "id": publication.id,
        "site_id": publication.site_id,
        "sequence": publication.sequence,
        "snapshot_schema_version": publication.snapshot_schema_version,
        "snapshot_hash": publication.snapshot_hash,
        "source_publication_id": publication.source_publication_id,
        "created_by": {
            "id": publication.created_by_id,
            "email": publication.created_by.email,
        },
        "created_at": publication.created_at,
    }


def _draft_summary(page_id: UUID) -> dict[str, Any]:
    return _draft_payload(get_draft(page_id=page_id))


def _draft_payload(draft: PageDraft) -> dict[str, Any]:
    return {
        "page_id": draft.page.id,
        "version": draft.version.number if draft.version is not None else draft.page.version,
        "draft_id": draft.version.id if draft.version is not None else None,
        "content_hash": draft.version.content_hash if draft.version is not None else None,
        "created_at": draft.version.created_at if draft.version is not None else None,
        "blocks": [_block_summary(block) for block in draft.blocks],
        "media_asset_ids": list(draft.media_asset_ids),
    }


def _block_summary(block: PageBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "position": block.position,
        "block_type": block.block_type,
        "schema_version": block.schema_version,
        "data": block.data,
    }


def _translation_summary(translation: PageTranslation) -> dict[str, Any]:
    return {
        "id": translation.id,
        "page_id": translation.page_id,
        "site_id": translation.site_id,
        "locale": translation.locale,
        "slug": translation.slug,
        "title": translation.title,
        "description": translation.description,
        "social_title": translation.social_title,
        "social_description": translation.social_description,
        "allow_title_fallback": translation.allow_title_fallback,
        "allow_description_fallback": translation.allow_description_fallback,
        "allow_social_title_fallback": translation.allow_social_title_fallback,
        "allow_social_description_fallback": (translation.allow_social_description_fallback),
        "version": translation.version,
        "slug_locked": translation.slug_locked_at is not None,
        "created_at": translation.created_at,
        "updated_at": translation.updated_at,
    }


def _localization_report(report: SiteLocalizationReport) -> dict[str, Any]:
    return {
        "site_id": report.site.id,
        "default_locale": report.site.default_locale,
        "supported_locales": list(report.supported_locales),
        "ready_to_publish": report.ready_to_publish,
        "pages": [
            {
                "page_id": page.page.id,
                "page_key": page.page.key,
                "page_name": page.page.name,
                "locales": [_locale_resolution(locale) for locale in page.locales],
                "hreflang": page.hreflang,
                "x_default": page.x_default,
            }
            for page in report.pages
        ],
    }


def _locale_resolution(locale: LocaleResolution) -> dict[str, Any]:
    return {
        "locale": locale.locale,
        "translation_id": locale.translation_id,
        "version": locale.version,
        "slug": locale.slug,
        "path": locale.path,
        "canonical_path": locale.canonical_path,
        "title": locale.title,
        "description": locale.description,
        "social_title": locale.social_title,
        "social_description": locale.social_description,
        "fallback_fields": list(locale.fallback_fields),
        "missing_fields": list(locale.missing_fields),
        "complete": locale.complete,
        "slug_locked": locale.slug_locked,
    }


class ChangeSetProposalView(APIView):
    """What this change set would do, and nothing more.

    Answering with the diff we would apply — rather than with the sender's
    account of its own intent — is what makes an approval mean something. The
    same plan produces both this preview and the later effect.
    """

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_change_set_preview",
        tags=["sites"],
        request=ChangeSetProposalSerializer,
        responses={
            200: ChangeSetDiffSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            422: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ChangeSetProposalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.validated_data["change_set"]
        context = _change_set_context(document)
        plan = plan_change_set(document, context)
        return Response(change_set_diff(document, plan, context))


class ChangeSetApplyView(APIView):
    """Turns an accepted change set into a new draft, never into a mutation."""

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_change_set_apply",
        tags=["sites"],
        request=ChangeSetApplySerializer,
        parameters=[IDEMPOTENCY_PARAMETER],
        responses={
            201: ChangeSetResultSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
            422: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ChangeSetApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.validated_data["change_set"]
        context = _change_set_context(document)
        result = apply_change_set(
            document,
            context,
            idempotency_key=_idempotency_header(request, document),
            approval_digest=serializer.validated_data.get("approval_digest"),
        )
        return Response(result, status=status.HTTP_201_CREATED)


def _change_set_context(document: Any) -> Any:
    """The tenant this call already established, after the envelope is sound.

    Validated first so a malformed document is refused the same way whoever
    sent it can reproduce, before anything is looked up.
    """
    from saas_core.modules.core.organizations.context import require_tenant_context

    validate_change_set(document)
    return require_tenant_context()


def _idempotency_header(request: Request, document: Any) -> str:
    """The sender's key, or the one the document already carries.

    A change set names its own idempotency key, so a connector that forgets the
    header still cannot create two drafts from one intent.
    """
    header = str(request.headers.get("Idempotency-Key", "")).strip()
    if header:
        return header
    return str(document.get("idempotency_key", ""))


class OperationStatusView(APIView):
    """What the request carrying this key actually did.

    A connector whose connection died mid-mutation has two bad options: retry
    and risk a second effect, or give up and leave the two systems disagreeing.
    This is the third — asking, and getting an answer that costs nothing.

    `found: false` with a 200 is the right answer for a key nobody has seen. A
    404 would be indistinguishable from "this endpoint does not exist", which
    is exactly the ambiguity the caller came here to resolve.
    """

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_operation_status_retrieve",
        tags=["sites"],
        responses={
            200: OperationStatusSerializer,
            403: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, idempotency_key: str) -> Response:
        return Response(read_operation_status(idempotency_key=idempotency_key))


class AutomationConnectionListView(APIView):
    """Who may act here, how far they reach, and when they last did.

    Session-only: this is the supervision screen, and a credential able to read
    the list of credentials could map its own way to a wider one.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_automation_connections_list",
        tags=["sites"],
        responses={
            200: AutomationConnectionSerializer(many=True),
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request) -> Response:
        return Response(list_automation_connections())


class AutomationGrantRevokeView(APIView):
    """The emergency stop, one click from the list it appears in."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_automation_grant_revoke",
        tags=["sites"],
        request=GrantRevokeSerializer,
        responses={
            200: AutomationConnectionSerializer(many=True),
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request, grant_id: UUID) -> Response:
        serializer = GrantRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revoke_automation_grant(
            grant_id=grant_id, reason=serializer.validated_data["reason"]
        )
        # The whole list back, so the screen cannot show a stale row next to
        # the one it just changed.
        return Response(list_automation_connections())


class ContentProposalListView(APIView):
    """Drafts an automation wrote that nobody has published yet."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_content_proposals_list",
        tags=["sites"],
        responses={
            200: ContentProposalSerializer(many=True),
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request) -> Response:
        return Response(list_pending_proposals())


class ContentInventoryView(APIView):
    """One read, one moment, one hash.

    A connector that assembled its picture endpoint by endpoint would be
    planning against a state that never existed — the pages from one moment and
    the collections from another. The ETag then lets it ask "has anything I act
    on changed?" without paying for the whole answer.
    """

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_inventory_retrieve",
        tags=["sites"],
        parameters=[
            OpenApiParameter(
                name="If-None-Match",
                location=OpenApiParameter.HEADER,
                required=False,
                type=str,
                description="ETag z poprzedniego odczytu; 304 gdy nic się nie zmieniło.",
            )
        ],
        responses={
            200: ContentInventorySerializer,
            304: None,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        inventory = read_inventory()
        etag = inventory_etag(inventory)
        if request.headers.get("If-None-Match") == etag:
            # Nothing the caller acts on has moved. The moment it was read has,
            # which is exactly why the timestamp is outside the hash.
            not_modified = Response(status=304)
            not_modified["ETag"] = etag
            return not_modified
        response = Response(inventory)
        response["ETag"] = etag
        return response


class ContentCapabilitiesView(APIView):
    """What this tenant's content surface can do.

    Readable by the panel and by an integration with a read scope: a connector
    with no database has no other way to learn which blocks, languages and
    limits it is working against, and finding out by having a write refused is
    a worse answer.
    """

    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_capabilities_retrieve",
        tags=["sites"],
        responses={
            200: ContentCapabilitiesSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request) -> Response:
        return Response(read_content_capabilities())


class SitePurposeView(APIView):
    """Marks what a site is for.

    Session-only: the label is what inventory and SeoContentRank reason about,
    so a credential able to set it could describe a customer's site as ours.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_purpose_set",
        tags=["sites"],
        request=SitePurposeSerializer,
        responses={
            200: SiteSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, site_id: UUID) -> Response:
        serializer = SitePurposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        site = set_site_purpose(
            site_id=site_id, purpose=serializer.validated_data["purpose"]
        )
        return Response(_site_summary(site))


class PageTypeView(APIView):
    """See `SitePurposeView`: a person marks what a page is."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_type_set",
        tags=["sites"],
        request=PageTypeSerializer,
        responses={
            200: PageSummarySerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID) -> Response:
        serializer = PageTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        page = set_page_type(
            page_id=page_id, page_type=serializer.validated_data["page_type"]
        )
        return Response(_page_summary(page))


def _redirect_payload(redirect: Any) -> dict[str, Any]:
    return {
        "id": redirect.id,
        "locale": redirect.locale,
        "from_path": redirect.from_path,
        "to_path": redirect.to_path,
        "reason": redirect.reason,
    }


class PageUrlView(APIView):
    """Moves a published page, leaving a redirect behind.

    Session-only. The slug lock exists because every link and search result
    points at the published address; this is the single audited way past it.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_url_change",
        tags=["sites"],
        request=PageUrlChangeSerializer,
        responses={
            200: SiteRedirectSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
    )
    def put(self, request: Request, page_id: UUID) -> Response:
        serializer = PageUrlChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _translation, redirect = change_page_url(
            page_id=page_id,
            locale=serializer.validated_data["locale"],
            slug=serializer.validated_data["slug"],
            reason=serializer.validated_data["reason"],
        )
        return Response(_redirect_payload(redirect))


class SiteRedirectListView(APIView):
    permission_classes = [IsSessionOrApiKey]

    @extend_schema(
        operation_id="sites_redirects_list",
        tags=["sites"],
        responses={
            200: SiteRedirectSerializer(many=True),
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, site_id: UUID) -> Response:
        return Response([
            _redirect_payload(item) for item in list_site_redirects(site_id=site_id)
        ])


class SiteRedirectView(APIView):
    """Removes one redirect. Session-only: dropping it costs whatever still
    follows the old address, which is a person's call."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_redirect_delete",
        tags=["sites"],
        responses={
            204: None,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def delete(self, _request: Request, redirect_id: UUID) -> Response:
        delete_site_redirect(redirect_id=redirect_id)
        return Response(status=204)
