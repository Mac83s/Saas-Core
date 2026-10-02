from __future__ import annotations

import uuid

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
