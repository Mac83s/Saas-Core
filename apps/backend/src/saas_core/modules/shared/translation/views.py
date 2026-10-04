"""`/api/v1/translation/` — operable by the AI assistant (ADR-069 pkt 28, ADR-076 pkt 7).

Every operation has an explicit id and description; every write a required
Idempotency-Key; every preview `x-dry-run`; validation errors are 400
ProblemDetails with `errors [{field, code, message}]`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException, ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from saas_core.http.exceptions import problem_details_exception_handler
from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .automation import demand_listing, list_demand
from .jobs import (
    TargetRequest,
    TranslationQuoteChanged,
    TranslationUnavailable,
    job_payload,
    list_jobs,
    order_translation,
    quote_payload,
    quote_translation,
)
from .review import (
    ReviewChoice,
    cancel_job,
    count_review,
    decide_review,
    job_detail,
    list_review,
    revert_job,
    review_detail,
    review_listing,
)
from .serializers import (
    DemandPageSerializer,
    DemandQuerySerializer,
    GlossaryDeleteQuerySerializer,
    GlossaryPageSerializer,
    GlossaryQuerySerializer,
    GlossaryTermInputSerializer,
    GlossaryTermPreviewSerializer,
    GlossaryTermSerializer,
    GlossaryTermUpdateSerializer,
    JobDetailQuerySerializer,
    JobDetailSerializer,
    JobPageSerializer,
    JobQuerySerializer,
    JobSerializer,
    OrderRequestSerializer,
    QuoteRequestSerializer,
    QuoteSerializer,
    ReviewDecisionResultSerializer,
    ReviewDecisionSerializer,
    ReviewDetailSerializer,
    ReviewPageSerializer,
    ReviewQuerySerializer,
    TranslationOfferSerializer,
    TranslationSettingsPreviewSerializer,
    TranslationSettingsSerializer,
    TranslationSettingsUpdateSerializer,
)
from .services import (
    change_settings,
    create_glossary_term,
    delete_glossary_term,
    list_glossary,
    read_settings,
    translation_offer,
    update_glossary_term,
)

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
_PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
}
_PREVIEW = {"x-dry-run": True}
_PREVIEW_NOTE = (
    " Nothing is saved: the answer is what the write would leave, with `changes`, or the same "
    "400, 403, 404 and 409 the write would answer."
)
_WRITE_NOTE = (
    " A repeated Idempotency-Key answers the first result again; the key reused on another "
    "request is 409 `translation_idempotency_conflict`. `expected_version` is the version the "
    "change was made on; another one is 409 `translation_version_conflict`."
)


def _idem(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 160:
        raise ParseError("Wymagany jest prawidłowy Idempotency-Key.")
    return value


class TranslationOfferView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_offer_retrieve",
        summary="What translation the company can order now",
        description="Whether a translation can be ordered now and why not, the effective "
        "publication mode with its source, the automation's state, the price unit and every "
        "translation setting with its variants, bounds, defaults and pl/en labels.",
        tags=["translation"],
        responses={200: TranslationOfferSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        return Response(TranslationOfferSerializer(translation_offer()).data)


def _settings_input(request: Request) -> tuple[dict[str, Any], list[str], int]:
    serializer = TranslationSettingsUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return (
        serializer.changes(),
        list(serializer.validated_data.get("reset") or ()),
        serializer.validated_data["expected_version"],
    )


@method_decorator(csrf_protect, name="dispatch")
class TranslationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_settings_retrieve",
        summary="The company's translation settings",
        description="Each setting with the company's own value (null: inherited), the value "
        "in force, its source and the operator's lock with the reason; the version token; who "
        "consented to the automation and whether content processing was acknowledged.",
        tags=["translation"],
        responses={200: TranslationSettingsSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        return Response(TranslationSettingsSerializer(read_settings()).data)

    @extend_schema(
        operation_id="translation_settings_update",
        summary="Change the company's translation settings",
        description="Changes the publication mode, the automation and its monthly limit. An "
        "absent or null field stays as it is; `reset` takes keys back to the inherited value. "
        "Turning the automation on, and acknowledging processing, is the consent of the person "
        "sending it and is refused to API keys and to the assistant on its own; "
        "`auto_changes: true` sent while the automation runs on another person's consent makes "
        "the sender that person." + _WRITE_NOTE,
        tags=["translation"],
        parameters=[IDEMPOTENCY],
        request=TranslationSettingsUpdateSerializer,
        responses={200: TranslationSettingsSerializer, **_PROBLEMS},
    )
    def patch(self, request: Request) -> Response:
        changes, reset, version = _settings_input(request)
        saved = change_settings(
            changes=changes,
            reset=reset,
            expected_version=version,
            idempotency_key=_idem(request),
        )
        return Response(TranslationSettingsSerializer(saved.value).data)


@method_decorator(csrf_protect, name="dispatch")
class TranslationSettingsPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_settings_preview",
        summary="Check a settings change without saving it",
        description="Validates a change as `translation_settings_update` would." + _PREVIEW_NOTE,
        tags=["translation"],
        request=TranslationSettingsUpdateSerializer,
        responses={200: TranslationSettingsPreviewSerializer, **_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        changes, reset, version = _settings_input(request)
        saved = change_settings(
            changes=changes, reset=reset, expected_version=version, preview=True
        )
        return Response(
            TranslationSettingsPreviewSerializer({**saved.value, "changes": saved.changes}).data
        )


@method_decorator(csrf_protect, name="dispatch")
class GlossaryListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_glossary_list",
        summary="The company's glossary",
        description="Terms a translation keeps or renders the company's way, ordered by "
        "language and term, paged by `cursor`.",
        tags=["translation"],
        parameters=[GlossaryQuerySerializer],
        responses={
            200: GlossaryPageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = GlossaryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items, next_cursor, count = list_glossary(
            cursor=query.validated_data.get("cursor"), limit=query.validated_data["limit"]
        )
        return Response({
            "items": GlossaryTermSerializer(items, many=True).data,
            "count": count,
            "next_cursor": next_cursor,
        })

    @extend_schema(
        operation_id="translation_glossary_create",
        summary="Add a glossary term",
        description="Adds a term: one line of at most 120 characters, no tokens, up to 10 "
        "inflected forms; a company has at most 500. Terms are data for the model, never "
        "instructions." + _WRITE_NOTE,
        tags=["translation"],
        parameters=[IDEMPOTENCY],
        request=GlossaryTermInputSerializer,
        responses={201: GlossaryTermSerializer, **_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        serializer = GlossaryTermInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = create_glossary_term(
            data=dict(serializer.validated_data), idempotency_key=_idem(request)
        )
        return Response(GlossaryTermSerializer(saved.value).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class GlossaryCreatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_glossary_create_preview",
        summary="Check a new glossary term without adding it",
        description="Validates a term as `translation_glossary_create` would." + _PREVIEW_NOTE,
        tags=["translation"],
        request=GlossaryTermInputSerializer,
        responses={200: GlossaryTermPreviewSerializer, **_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request) -> Response:
        serializer = GlossaryTermInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved = create_glossary_term(data=dict(serializer.validated_data), preview=True)
        return Response({**GlossaryTermSerializer(saved.value).data, "changes": saved.changes})


def _term_update(request: Request) -> tuple[dict[str, Any], int]:
    serializer = GlossaryTermUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    return data, data.pop("expected_version")


@method_decorator(csrf_protect, name="dispatch")
class GlossaryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_glossary_update",
        summary="Change a glossary term",
        description="Changes the fields sent; null leaves a field as it is." + _WRITE_NOTE,
        tags=["translation"],
        parameters=[IDEMPOTENCY],
        request=GlossaryTermUpdateSerializer,
        responses={200: GlossaryTermSerializer, **_PROBLEMS},
    )
    def patch(self, request: Request, term_id: UUID) -> Response:
        data, version = _term_update(request)
        saved = update_glossary_term(
            term_id=term_id, data=data, expected_version=version, idempotency_key=_idem(request)
        )
        return Response(GlossaryTermSerializer(saved.value).data)

    @extend_schema(
        operation_id="translation_glossary_delete",
        summary="Remove a glossary term",
        description="Removes the term at the version given in `expected_version`." + _WRITE_NOTE,
        tags=["translation"],
        parameters=[IDEMPOTENCY, GlossaryDeleteQuerySerializer],
        responses={204: None, **_PROBLEMS},
    )
    def delete(self, request: Request, term_id: UUID) -> Response:
        query = GlossaryDeleteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        delete_glossary_term(
            term_id=term_id,
            expected_version=query.validated_data["expected_version"],
            idempotency_key=_idem(request),
        )
        return Response(status=204)


@method_decorator(csrf_protect, name="dispatch")
class GlossaryUpdatePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_glossary_update_preview",
        summary="Check a change to a glossary term without saving it",
        description="Validates a change as `translation_glossary_update` would." + _PREVIEW_NOTE,
        tags=["translation"],
        request=GlossaryTermUpdateSerializer,
        responses={200: GlossaryTermPreviewSerializer, **_PROBLEMS},
        extensions=_PREVIEW,
    )
    def post(self, request: Request, term_id: UUID) -> Response:
        data, version = _term_update(request)
        saved = update_glossary_term(
            term_id=term_id, data=data, expected_version=version, preview=True
        )
        return Response({**GlossaryTermSerializer(saved.value).data, "changes": saved.changes})


def _targets(data: dict[str, Any]) -> list[TargetRequest]:
    return [TargetRequest(**target) for target in data["targets"]]


def _problem(request: Request, error: APIException, **extra: Any) -> Response:
    response = problem_details_exception_handler(error, {"request": request})
    assert response is not None
    response.data.update(extra)
    return response


@method_decorator(csrf_protect, name="dispatch")
class QuoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_quote_create",
        summary="Quote a translation",
        description="Counts what would be translated for each (object, language), what it "
        "costs, what would wait for a person and why, and seals it in a digest an order must "
        "carry. Nothing is saved; the same content gives the same digest.",
        tags=["translation"],
        request=QuoteRequestSerializer,
        responses={
            200: QuoteSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "A calculation: nothing is saved, a repeat answers the same.",
            }
        },
    )
    def post(self, request: Request) -> Response:
        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = quote_translation(
            targets=_targets(data),
            protected=data["protected"],
            include_unverified=data["include_unverified"],
        )
        return Response(QuoteSerializer(quote_payload(result)).data)


@method_decorator(csrf_protect, name="dispatch")
class JobListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_job_list",
        summary="Translation jobs",
        description="The company's translation jobs, newest first, paged by `cursor`. "
        "`active=true` keeps the jobs still queued or running — a screen follows those; "
        "`active=false` keeps the ones that ended.",
        tags=["translation"],
        parameters=[JobQuerySerializer],
        responses={
            200: JobPageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = JobQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        jobs, next_cursor = list_jobs(
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
            active=query.validated_data.get("active"),
        )
        return Response({"items": [job_payload(job) for job in jobs], "next_cursor": next_cursor})

    @extend_schema(
        operation_id="translation_job_create",
        summary="Order a translation",
        description="Orders the quote with this digest at the credits it showed, as the person "
        "sending it. A changed quote is 409 `translation_quote_changed` with the new quote in "
        "`quote`; a changed price is 409 `credit_price_changed`; translation that cannot run now "
        "is 503 `translation_unavailable` with `reasons`. A repeated Idempotency-Key answers the "
        "first job again.",
        tags=["translation"],
        parameters=[IDEMPOTENCY],
        request=OrderRequestSerializer,
        responses={
            201: JobSerializer,
            **_PROBLEMS,
            402: ProblemDetailsSerializer,
            503: ProblemDetailsSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = OrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            saved = order_translation(
                targets=_targets(data),
                digest=data["digest"],
                expected_credits=data["expected_credits"],
                protected=data["protected"],
                include_unverified=data["include_unverified"],
                idempotency_key=_idem(request),
            )
        except TranslationQuoteChanged as changed:
            return _problem(
                request, changed, quote=QuoteSerializer(quote_payload(changed.quote)).data
            )
        except TranslationUnavailable as unavailable:
            return _problem(request, unavailable, reasons=unavailable.reasons)
        return Response(JobSerializer(job_payload(saved.value)).data, status=201)


class JobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_job_retrieve",
        summary="A translation job",
        description="The job with its parts (credits held and settled) and items (object × "
        "language, state, delivered characters and what the source answered), and whether it "
        "can still be taken back. `labels=true` names every item as its source lists it.",
        tags=["translation"],
        parameters=[JobDetailQuerySerializer],
        responses={
            200: JobDetailSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request, job_id: UUID) -> Response:
        query = JobDetailQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        detail = job_detail(job_id, labels=query.validated_data["labels"])
        return Response(JobDetailSerializer(detail).data)


class DemandListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_demand_list",
        summary="What the automation still has to translate",
        description="Changes of public content the automatic translation of changes has not "
        "started yet, soonest first, paged by `cursor`: those waiting out their quiet time "
        "(`waiting`) and those the automation is held on (`blocked`), each with the reason and "
        "when it is tried again. Each is named as its source lists it. `count` is everything "
        "in the asked state. Empty while the automation is off: nothing is recorded then.",
        tags=["translation"],
        parameters=[DemandQuerySerializer],
        responses={
            200: DemandPageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = DemandQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, next_cursor, count = list_demand(
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
            state=query.validated_data.get("state"),
        )
        return Response(
            DemandPageSerializer({
                "items": demand_listing(rows),
                "count": count,
                "next_cursor": next_cursor,
            }).data
        )


def _choices(request: Request) -> list[ReviewChoice]:
    serializer = ReviewDecisionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return [
        ReviewChoice(id=item["id"], version=item["version"])
        for item in serializer.validated_data["items"]
    ]


class ReviewListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_review_list",
        summary="Translations waiting for a person",
        description="Results that wait, with why: a legal document, review mode, a person's "
        "text they would replace, the first appearance of a language, a soft-check flag — "
        "and those the checks refused, to translate by hand. Each is named as its source lists "
        "it. Oldest first, paged by `cursor`; `count` is everything that waits.",
        tags=["translation"],
        parameters=[ReviewQuerySerializer],
        responses={
            200: ReviewPageSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = ReviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, next_cursor = list_review(
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
            reason=query.validated_data.get("reason"),
        )
        return Response({
            "items": review_listing(rows),
            "count": count_review(reason=query.validated_data.get("reason")),
            "next_cursor": next_cursor,
        })


class ReviewDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_review_retrieve",
        summary="A translation waiting for a person, text beside text",
        description="One waiting result with, for each unit, the source text, what stands in "
        "the language now and what accepting would write. The texts are kept here for a live "
        "record only (a card, the booking catalogue); a versioned source (a page, an article) "
        "answers `comparable: false` with no units and shows its waiting text in its own "
        "editor. `fits: false` means the source or the translation moved since and an "
        "acceptance would answer 409. An item already decided or replaced is 404; a source "
        "the person may not read is 403.",
        tags=["translation"],
        responses={
            200: ReviewDetailSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, review_id: UUID) -> Response:
        return Response(ReviewDetailSerializer(review_detail(review_id)).data)


def _decision_view(action: str, operation_id: str, summary: str, description: str) -> type[APIView]:
    @method_decorator(csrf_protect, name="dispatch")
    class DecisionView(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(
            operation_id=operation_id,
            summary=summary,
            description=description
            + " A person's decision: a job or the assistant without a consent click is 403 "
            "`person_required`. An item decided meanwhile or at another version is 409 "
            "`translation_review_changed`. A repeated Idempotency-Key answers the first result.",
            tags=["translation"],
            parameters=[IDEMPOTENCY],
            request=ReviewDecisionSerializer,
            responses={200: ReviewDecisionResultSerializer, **_PROBLEMS},
        )
        def post(self, request: Request) -> Response:
            saved = decide_review(
                action=action, choices=_choices(request), idempotency_key=_idem(request)
            )
            return Response(ReviewDecisionResultSerializer({"items": saved.value}).data)

    DecisionView.__name__ = f"Review{action.title()}View"
    return DecisionView


ReviewAcceptView = _decision_view(
    "accept",
    "translation_review_accept",
    "Accept waiting translations",
    "Publishes the chosen results the way their source publishes: one derived publication "
    "for a site's pages, a write for a live record.",
)
ReviewDiscardView = _decision_view(
    "discard",
    "translation_review_discard",
    "Discard waiting translations",
    "Drops the chosen results; what is public stays as it is. A discarded result is billed "
    "like a delivered one (ADR-069 pkt 24).",
)


@method_decorator(csrf_protect, name="dispatch")
class JobRevertView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_job_revert",
        summary="Take back a translation job",
        description="Returns every source the job wrote to its texts from before it, through "
        "one derived publication each. Credits are not returned. Only the newest job that "
        "wrote anything, once it has ended (`revertable` in the job's detail): 400 with "
        "`job_running`, `not_latest_job` or `already_reverted` on `job_id` otherwise. A "
        "person's decision: 403 `person_required` otherwise.",
        tags=["translation"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: JobSerializer, **_PROBLEMS},
    )
    def post(self, request: Request, job_id: UUID) -> Response:
        saved = revert_job(job_id=job_id, idempotency_key=_idem(request))
        return Response(JobSerializer(job_payload(saved.value)).data)


@method_decorator(csrf_protect, name="dispatch")
class JobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="translation_job_cancel",
        summary="Stop a translation job",
        description="Stops sending: items not started are cancelled, items in flight finish, "
        "what was delivered is settled and the rest of the held credits are released.",
        tags=["translation"],
        parameters=[IDEMPOTENCY],
        request=None,
        responses={200: JobSerializer, **_PROBLEMS},
    )
    def post(self, request: Request, job_id: UUID) -> Response:
        saved = cancel_job(job_id=job_id, idempotency_key=_idem(request))
        return Response(JobSerializer(job_payload(saved.value)).data)
