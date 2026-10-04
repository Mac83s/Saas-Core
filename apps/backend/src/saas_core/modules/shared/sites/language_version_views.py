from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .language_decisions import (
    LanguageDecision,
    accept_locale_version,
    accept_locale_versions,
    batch_digest,
    publish_locale_version,
    reject_locale_version,
    withdraw_locale_version,
)
from .language_plan import preview_site_publication
from .language_version_serializers import (
    LanguageDecisionSerializer,
    LocaleAcceptSerializer,
    LocaleBatchAcceptSerializer,
    LocaleBatchResultSerializer,
    LocaleBodyCopySerializer,
    LocaleBodyRebaseSerializer,
    LocaleBodyRestoreSerializer,
    LocaleBodySaveSerializer,
    LocaleBodySerializer,
    LocaleBodyVersionListSerializer,
    LocaleBodyVersionPreviewSerializer,
    PublicationPlanSerializer,
    SiteTextsPublicationSerializer,
    SiteTextsSaveSerializer,
    SiteTextsSerializer,
    TranslationOverviewQuerySerializer,
    TranslationOverviewSerializer,
)
from .language_versions import (
    LocaleBody,
    copy_source_into_locale_body,
    get_locale_body,
    list_locale_body_versions,
    locale_body_version_blocks,
    rebase_locale_body,
    restore_locale_body_version,
    save_locale_body,
    site_translation_overview,
)
from .localized_bodies import inline_marks
from .models import PageLocaleVersion
from .site_texts import SiteTexts, list_site_texts, publish_site_texts, save_site_texts
from .views import IDEMPOTENCY_PARAMETER

PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}


def _body(body: LocaleBody) -> dict[str, Any]:
    blocks = body.source_blocks()
    marks = inline_marks(blocks)
    return {
        "page_id": body.page.id,
        "locale": body.translation.locale,
        "source_version_id": body.source_version.id,
        "source_version": body.source_version.number,
        "outdated": body.outdated,
        "body_version": body.translation.body_version,
        "version": body.version.number if body.version is not None else None,
        "version_id": body.version.id if body.version is not None else None,
        # What the editor's banner says about this language beyond its text
        # (TL15): a translation waiting for a person's decision, and a version
        # a person took off the site.
        "pending": (
            {
                "version_id": pending.id,
                "number": pending.number,
                "reason": body.translation.pending_reason,
                "in_units": body.waiting,
                "metadata": [
                    {
                        "field": item.field,
                        "source_text": item.source_text,
                        "text": item.text,
                        "current_text": item.current_text,
                    }
                    for item in body.metadata
                ],
            }
            if (pending := body.translation.body_pending) is not None
            else None
        ),
        "withdrawn": body.translation.withdrawn_at is not None,
        # The version visitors read now; differing from `version_id` means
        # this language has changes that are not on the site yet.
        "live_version_id": _live_version_id(body),
        "untranslated": body.untranslated,
        # The source's sections in order, so the editor can name the section
        # a unit's key starts with (`2/…` is the third).
        "block_types": [str(block["block_type"]) for block in blocks],
        "units": [
            {
                "key": state.unit.key,
                "kind": state.unit.kind,
                "source_text": state.unit.text,
                "text": state.text,
                "origin": state.origin,
                "translated": state.translated,
                "suggestion": state.suggestion,
                "current_text": state.current_text,
                "data_class": state.unit.data_class,
                "placeholder": state.unit.placeholder,
                "max_length": state.unit.max_length,
                "required_text": state.unit.required,
                "marks": marks.get(state.unit.key, []),
            }
            for state in body.units
        ],
    }


def _live_version_id(body: LocaleBody) -> str | None:
    publication = body.page.site.current_publication
    if publication is None:
        return None
    for page in publication.snapshot.get("pages", []):
        if isinstance(page, dict) and page.get("page_id") == str(body.page.id):
            for entry in page.get("locales", []):
                if (
                    isinstance(entry, dict)
                    and entry.get("locale") == body.translation.locale
                    and "blocks" in entry
                    and not entry.get("withheld")
                ):
                    return str(entry.get("locale_version_id") or "") or None
    return None


def _version(version: PageLocaleVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "number": version.number,
        "source_version_id": version.source_version_id,
        "source_version": version.source_version.number,
        "origin": version.origin,
        "origin_ref": version.origin_ref,
        "created_at": version.created_at,
    }


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_retrieve",
        summary="Read a page body in another language",
        description="Every text unit of the source version this language follows, with this "
        "language's text, who wrote it and what is still untranslated (ADR-070). While a "
        "version waits for acceptance the units carry that version's text "
        "(`pending.in_units`), each beside what the language says now (`current_text`).",
        tags=["sites"],
        responses={200: LocaleBodySerializer, **PROBLEMS},
    )
    def get(self, _request: Request, page_id: UUID, locale: str) -> Response:
        return Response(_body(get_locale_body(page_id=page_id, locale=locale, waiting=True)))

    @extend_schema(
        operation_id="sites_page_locale_body_save",
        summary="Save text units of a page body in another language",
        description="Writes the named units as a person's text; structure comes from the "
        "source version. 400 `locale_unit_invalid` names every unit that does not fit as a "
        "field error `units.<key>` with its code (unknown_unit, required, too_long, "
        "token_missing, token_unexpected, token_malformed, token_nesting, token_empty, "
        "block_invalid). The page's own version does not move.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodySaveSerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def put(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodySaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_preview",
        summary="Check a save of text units without saving",
        description="The body as the save would leave it, or the same 400 and 409 the save "
        "would answer. Nothing is written.",
        tags=["sites"],
        request=LocaleBodySaveSerializer,
        responses={200: LocaleBodySerializer, **PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodySaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = save_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key="",
            preview=True,
        )
        return Response(_body(result.value))


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyCopyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_copy",
        summary="Start a manual translation from the source text",
        description="Fills every unit with no text yet with the source text. A copy stays "
        "untranslated until somebody changes it or saves it as it is.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodyCopySerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodyCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = copy_source_into_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class PageLocaleBodyVersionListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_versions_list",
        summary="History of a page body in another language",
        description="Every version of this language's body, newest first, with the source "
        "version it follows and how it came to be (save, copy, restore, rebase, a job).",
        tags=["sites"],
        responses={200: LocaleBodyVersionListSerializer, **PROBLEMS},
    )
    def get(self, _request: Request, page_id: UUID, locale: str) -> Response:
        versions = list_locale_body_versions(page_id=page_id, locale=locale)
        return Response({"items": [_version(version) for version in versions]})


class PageLocaleBodyVersionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_version_retrieve",
        summary="A past version of a page body in another language, as blocks",
        description="The blocks a visitor would have got from that version, assembled from "
        "the source version it is bound to; for a read-only preview.",
        tags=["sites"],
        responses={200: LocaleBodyVersionPreviewSerializer, **PROBLEMS},
    )
    def get(self, _request: Request, page_id: UUID, locale: str, version_id: UUID) -> Response:
        version, blocks = locale_body_version_blocks(
            page_id=page_id, locale=locale, version_id=version_id
        )
        return Response({"version": _version(version), "blocks": blocks})


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_version_restore",
        summary="Make a past version of a page body in another language current again",
        description="A new version with the old text and the old binding; a version bound to "
        "an older source must be moved onto the current one before it can be published.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodyRestoreSerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str, version_id: UUID) -> Response:
        serializer = LocaleBodyRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = restore_locale_body_version(
            page_id=page_id,
            locale=locale,
            version_id=version_id,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyRebaseView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_rebase",
        summary="Move a page body in another language onto the current source version",
        description="Unchanged source text keeps its translation wherever it moved, a sentence "
        "translated on another page of the site is reused, a changed unit starts "
        "untranslated with a person's old text as a suggestion. Already current: 200 and "
        "nothing changes.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBodyRebaseSerializer,
        responses={200: LocaleBodySerializer, 201: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodyRebaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = rebase_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            _body(result.value),
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleBodyRebasePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_body_rebase_preview",
        summary="See what moving onto the current source version would keep",
        description="The body as the move would leave it: carried, reused, untranslated and "
        "suggested units. Nothing is written.",
        tags=["sites"],
        extensions={"x-dry-run": True},
        request=LocaleBodyRebaseSerializer,
        responses={200: LocaleBodySerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleBodyRebaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = rebase_locale_body(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key="",
            preview=True,
        )
        return Response(_body(result.value))


class SiteTranslationOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_translation_overview",
        summary="Every page or article of a site against every other language",
        description="Pages: missing, pending, outdated, untranslated or complete per language, "
        "with the untranslated count, whether the version is on the site (`on_site`) and where "
        "(`path`). Articles: published, draft or missing per language. `kind=other`: the "
        "site's own texts, the company's cards and its booking catalogue, one row per object, "
        "in the page's states. `source_key` and `source_id` are what a translation order "
        "names; `review_id` is a result waiting in the cell that can be accepted. "
        "Filter by language and state; paginated by cursor.",
        tags=["sites"],
        parameters=[TranslationOverviewQuerySerializer],
        responses={200: TranslationOverviewSerializer, **PROBLEMS},
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        query = TranslationOverviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, next_cursor, locales = site_translation_overview(
            site_id=site_id, **query.validated_data
        )
        return Response({
            "locales": list(locales),
            "items": [
                {
                    "kind": row.kind,
                    "id": row.id,
                    "source_key": row.source_key,
                    "source_id": row.source_id,
                    "title": row.title,
                    "cells": [
                        {
                            "locale": cell.locale,
                            "state": cell.state,
                            "untranslated": cell.untranslated,
                            "metadata_complete": cell.metadata_complete,
                            "on_site": cell.on_site,
                            "path": cell.path,
                            "review_id": cell.review.id if cell.review else None,
                            "review_version": cell.review.version if cell.review else None,
                            "review_comparable": cell.review.comparable if cell.review else None,
                        }
                        for cell in row.cells
                    ],
                }
                for row in rows
            ],
            "next_cursor": next_cursor,
        })


def _decision(decision: LanguageDecision) -> dict[str, Any]:
    return {
        "page_id": decision.page.id,
        "locale": decision.translation.locale,
        "published": decision.publication is not None and decision.skipped is None,
        "publication_id": decision.publication.id if decision.publication else None,
        "skipped": decision.skipped,
    }


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_accept",
        summary="Accept a language version waiting for review",
        description="Makes the waiting version current and, if it may go out (ADR-070 pkt 6), "
        "publishes it as a derived publication of the published state — nobody's drafts go "
        "with it. A person's decision only.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleAcceptSerializer,
        responses={200: LanguageDecisionSerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = accept_locale_version(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(_decision(decision))


@method_decorator(csrf_protect, name="dispatch")
class PageLocaleRejectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_page_locale_reject",
        summary="Reject a language version waiting for review",
        description="Drops the waiting version; the current one and the site stay as they "
        "were. A person's decision only.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleAcceptSerializer,
        responses={200: LanguageDecisionSerializer, **PROBLEMS},
    )
    def post(self, request: Request, page_id: UUID, locale: str) -> Response:
        serializer = LocaleAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = reject_locale_version(
            page_id=page_id,
            locale=locale,
            **serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(_decision(decision))


def _single_decision_view(operation: str, action: Any, summary: str, description: str) -> Any:
    @method_decorator(csrf_protect, name="dispatch")
    class View(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(
            operation_id=f"sites_page_locale_{operation}",
            summary=summary,
            description=description,
            tags=["sites"],
            parameters=[IDEMPOTENCY_PARAMETER],
            request=None,
            responses={200: LanguageDecisionSerializer, **PROBLEMS},
        )
        def post(self, request: Request, page_id: UUID, locale: str) -> Response:
            return Response(
                _decision(
                    action(
                        page_id=page_id,
                        locale=locale,
                        idempotency_key=request.headers.get("Idempotency-Key", ""),
                    )
                )
            )

    @method_decorator(csrf_protect, name="dispatch")
    class Preview(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(
            operation_id=f"sites_page_locale_{operation}_preview",
            summary=f"{summary} — preview",
            description=f"{description} Nothing changes.",
            tags=["sites"],
            request=None,
            responses={200: LanguageDecisionSerializer, **PROBLEMS},
            extensions={"x-dry-run": True},
        )
        def post(self, _request: Request, page_id: UUID, locale: str) -> Response:
            return Response(
                _decision(action(page_id=page_id, locale=locale, idempotency_key="", preview=True))
            )

    View.__name__ = f"PageLocale{operation.title()}View"
    Preview.__name__ = f"PageLocale{operation.title()}PreviewView"
    return View, Preview


PageLocalePublishView, PageLocalePublishPreviewView = _single_decision_view(
    "publish",
    publish_locale_version,
    "Publish this language version",
    "Publishes the version's current body as a derived publication of the published "
    "state, if it may go out; otherwise answers why (`skipped`). A person's decision only.",
)
PageLocaleWithdrawView, PageLocaleWithdrawPreviewView = _single_decision_view(
    "withdraw",
    withdraw_locale_version,
    "Take this language version off the site",
    "Its address answers 308 to the page in the source language until it is published "
    "again. A person's decision only.",
)


@method_decorator(csrf_protect, name="dispatch")
class SiteLocaleBatchAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_translations_accept",
        summary="Accept several language versions in one publication",
        description="Accepts the listed waiting versions, home pages first, and publishes "
        "those that may go out in one derived publication. Send the digest of the preview "
        "for more than one item.",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=LocaleBatchAcceptSerializer,
        responses={200: LocaleBatchResultSerializer, **PROBLEMS},
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        return _batch(request, site_id, preview=False)


@method_decorator(csrf_protect, name="dispatch")
class SiteLocaleBatchAcceptPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_translations_accept_preview",
        summary="See what accepting several language versions would publish",
        description="What each listed version would do, and the digest to send back.",
        tags=["sites"],
        request=LocaleBatchAcceptSerializer,
        responses={200: LocaleBatchResultSerializer, **PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, site_id: UUID) -> Response:
        return _batch(request, site_id, preview=True)


def _batch(request: Request, site_id: UUID, *, preview: bool) -> Response:
    serializer = LocaleBatchAcceptSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    items = [
        (item["page_id"], item["locale"], item["expected_body_version"])
        for item in serializer.validated_data["items"]
    ]
    decisions = accept_locale_versions(
        items=items,
        digest=serializer.validated_data["digest"] or None,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        preview=preview,
        site_id=site_id,
    )
    return Response({
        "items": [_decision(decision) for decision in decisions],
        "digest": (
            batch_digest([(decision.page, decision.translation) for decision in decisions])
            if preview
            else None
        ),
    })


def _site_texts(texts: SiteTexts) -> dict[str, Any]:
    return {
        "site_id": str(texts.site.id),
        "locale": texts.locale,
        "version": texts.version,
        "items": [
            {
                "key": item.key,
                "role": item.role,
                "source_text": item.source_text,
                "text": item.text,
                "origin": item.origin,
                "state": item.state if item.state != "copied" else "missing",
                "pending_text": item.pending_text,
                "pending_reason": item.pending_reason,
            }
            for item in texts.items
        ],
    }


@method_decorator(csrf_protect, name="dispatch")
class SiteTextsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_site_texts_retrieve",
        summary="Read a site's own texts in another language",
        description="The tagline, the footer and its link labels, collection and tag names as "
        "the published site shows them, each with this language's translation (ADR-070 pkt 15).",
        tags=["sites"],
        responses={200: SiteTextsSerializer, **PROBLEMS},
    )
    def get(self, _request: Request, site_id: UUID, locale: str) -> Response:
        return Response(_site_texts(list_site_texts(site_id=site_id, locale=locale)))

    @extend_schema(
        operation_id="sites_site_texts_save",
        summary="Translate a site's own texts",
        description="Writes the named texts as a person's translation; they go out with the "
        "site's next publication or with `…/publish/`. 400 names an unknown key or a too long "
        "text as `texts.<key>`; 409 `site_texts_version_conflict` when another save came first.",
        tags=["sites"],
        request=SiteTextsSaveSerializer,
        responses={200: SiteTextsSerializer, **PROBLEMS},
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "Guarded by the version: a repeat answers 409 and changes "
                "nothing.",
            }
        },
    )
    def put(self, request: Request, site_id: UUID, locale: str) -> Response:
        serializer = SiteTextsSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        texts = save_site_texts(site_id=site_id, locale=locale, **serializer.validated_data)
        return Response(_site_texts(texts))


@method_decorator(csrf_protect, name="dispatch")
class SiteTextsPublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_site_texts_publish",
        summary="Publish a site's texts in one language",
        description="A derived publication of what is already public with this language's "
        "site texts as they are now — no draft goes with it. A person's decision "
        "(person_required).",
        tags=["sites"],
        parameters=[IDEMPOTENCY_PARAMETER],
        request=None,
        responses={200: SiteTextsPublicationSerializer, **PROBLEMS},
    )
    def post(self, request: Request, site_id: UUID, locale: str) -> Response:
        publication = publish_site_texts(
            site_id=site_id,
            locale=locale,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response({
            "site_id": str(site_id),
            "locale": locale,
            "publication_id": str(publication.id),
        })


class SitePublicationPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sites_publication_preview",
        summary="What publishing the site would carry in each other language",
        description="Read before publishing: per language whether visitors could read the "
        "site in it afterwards, and per page whether its version goes out, stays in its last "
        "published form, is withheld, taken off, skipped or missing — with the reason. The "
        "same verdict the publication uses; nothing is saved.",
        tags=["sites"],
        responses={
            200: PublicationPlanSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, site_id: UUID) -> Response:
        plan = preview_site_publication(site_id=site_id)
        return Response({
            "ready_to_publish": plan.ready_to_publish,
            "languages": [
                {
                    "locale": language.locale,
                    "live": language.live,
                    "live_after": language.live_after,
                    "pages": [
                        {
                            "page_id": page.page_id,
                            "page_name": page.page_name,
                            "outcome": page.outcome,
                            "reason": page.reason,
                        }
                        for page in language.pages
                    ],
                }
                for language in plan.languages
            ],
        })
