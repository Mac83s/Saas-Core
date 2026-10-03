"""A conversation with the assistant, as the server keeps it (ADR-076, A3).

Three tables, all the company's own (RLS): the conversation, its turns — one
per message of the person, with the plan that waits for their click — and the
transcript the model is shown again on every call. The transcript is content
a person wrote and personal data: nothing here goes to a log, and the rows
leave after `assistant.retention.conversation_days` and with the company.

A fourth holds the company's profile (A2): what the owner said about the
company, one row per saved state.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class TurnState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    AWAITING_CONSENT = "awaiting_consent", "Awaiting consent"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


#: A turn still in progress: a conversation has at most one.
TURN_OPEN = (TurnState.QUEUED, TurnState.RUNNING, TurnState.AWAITING_CONSENT)


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    TOOL = "tool", "Tool"


class ConversationKind(models.TextChoices):
    #: Operates the company through the registry's commands (A3-1).
    OPERATE = "operate", "Operate"
    #: Sets the company up: notes the profile and offers the configurator's
    #: plan, with three tools of its own and no other (A3-2).
    SETUP = "setup", "Setup"


class AssistantConversation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(
        max_length=10, choices=ConversationKind.choices, default=ConversationKind.OPERATE
    )
    # The membership the assistant acts for; only that person reads the rows.
    membership_id = models.UUIDField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # The panel's language when it began: previews and refusals use it.
    language = models.CharField(max_length=2)
    title = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "membership_id", "idempotency_key"],
                name="assistant_conv_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=[choice.value for choice in ConversationKind]),
                name="assistant_conv_kind_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "membership_id", "-updated_at"],
                name="assistant_conv_person_idx",
            )
        ]


class AssistantTurn(TenantScopedModel):
    """One message of the person and everything the assistant did about it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE, related_name="turns"
    )
    index = models.PositiveIntegerField()
    state = models.CharField(max_length=20, choices=TurnState.choices, default=TurnState.QUEUED)
    idempotency_key = models.CharField(max_length=160)
    failure_code = models.CharField(max_length=80, blank=True)
    # Model calls made for this turn, against `assistant.limits.model_steps_per_turn`.
    steps_used = models.PositiveSmallIntegerField(default=0)
    # The plan waiting for the person's click: the invocations with the step
    # ids the server gave them, and each consent group's id and digest.
    pending = models.JSONField(null=True, blank=True)
    credit_reservation_key = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "index"], name="assistant_turn_index_unique"
            ),
            models.UniqueConstraint(
                fields=["conversation", "idempotency_key"], name="assistant_turn_key_unique"
            ),
            models.UniqueConstraint(
                fields=["conversation"],
                condition=models.Q(state__in=[state.value for state in TURN_OPEN]),
                name="assistant_turn_one_open",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=[choice.value for choice in TurnState]),
                name="assistant_turn_state_ck",
            ),
        ]
        indexes = [models.Index(fields=["state", "updated_at"], name="assistant_turn_state_idx")]


class AssistantMessage(TenantScopedModel):
    """One message of the transcript, in the order the model reads it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE, related_name="messages"
    )
    turn = models.ForeignKey(AssistantTurn, on_delete=models.CASCADE, related_name="messages")
    index = models.PositiveIntegerField()
    role = models.CharField(max_length=10, choices=MessageRole.choices)
    content = models.TextField(blank=True)
    # An assistant message's calls: the provider's id, the tool name and the
    # model's exact arguments, with the step id and command the server gave.
    tool_calls = models.JSONField(default=list, blank=True)
    # A tool message: the call it answers and how the step ended.
    tool_call_id = models.CharField(max_length=200, blank=True)
    result = models.JSONField(null=True, blank=True)
    # Opaque provider state the same model needs back (ADR-068).
    continuation = models.JSONField(null=True, blank=True)
    usage_entry_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "index"], name="assistant_message_index_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=[choice.value for choice in MessageRole]),
                name="assistant_message_role_ck",
            ),
        ]


class AssistantProfileVersion(TenantScopedModel):
    """One saved state of the company's profile (`profile_schema.py`).

    The newest row is the profile; the older ones are its history — who
    changed it, when and from which conversation. Personal data: the owner's
    words and the names of the company's people. Rows leave with the company;
    versions older than the current one are due after
    `assistant.retention.conversation_days` (the purge arrives with the
    platform's retention hook, not here).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    version = models.PositiveIntegerField()
    document = models.JSONField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    membership_id = models.UUIDField()
    # Empty when the person saved it themselves; "assistant" with the
    # conversation it came from otherwise (ADR-076 §6). Not a foreign key: the
    # transcript is purged long before the profile is.
    acting_via = models.CharField(max_length=20, blank=True)
    conversation_id = models.UUIDField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=160)
    # What was asked under that key, so the key reused for something else is refused.
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "version"], name="assistant_profile_version_unique"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"], name="assistant_profile_key_unique"
            ),
        ]
