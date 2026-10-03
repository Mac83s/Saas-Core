from typing import Any, cast

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .documents import (
    add_text,
    approve_draft,
    list_documents,
    public_document,
    read_document,
    save_draft,
)
from .models import DocumentRoute
from .security import public_documents_context
from .serializers import (
    CustomerDocumentApprovalSerializer,
    CustomerDocumentApproveInputSerializer,
    CustomerDocumentDetailSerializer,
    CustomerDocumentDraftInputSerializer,
    CustomerDocumentListSerializer,
    CustomerDocumentSerializer,
    CustomerDocumentTextInputSerializer,
    PublicCustomerDocumentSerializer,
)

_VERSION_LOCKED = {
    "x-quality-exempt": {
        "idempotency-key": "Locked by version: a repeat at the same version answers 409 "
        "and changes nothing.",
    }
}
_TAGS = ["customers"]


class DocumentListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="customers_documents_list",
        summary="The company's documents for its customers",
        description="Every kind of document — booking terms, shop terms, privacy policy, "
        "cancellation policy — with its draft, the version in force today and one approved "
        "for later, plus what a caller may choose from: the company's content languages and "
        "the longest text.",
        tags=_TAGS,
        responses={200: CustomerDocumentListSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        return Response(list_documents())


class DocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="customers_document_read",
        summary="One document with its versions and texts",
        description="The draft, every approved version (newest first) and, for the version "
        "in force and the upcoming one, the current text in each language; with what a "
        "caller may choose from, as in the list.",
        tags=_TAGS,
        responses={
            200: CustomerDocumentDetailSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, kind: str) -> Response:
        return Response(read_document(kind))


@method_decorator(csrf_protect, name="dispatch")
class DocumentDraftView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="customers_document_draft_save",
        summary="Write a document's draft",
        description="Saves the text somebody is still working on, in one content language "
        "of the company; an empty text clears it. A draft binds nobody: customers keep "
        "reading the version in force until a person approves the draft.",
        tags=_TAGS,
        request=CustomerDocumentDraftInputSerializer,
        responses={
            200: CustomerDocumentSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
        extensions=_VERSION_LOCKED,
    )
    def put(self, request: Request, kind: str) -> Response:
        serializer = CustomerDocumentDraftInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(save_draft(kind, **cast(dict[str, Any], serializer.validated_data)))


class DocumentApprovePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="customers_document_approve_preview",
        summary="What approving the draft would do",
        description="Checks the draft exactly as the approval does and says which version "
        "number it gets, from which day, and in which of the company's languages customers "
        "will get no document until somebody adds that text. Writes nothing.",
        tags=_TAGS,
        request=CustomerDocumentApproveInputSerializer,
        responses={
            200: CustomerDocumentApprovalSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request, kind: str) -> Response:
        serializer = CustomerDocumentApproveInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            approve_draft(kind, preview=True, **cast(dict[str, Any], serializer.validated_data))
        )


@method_decorator(csrf_protect, name="dispatch")
class DocumentApproveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="customers_document_approve",
        summary="Approve the draft as the next version",
        description="Makes the draft an append-only version in force from a day. Only a "
        "person may do it, after a fresh code from the authenticator app: 403 "
        "`person_required` for an automation, 403 `step_up_required` without the code "
        "(POST /api/v1/auth/step-up/, then repeat), `step_up_mfa_setup_required` for an "
        "account without two-factor sign-in.",
        tags=_TAGS,
        request=CustomerDocumentApproveInputSerializer,
        responses={
            200: CustomerDocumentApprovalSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
        extensions=_VERSION_LOCKED,
    )
    def post(self, request: Request, kind: str) -> Response:
        serializer = CustomerDocumentApproveInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(approve_draft(kind, **cast(dict[str, Any], serializer.validated_data)))


@method_decorator(csrf_protect, name="dispatch")
class DocumentTextView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="customers_document_text_add",
        summary="Add a version's text in a language",
        description="Appends the text of an approved version in another content language "
        "of the company, or a correction of a text it already has. Always a new row: what "
        "customers agreed to stays as it was. The same gate as the approval — a person, "
        "after a fresh code from the authenticator app.",
        tags=_TAGS,
        request=CustomerDocumentTextInputSerializer,
        responses={
            200: CustomerDocumentSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
            409: ProblemDetailsSerializer,
        },
        extensions=_VERSION_LOCKED,
    )
    def post(self, request: Request, kind: str) -> Response:
        serializer = CustomerDocumentTextInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(add_text(kind, **cast(dict[str, Any], serializer.validated_data)))


class PublicDocumentThrottle(AnonRateThrottle):
    scope = "customers_public_document"


class PublicDocumentView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicDocumentThrottle]

    @extend_schema(
        operation_id="public_customer_document",
        summary="A company's document, as anybody may read it",
        description="The version in force today behind a document's public address. With "
        "`locale` the text comes in that language when the version has it, otherwise in "
        "the language the version was approved in; `locale` in the answer says which.",
        tags=["public-customers"],
        parameters=[
            OpenApiParameter(
                "locale",
                str,
                OpenApiParameter.QUERY,
                description="A language code, e.g. de.",
            )
        ],
        responses={200: PublicCustomerDocumentSerializer, 404: ProblemDetailsSerializer},
        extensions={
            "x-quality-exempt": {
                "error-400": "A language the version has no text in is answered in its own.",
            }
        },
    )
    def get(self, request: Request, public_id: str) -> Response:
        route = DocumentRoute.objects.filter(public_id=public_id).first()
        if route is None:
            raise NotFound("Dokument nie istnieje.")
        with public_documents_context(route.organization_id):
            document = public_document(public_id, request.query_params.get("locale") or None)
        if document is None:
            raise NotFound("Dokument nie istnieje.")
        return Response(document)
