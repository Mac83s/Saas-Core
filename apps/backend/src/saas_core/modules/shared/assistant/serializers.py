from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.serializers import LocalizedTextSerializer

from .models import ConversationKind, TurnState
from .services import MAX_MESSAGE_CHARACTERS


class AssistantSetupOfferSerializer(serializers.Serializer[Any]):
    allowed = serializers.BooleanField(
        help_text="Whether this person may set the company up: they manage its settings."
    )
    turns_left = serializers.IntegerField(
        min_value=0, help_text="Free setup messages the company has left."
    )
    turns_left_today = serializers.IntegerField(
        min_value=0, help_text="Free setup messages this person has left today (UTC)."
    )


class AssistantOfferSerializer(serializers.Serializer[Any]):
    available = serializers.BooleanField(
        help_text="Whether a message would be taken now. False: `reasons` say why."
    )
    reasons = serializers.ListField(
        child=serializers.CharField(),
        help_text="Why the chat is closed: `model_not_selected` and the model port's other "
        "reasons, `worker_unavailable`, `daily_ceiling`, `feature_disabled`.",
    )
    in_plan = serializers.BooleanField(
        help_text="Whether the company's plan has `assistant.text.enabled`."
    )
    credits_per_message = serializers.IntegerField(
        min_value=0, help_text="Credits one answered message costs; 0 while it is not metered."
    )
    max_message_characters = serializers.IntegerField(min_value=1)
    setup = AssistantSetupOfferSerializer(
        help_text="The conversation that sets the company up: free, within these budgets."
    )


_KIND_HELP = (
    "`operate`: the assistant works with the company's commands, a credit per answered "
    "message. `setup`: it sets the company up — notes what the owner says into the company "
    "profile and offers the plan worked out from it; free, within the setup budgets."
)


class AssistantConversationStartSerializer(serializers.Serializer[Any]):
    language = serializers.ChoiceField(
        choices=("pl", "en"),
        help_text="The panel's language: previews and refusals are shown in it. The "
        "assistant itself answers in the language the person writes in.",
    )
    kind = serializers.ChoiceField(
        choices=ConversationKind.choices, default=ConversationKind.OPERATE, help_text=_KIND_HELP
    )


class AssistantConversationSummarySerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=ConversationKind.choices, help_text=_KIND_HELP)
    title = serializers.CharField(allow_blank=True, help_text="The first message, shortened.")
    language = serializers.ChoiceField(choices=("pl", "en"))
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class AssistantConversationListSerializer(serializers.Serializer[Any]):
    items = AssistantConversationSummarySerializer(many=True)


class AssistantConversationListQuerySerializer(serializers.Serializer[Any]):
    limit = serializers.IntegerField(
        min_value=1, max_value=50, default=20, help_text="How many of the newest to return."
    )


class AssistantTurnItemSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(
        choices=("text", "action"),
        help_text="`text`: what the assistant wrote. `action`: one step it took or proposed.",
    )
    text = serializers.CharField(required=False)
    step_id = serializers.UUIDField(required=False)
    title = LocalizedTextSerializer(
        required=False, help_text="The step's command as a person reads it."
    )
    risk = serializers.ChoiceField(
        choices=("read", "draft", "apply", "publish", "irreversible"), required=False
    )
    status = serializers.ChoiceField(
        choices=("pending", "done", "refused", "failed", "skipped", "declined"),
        required=False,
        help_text="`pending`: waits for the person's click. Only `done` means it happened.",
    )
    code = serializers.CharField(
        required=False, allow_blank=True, help_text="Why a step did not run, as a stable code."
    )


class AssistantConsentGroupSerializer(serializers.Serializer[Any]):
    id = serializers.CharField(help_text="What the consent token is handed back under.")
    digest = serializers.CharField(
        help_text="Read the plan and mint the token at "
        "`/api/v1/organizations/current/command-consents/{digest}/`."
    )
    steps = serializers.ListField(child=serializers.UUIDField())


class AssistantTurnSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(source="turn.id")
    state = serializers.ChoiceField(choices=TurnState.choices, source="turn.state")
    failure_code = serializers.CharField(
        source="turn.failure_code",
        allow_blank=True,
        help_text="Why a failed turn failed: `conversation_budget`, `budget`, `refused`, "
        "`unavailable`, `step_limit`, `authorization_revoked`, `timeout`.",
    )
    created_at = serializers.DateTimeField(source="turn.created_at")
    text = serializers.CharField(help_text="The person's message.")
    items = AssistantTurnItemSerializer(many=True)
    consents = AssistantConsentGroupSerializer(
        many=True, help_text="The clicks an `awaiting_consent` turn waits for; else empty."
    )


class AssistantTurnAcceptedSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=TurnState.choices)


class AssistantConversationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(source="conversation.id")
    title = serializers.CharField(source="conversation.title", allow_blank=True)
    language = serializers.ChoiceField(choices=("pl", "en"), source="conversation.language")
    created_at = serializers.DateTimeField(source="conversation.created_at")
    updated_at = serializers.DateTimeField(source="conversation.updated_at")
    turns = AssistantTurnSerializer(many=True)


class AssistantTurnInputSerializer(serializers.Serializer[Any]):
    text = serializers.CharField(
        max_length=MAX_MESSAGE_CHARACTERS,
        trim_whitespace=True,
        help_text="What the person wrote, at most 4000 characters.",
    )


class AssistantConsentAnswerSerializer(serializers.Serializer[Any]):
    consents = serializers.DictField(
        child=serializers.CharField(max_length=2000),
        required=False,
        default=dict,
        help_text="Consent group id → the token its click minted. A group without a token "
        "does not run.",
    )
    declined = serializers.BooleanField(
        default=False,
        help_text="True: the person declined the whole plan; nothing runs.",
    )


class AssistantProfileSerializer(serializers.Serializer[Any]):
    schema = serializers.CharField(help_text="The document's contract: `company-profile.v1`.")
    version = serializers.IntegerField(
        min_value=0, help_text="0 while nothing was saved; a change names the version it saw."
    )
    document = serializers.DictField(
        help_text="What the owner told the assistant about the company, as "
        "`packages/contracts/assistant/company-profile.v1.schema.json`: every value with "
        "its origin and whether the owner confirmed it."
    )
    updated_at = serializers.DateTimeField(allow_null=True)


class AssistantProfileSavedSerializer(AssistantProfileSerializer):
    changed = serializers.ListField(
        child=serializers.CharField(),
        help_text="The fields the change touched, e.g. `company.city`; a list counts as one "
        "field. Empty when it changed nothing.",
    )


class AssistantProfileChangeSerializer(serializers.Serializer[Any]):
    expected_version = serializers.IntegerField(
        min_value=0, help_text="The version the change was made against; 0 for the first."
    )
    changes = serializers.DictField(
        help_text="A JSON merge patch (RFC 7396) over the document: a field sent replaces "
        "the field, `null` removes it, a list is replaced whole."
    )
