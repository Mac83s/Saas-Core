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
