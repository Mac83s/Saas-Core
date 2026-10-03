from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class GlossaryRule(models.TextChoices):
    # Unchanged in every script: a brand, a product name.
    KEEP = "keep", "Keep"
    # Unchanged in Latin, transliterated into Cyrillic: a person's name.
    NAME = "name", "Name"
    # The company's own translation.
    TRANSLATE_AS = "translate_as", "Translate as"


class TranslationGlossaryTerm(TenantScopedModel):
    """One term of a company's glossary (ADR-069 pkt 7).

    Data for the model, never an instruction: a term reaches it only when it
    occurs in the text being translated, inside the same data frame as the
    segments, and the limits below keep it a term rather than a paragraph.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    term = models.CharField(max_length=120)
    rule = models.CharField(max_length=16, choices=GlossaryRule.choices)
    source_locale = models.CharField(max_length=10)
    # Empty: every target language.
    target_locale = models.CharField(max_length=10, blank=True)
    # `translate_as` only.
    translation = models.CharField(max_length=120, blank=True)
    # Inflected forms of the term in the source language, at most 10.
    forms = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                "organization",
                Lower("term"),
                "source_locale",
                "target_locale",
                name="translation_glossary_term_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(rule__in=[choice.value for choice in GlossaryRule]),
                name="translation_glossary_term_rule_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(rule=GlossaryRule.TRANSLATE_AS) | ~models.Q(translation=""),
                name="translation_glossary_term_translation_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(term=""),
                name="translation_glossary_term_not_empty_ck",
            ),
        ]
        indexes = [models.Index(fields=["organization", "source_locale"])]


class TranslationMode(models.TextChoices):
    AUTOMATIC = "automatic", "Automatic"
    REVIEW = "review", "Review"


class TranslationSettings(TenantScopedModel):
    """The company's translation settings (ADR-069 pkt 6, 12, 14; ADR-078 `entity`).

    An empty or null value is no explicit value: the profile's starting value
    or the code's default applies. Written only through `change_settings`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    mode = models.CharField(max_length=16, choices=TranslationMode.choices, blank=True)
    auto_changes = models.BooleanField(null=True, blank=True)
    # The person whose consent the automation acts on, checked at every run.
    auto_consent_membership_id = models.UUIDField(null=True, blank=True)
    auto_consent_at = models.DateTimeField(null=True, blank=True)
    auto_monthly_limit = models.PositiveIntegerField(null=True, blank=True)
    # Delivered characters of automatic jobs not yet billed: they pay whole
    # thousands and carry the rest to the next part, month after month (ADR-069 pkt 23).
    auto_carry_characters = models.PositiveIntegerField(default=0)
    # The one-off confirmation that content goes to OpenRouter and model
    # providers outside the EEA (ADR-069 pkt 6).
    processing_ack_membership_id = models.UUIDField(null=True, blank=True)
    processing_ack_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="translation_settings_org_uq"),
            models.CheckConstraint(
                condition=models.Q(mode__in=["", *TranslationMode.values]),
                name="translation_settings_mode_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(auto_monthly_limit__isnull=True)
                | models.Q(auto_monthly_limit__lte=100_000),
                name="translation_settings_limit_ck",
            ),
        ]


class TranslationMutation(TenantScopedModel):
    """The receipt of a translation write: the same key again gets the first
    answer back (ADR-046 semantics, as `BookingSetupMutation`)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: `settings.update`, `glossary.create`, `glossary.update`, `glossary.delete`.
    action = models.CharField(max_length=40)
    principal_ref = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    result_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "action", "principal_ref", "idempotency_key"],
                name="translation_mutation_idem_uq",
            )
        ]


class TranslationOverride(TenantScopedModel):
    """The operator's override for one company (ADR-069 pkt 30), append-only.

    The newest row is in force. It works as a lock: it wins over the company's
    value, and the company sees the field locked with the reason. Written only
    by `translation_org_override --operator --reason`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    # "" none, "review" forced review, "off" paused.
    mode_cap = models.CharField(max_length=8, blank=True)
    # A lower automation limit than the company's; null leaves it alone.
    auto_monthly_limit_cap = models.PositiveIntegerField(null=True, blank=True)
    reason = models.TextField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mode_cap__in=["", "review", "off"]),
                name="translation_override_mode_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="translation_override_reason_ck"
            ),
        ]


class TranslationCeiling(models.Model):
    """The deployment's switch (ADR-069 pkt 30), append-only like `AiBadgeSwitch`.

    The newest row is the state; no rows means `none`. A platform table: no
    organization, no RLS. Written only by `translation_ceiling --operator --reason`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    state = models.CharField(max_length=8)
    reason = models.TextField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=["none", "review", "off"]),
                name="translation_ceiling_state_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="translation_ceiling_reason_ck"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.state}"


class JobState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


JOB_TERMINAL = frozenset({JobState.SUCCEEDED, JobState.PARTIAL, JobState.FAILED, JobState.CANCELED})


class PartState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SETTLED = "settled", "Settled"


class ItemState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    WRITTEN = "written", "Written"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"


ITEM_ACTIVE = frozenset({ItemState.QUEUED, ItemState.RUNNING})


class TranslationJob(TenantScopedModel):
    """One order: the pairs (object × language) of one quote, sealed by its
    digest, run as the person who ordered it (ADR-069 pkt 13, 18, 19)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    # The membership the job acts as: the person who clicked, or who consented.
    membership_id = models.UUIDField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # click | automatic
    trigger = models.CharField(max_length=16)
    # `<kind>:<uuid>` (A1a `acting_trigger`): user, api_key, schedule, conversation.
    cause = models.CharField(max_length=80)
    # credits | platform_budget
    billing = models.CharField(max_length=16)
    protected = models.CharField(max_length=16)
    include_unverified = models.BooleanField(default=False)
    quote_digest = models.CharField(max_length=64)
    operation_key = models.CharField(max_length=100)
    unit_cost = models.PositiveIntegerField(null=True, blank=True)
    units = models.PositiveIntegerField(default=0)
    credits = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=JobState.choices, default=JobState.QUEUED)
    error_code = models.CharField(max_length=80, blank=True)
    next_attempt_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # „Cofnij ostatnie zadanie”: the sources went back to their texts from before.
    reverted_at = models.DateTimeField(null=True, blank=True)
    # The platform's own content above the confirmation threshold waits for
    # the operator (ADR-069 pkt 26); the estimate is in USD micros.
    estimated_usd_micros = models.PositiveBigIntegerField(null=True, blank=True)
    confirmation_required = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["organization", "state", "next_attempt_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(trigger__in=["click", "automatic"]),
                name="translation_job_trigger_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(billing__in=["credits", "platform_budget"]),
                name="translation_job_billing_ck",
            ),
        ]


class TranslationJobPart(TenantScopedModel):
    """At most 500 units of a job, with its own credit hold taken when it starts
    and its own 72-hour deadline (ADR-069 pkt 19, 20)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    job = models.ForeignKey(TranslationJob, on_delete=models.CASCADE, related_name="parts")
    index = models.PositiveIntegerField()
    units = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=PartState.choices, default=PartState.QUEUED)
    reservation_key = models.CharField(max_length=120, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    delivered_characters = models.PositiveIntegerField(default=0)
    settled_units = models.PositiveIntegerField(default=0)
    settled_credits = models.PositiveIntegerField(default=0)
    settled_at = models.DateTimeField(null=True, blank=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "index"], name="translation_part_index_uq")
        ]


class TranslationJobItem(TenantScopedModel):
    """One object in one language: the durable queue, with one active item per
    pair (ADR-069 pkt 19)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    job = models.ForeignKey(TranslationJob, on_delete=models.CASCADE, related_name="items")
    part = models.ForeignKey(TranslationJobPart, on_delete=models.CASCADE, related_name="items")
    # The order of the quote: a site's home page first.
    position = models.PositiveIntegerField()
    source_key = models.CharField(max_length=100)
    object_id = models.UUIDField()
    locale = models.CharField(max_length=10)
    basis = models.CharField(max_length=16)
    scope = models.CharField(max_length=200)
    quoted_characters = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=ItemState.choices, default=ItemState.QUEUED)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    # Results that passed the hard checks, by source hash, kept until the item
    # is written: a write refused for a changed version is retried without a
    # second model call.
    delivered = models.JSONField(default=dict, blank=True)
    delivered_characters = models.PositiveIntegerField(default=0)
    # What the source answered: [{state, reason, keys}] — no text.
    outcomes = models.JSONField(default=list, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_key", "object_id", "locale"],
                condition=models.Q(state__in=["queued", "running"]),
                name="translation_item_active_uq",
            )
        ]
        indexes = [models.Index(fields=["job", "state", "position"])]


class ReviewState(models.TextChoices):
    OPEN = "open", "Open"
    ACCEPTED = "accepted", "Accepted"
    DISCARDED = "discarded", "Discarded"
    SUPERSEDED = "superseded", "Superseded"


class TranslationReviewItem(TenantScopedModel):
    """A result waiting for a person, with the reason (ADR-069 pkt 21).

    A versioned source keeps the text itself (pages: `body_pending`) and takes
    the decision through `review`; a live record keeps nothing pending, so the
    text waits here and an acceptance is a write with the `acceptance` trigger
    (docs/architecture/translation-sources.md §6.3, §6.6). A newer result for
    the same pair supersedes an open one.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    job = models.ForeignKey(
        TranslationJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews"
    )
    source_key = models.CharField(max_length=100)
    object_id = models.UUIDField()
    locale = models.CharField(max_length=10)
    basis = models.CharField(max_length=16)
    basis_version = models.CharField(max_length=200)
    target_version = models.CharField(max_length=200, blank=True)
    reason = models.CharField(max_length=40)
    keys = models.PositiveIntegerField(default=0)
    # Live records only: unit key → [text, provenance]. Customer content,
    # cleared once decided.
    texts = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=16, choices=ReviewState.choices, default=ReviewState.OPEN)
    version = models.PositiveIntegerField(default=1)
    decided_by_membership_id = models.UUIDField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["organization", "state", "created_at"])]


class DemandState(models.TextChoices):
    WAITING = "waiting", "Waiting"
    # Consent, rights, the month's limit, credits or the provider are missing:
    # checked again at `check_at` (ADR-069 pkt 14, translation-sources.md §8.3).
    BLOCKED = "blocked", "Blocked"


class TranslationDemand(TenantScopedModel):
    """An object whose public source changed while the automation is on, waiting
    for its job (TL21, translation-sources.md §8.3).

    One row per (source, object): repeated changes move `due_at` — five
    minutes after the latest, at most thirty after the first — so a burst of
    publications becomes one job.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    source_key = models.CharField(max_length=100)
    object_id = models.UUIDField()
    # `<kind>:<uuid>` of the change that opened the row: user, api_key, schedule.
    cause = models.CharField(max_length=80)
    first_at = models.DateTimeField()
    due_at = models.DateTimeField()
    state = models.CharField(
        max_length=16, choices=DemandState.choices, default=DemandState.WAITING
    )
    reason = models.CharField(max_length=40, blank=True)
    check_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_key", "object_id"],
                name="translation_demand_object_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["waiting", "blocked"]),
                name="translation_demand_state_ck",
            ),
        ]
        indexes = [models.Index(fields=["state", "due_at"])]
