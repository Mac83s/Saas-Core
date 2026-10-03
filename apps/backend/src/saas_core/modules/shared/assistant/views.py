"""`/api/v1/assistant/` — the person's conversations with the assistant (ADR-076, A3).

A message is taken and answered later: `assistant_turn_create` queues the turn
and the conversation is read again until the turn is `done`, `failed` or
`awaiting_consent`. A turn that waits lists the consent groups of its plan;
each is shown and agreed to through
`/api/v1/organizations/current/command-consents/{digest}/`, and the tokens come
back here.

`profile/` is the company's profile (A2): what the owner said about the
company, read and changed here so it is never something only a conversation
can reach.
"""

from __future__ import annotations

from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from saas_core.modules.core.identity.serializers import ProblemDetailsSerializer

from .profile import ProfileState, read_profile, save_profile
from .profile_schema import SCHEMA_ID
from .serializers import (
    AssistantConsentAnswerSerializer,
    AssistantConversationListQuerySerializer,
    AssistantConversationListSerializer,
    AssistantConversationSerializer,
    AssistantConversationStartSerializer,
    AssistantConversationSummarySerializer,
    AssistantOfferSerializer,
    AssistantProfileChangeSerializer,
    AssistantProfileSavedSerializer,
    AssistantProfileSerializer,
    AssistantSetupSerializer,
    AssistantTurnAcceptedSerializer,
    AssistantTurnInputSerializer,
)
from .services import (
    add_turn,
    answer_consent,
    assistant_offer,
    get_conversation,
    list_conversations,
    setup_overview,
    start_conversation,
)

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
_PROBLEMS = {
    400: ProblemDetailsSerializer,
    403: ProblemDetailsSerializer,
    404: ProblemDetailsSerializer,
    409: ProblemDetailsSerializer,
    429: ProblemDetailsSerializer,
    503: ProblemDetailsSerializer,
}
_REPEAT_NOTE = " A repeated Idempotency-Key answers the first result again."


def _idem(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 160:
        raise ParseError("Wymagany jest prawidłowy Idempotency-Key.")
    return value


class AssistantOfferView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_offer_retrieve",
        summary="Whether the assistant can be talked to now",
        description="Whether a message would be taken now and why not: the model port's "
        "state, a worker for the `ai` queue, the deployment's daily ceiling and the "
        "company's plan; and what one answered message costs in credits.",
        tags=["assistant"],
        responses={200: AssistantOfferSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        return Response(AssistantOfferSerializer(assistant_offer()).data)


@method_decorator(csrf_protect, name="dispatch")
class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_conversation_list",
        summary="The person's conversations with the assistant",
        description="The signed-in person's own conversations in this company, newest "
        "first. Nobody else's are ever listed.",
        tags=["assistant"],
        parameters=[AssistantConversationListQuerySerializer],
        responses={
            200: AssistantConversationListSerializer,
            400: ProblemDetailsSerializer,
            403: ProblemDetailsSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        query = AssistantConversationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        items = list_conversations(limit=query.validated_data["limit"])
        return Response({"items": AssistantConversationSummarySerializer(items, many=True).data})

    @extend_schema(
        operation_id="assistant_conversation_create",
        summary="Start a conversation with the assistant",
        description="Opens an empty conversation of the signed-in person. Refused with "
        "503 `assistant_unavailable` while the chat is closed (see the offer), 403 "
        "`assistant_not_in_plan` without the plan feature and 429 above the limit of new "
        "conversations per address. A `setup` conversation is opened by whoever manages "
        "the company's settings." + _REPEAT_NOTE,
        tags=["assistant"],
        parameters=[IDEMPOTENCY],
        request=AssistantConversationStartSerializer,
        responses={201: AssistantConversationSummarySerializer, **_PROBLEMS},
    )
    def post(self, request: Request) -> Response:
        serializer = AssistantConversationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = start_conversation(
            language=serializer.validated_data["language"],
            kind=serializer.validated_data["kind"],
            idempotency_key=_idem(request),
            address=BaseThrottle().get_ident(request),
        )
        return Response(AssistantConversationSummarySerializer(conversation).data, status=201)


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_conversation_retrieve",
        summary="A conversation with everything the assistant wrote and did",
        description="The conversation's turns in order: the person's message, what the "
        "assistant wrote, each step it took with its status — only `done` means it "
        "happened — and, for a turn in `awaiting_consent`, the consent groups to show. "
        "Read it again until the last turn is `done`, `failed` or `awaiting_consent`.",
        tags=["assistant"],
        responses={
            200: AssistantConversationSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, conversation_id: UUID) -> Response:
        return Response(AssistantConversationSerializer(get_conversation(conversation_id)).data)


@method_decorator(csrf_protect, name="dispatch")
class TurnCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_turn_create",
        summary="Send the assistant a message",
        description="Takes the person's message and queues the assistant's turn; the "
        "answer arrives in the conversation. One turn at a time: 409 "
        "`assistant_turn_in_progress` while the previous one runs or waits for consent. A "
        "turn holds the credits of one message and spends them only when it is answered; a "
        "message in a `setup` conversation is free and counts against the setup budgets "
        "instead (429 `assistant_setup_budget`, `assistant_setup_daily_budget`: what was "
        "settled stays in the company profile and the setup is finished in the panel)."
        + _REPEAT_NOTE,
        tags=["assistant"],
        parameters=[IDEMPOTENCY],
        request=AssistantTurnInputSerializer,
        responses={202: AssistantTurnAcceptedSerializer, **_PROBLEMS},
    )
    def post(self, request: Request, conversation_id: UUID) -> Response:
        serializer = AssistantTurnInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        turn = add_turn(
            conversation_id=conversation_id,
            text=serializer.validated_data["text"],
            idempotency_key=_idem(request),
        )
        return Response(AssistantTurnAcceptedSerializer(turn).data, status=202)


@method_decorator(csrf_protect, name="dispatch")
class TurnConsentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_turn_consent_create",
        summary="Answer the plan a turn waits with",
        description="Runs the groups of the plan the person agreed to — each with the "
        "token its click minted — or, with `declined`, closes the plan with nothing run. "
        "The assistant then reports from the steps' results. A group without a token does "
        "not run; a stale or foreign token refuses its group. 409 "
        "`assistant_consent_not_awaited` when the turn waits for nothing.",
        tags=["assistant"],
        request=AssistantConsentAnswerSerializer,
        responses={202: AssistantTurnAcceptedSerializer, **_PROBLEMS},
        extensions={
            "x-quality-exempt": {
                "idempotency-key": "A plan runs once: its steps answer from their receipts "
                "on a repeat, and a second answer to a turn that no longer waits is 409.",
            }
        },
    )
    def post(self, request: Request, conversation_id: UUID, turn_id: UUID) -> Response:
        serializer = AssistantConsentAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        turn = answer_consent(
            conversation_id=conversation_id,
            turn_id=turn_id,
            consents=serializer.validated_data["consents"],
            declined=serializer.validated_data["declined"],
        )
        return Response(AssistantTurnAcceptedSerializer(turn).data, status=202)


class SetupView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_conversation_setup_retrieve",
        summary="Where the company's setup stands",
        description="For a `setup` conversation of the signed-in person: what the assistant "
        "knows about the company and from whom, and what follows from it now — the "
        "questions still to ask, the steps ready to run, the steps that wait and what the "
        "product cannot do yet. The same answer the conversation itself works from. A "
        "read: nothing is saved and nothing is run. 404 for a conversation of another kind.",
        tags=["assistant"],
        responses={
            200: AssistantSetupSerializer,
            403: ProblemDetailsSerializer,
            404: ProblemDetailsSerializer,
        },
    )
    def get(self, _request: Request, conversation_id: UUID) -> Response:
        return Response(AssistantSetupSerializer(setup_overview(conversation_id)).data)


def _profile(state: ProfileState) -> dict[str, object]:
    return {
        "schema": SCHEMA_ID,
        "version": state.version,
        "document": state.document,
        "updated_at": state.updated_at,
        "changed": list(state.changed),
    }


@method_decorator(csrf_protect, name="dispatch")
class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_profile_retrieve",
        summary="The company's profile, as the assistant keeps it",
        description="What the owner told the assistant about the company: who it is, what "
        "it sells, where and who works, each value with its origin and whether the owner "
        "confirmed it. Version 0 and an empty document while nothing was saved. Read by "
        "whoever manages the company's settings.",
        tags=["assistant"],
        responses={200: AssistantProfileSerializer, 403: ProblemDetailsSerializer},
    )
    def get(self, _request: Request) -> Response:
        return Response(AssistantProfileSerializer(_profile(read_profile())).data)

    @extend_schema(
        operation_id="assistant_profile_update",
        summary="Change the company's profile",
        description="Applies a JSON merge patch to the profile and saves it as its next "
        "version. Nothing in the account changes: the profile is what was said, not what "
        "was set up. 409 `assistant_profile_version_conflict` when the profile moved since "
        "`expected_version`; 400 names each field that is not a profile's." + _REPEAT_NOTE,
        tags=["assistant"],
        parameters=[IDEMPOTENCY],
        request=AssistantProfileChangeSerializer,
        responses={200: AssistantProfileSavedSerializer, **_PROBLEMS},
    )
    def patch(self, request: Request) -> Response:
        serializer = AssistantProfileChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state = save_profile(**serializer.validated_data, idempotency_key=_idem(request))
        return Response(AssistantProfileSavedSerializer(_profile(state)).data)


@method_decorator(csrf_protect, name="dispatch")
class ProfilePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="assistant_profile_update_preview",
        summary="Check a change to the profile without saving it",
        description="Validates the change as `assistant_profile_update` would. Nothing is "
        "saved: the answer is the profile as the save would leave it, with `changed`, or "
        "the same 400 and 409 the save would answer.",
        tags=["assistant"],
        request=AssistantProfileChangeSerializer,
        responses={200: AssistantProfileSavedSerializer, **_PROBLEMS},
        extensions={"x-dry-run": True},
    )
    def post(self, request: Request) -> Response:
        serializer = AssistantProfileChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state = save_profile(**serializer.validated_data, preview=True)
        return Response(AssistantProfileSavedSerializer(_profile(state)).data)
