"""`/api/v1/assistant/` — the person's conversations with the assistant (ADR-076, A3).

A message is taken and answered later: `assistant_turn_create` queues the turn
and the conversation is read again until the turn is `done`, `failed` or
`awaiting_consent`. A turn that waits lists the consent groups of its plan;
each is shown and agreed to through
`/api/v1/organizations/current/command-consents/{digest}/`, and the tokens come
back here.
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

from .serializers import (
    AssistantConsentAnswerSerializer,
    AssistantConversationListQuerySerializer,
    AssistantConversationListSerializer,
    AssistantConversationSerializer,
    AssistantConversationStartSerializer,
    AssistantConversationSummarySerializer,
    AssistantOfferSerializer,
    AssistantTurnAcceptedSerializer,
    AssistantTurnInputSerializer,
)
from .services import (
    add_turn,
    answer_consent,
    assistant_offer,
    get_conversation,
    list_conversations,
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
        "conversations per address." + _REPEAT_NOTE,
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
        "turn holds the credits of one message and spends them only when it is answered."
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
