"""Operator telemetry of every model call, without content (ADR-068 pkt 8).

One row per call (`kind=call`) or per consumer's settlement (`kind=settlement`):
identifiers, token counts, money, time and outcome — never a prompt, an output,
tool arguments or a provider's message. The organization is a bare UUID, not a
foreign key: the port writes on its own connection, and a key would take FOR
KEY SHARE on an organization row the caller's request may hold FOR UPDATE —
two connections waiting on each other, which PostgreSQL does not detect. Rows
leave with their organization through `register_erasure_rows`.

Declared in `platformTables` and without RLS: the port's connection sets no
tenant, and a tenant policy would silently zero the sums the ceilings read.
"""

from __future__ import annotations

import uuid

from django.db import models


class EntryKind(models.TextChoices):
    CALL = "call", "Wywołanie"
    SETTLEMENT = "settlement", "Rozliczenie"


class EntryState(models.TextChoices):
    ADMITTED = "admitted", "Dopuszczone"
    CALLING = "calling", "W toku"
    DONE = "done", "Zakończone"
    EXPIRED = "expired", "Wygasłe"


#: States whose cost — or estimate — counts toward the ceilings.
COUNTED_STATES = (EntryState.ADMITTED, EntryState.CALLING, EntryState.DONE)


class UsageEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=16, choices=EntryKind.choices, default=EntryKind.CALL)
    state = models.CharField(max_length=16, choices=EntryState.choices)
    task = models.CharField(max_length=80)
    pool = models.CharField(max_length=32)
    adapter = models.CharField(max_length=32, blank=True)
    requested_model = models.CharField(max_length=120, blank=True)
    resolved_model = models.CharField(max_length=120, blank=True)
    resolved_provider = models.CharField(max_length=80, blank=True)
    organization_id = models.UUIDField(null=True, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)
    conversation_id = models.UUIDField(null=True, blank=True)
    purpose = models.CharField(max_length=16)
    prompt_id = models.CharField(max_length=80, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    data_class = models.CharField(max_length=24, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    resend_of = models.UUIDField(null=True, blank=True)
    outcome = models.CharField(max_length=32, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    finish_reason = models.CharField(max_length=16, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(default=0)
    cached_input_tokens = models.PositiveIntegerField(default=0)
    continuations_dropped = models.PositiveSmallIntegerField(default=0)
    estimate_usd_micros = models.BigIntegerField(default=0)
    #: Empty when the outcome is unknown: an unknown cost stays unknown
    #: (ADR-046:20); the ceilings count the estimate in its place.
    cost_usd_micros = models.BigIntegerField(null=True, blank=True)
    cost_source = models.CharField(max_length=16, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    provider_request_id = models.CharField(max_length=120, blank=True)
    credits = models.PositiveIntegerField(null=True, blank=True)
    units = models.PositiveIntegerField(null=True, blank=True)
    unit = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "model_port_usageentry"
        indexes = [
            models.Index(fields=["pool", "created_at"], name="model_port_pool_created_idx"),
            models.Index(
                fields=["organization_id", "created_at"], name="model_port_org_created_idx"
            ),
            models.Index(fields=["actor_id", "created_at"], name="model_port_actor_created_idx"),
            models.Index(fields=["conversation_id"], name="model_port_conversation_idx"),
            models.Index(fields=["reference"], name="model_port_reference_idx"),
            models.Index(
                fields=["state", "expires_at"],
                condition=models.Q(state__in=["admitted", "calling"]),
                name="model_port_open_idx",
            ),
        ]
        constraints = [
            # "At most once": an unknown outcome is sent again by one row only.
            models.UniqueConstraint(
                fields=["resend_of"],
                condition=models.Q(resend_of__isnull=False),
                name="model_port_resend_once_uq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.task} {self.state} {self.outcome}"
