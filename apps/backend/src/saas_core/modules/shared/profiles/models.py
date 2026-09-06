"""Who a person or a company is in public, as structured data.

ADR-036 separates three things the audit found tangled: `User` is an account and
gets no public fields, `Organization` is a tenant, and everything a visitor is
meant to see lives here. Before this module the only place for a specialist's
photo and description was a page block, which meant the same person had to be
retyped on every page and could not be pointed at from Booking at all.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel

LOCALE_CHOICES = [("pl", "Polski"), ("en", "English")]


#: What a profile is about. A company has exactly one; a company has as many
#: people as it employs, and a person without a panel account has one too —
#: which is why the membership link is optional rather than the identity.
class ProfileSubjectKind(models.TextChoices):
    ORGANIZATION = "organization", "Organizacja"
    PERSON = "person", "Osoba"


def _validate_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 12:
        raise ValidationError({"links": "Linki muszą być listą (najwyżej 12 pozycji)."})
    links: list[dict[str, str]] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"label", "url"}
            or not all(isinstance(field, str) and field.strip() for field in item.values())
        ):
            raise ValidationError({"links": "Każdy link ma pola label i url."})
        url = item["url"].strip()
        if not url.startswith(("https://", "http://")):
            raise ValidationError({"links": "Link musi zaczynać się od http:// albo https://."})
        links.append({"label": item["label"].strip()[:80], "url": url[:400]})
    return links


def _validate_keys(value: Any, field: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValidationError({field: f"Lista może mieć najwyżej {limit} pozycji."})
    keys: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError({field: "Pozycje muszą być niepustymi kluczami."})
        keys.append(item.strip()[:64])
    if len(keys) != len(set(keys)):
        raise ValidationError({field: "Pozycje nie mogą się powtarzać."})
    return keys


class PublicProfile(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    subject_kind = models.CharField(max_length=16, choices=ProfileSubjectKind)
    # Optional on purpose: a receptionist with a panel account and a visiting
    # specialist without one are both people the site shows.
    membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    display_name = models.CharField(max_length=160)
    headline = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True, max_length=4000)
    photo = models.ForeignKey(
        "media.MediaAsset",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    # Explicit fields rather than a blob: a renderer and an export both have to
    # know what a phone number is, and a JSON bag makes that a guess.
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_address = models.CharField(max_length=240, blank=True)
    links = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=list, blank=True)
    specializations = models.JSONField(default=list, blank=True)
    locale = models.CharField(max_length=10, choices=LOCALE_CHOICES, default="pl")
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "subject_kind", "display_name", "id")
        constraints = [
            # One company profile per company, enforced where it cannot be
            # raced: two requests would otherwise each create their own.
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(subject_kind=ProfileSubjectKind.ORGANIZATION),
                name="profiles_single_organization_profile_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(subject_kind=ProfileSubjectKind.PERSON)
                    | models.Q(membership__isnull=True)
                ),
                name="profiles_membership_only_for_person_ck",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name

    def clean(self) -> None:
        super().clean()
        self.display_name = self.display_name.strip()
        if not self.display_name:
            raise ValidationError({"display_name": "Nazwa jest wymagana."})
        # Bio is text with limited formatting, never markup: it is rendered on a
        # public page, and a field that accepts HTML is a stored-XSS surface.
        if "<" in self.bio or "<" in self.headline:
            raise ValidationError({"bio": "Opis nie może zawierać znaczników HTML."})
        self.links = _validate_links(self.links)
        self.languages = _validate_keys(self.languages, "languages", 12)
        self.specializations = _validate_keys(self.specializations, "specializations", 24)


class PublicProfileTranslation(TenantScopedModel):
    """The same profile said in another language.

    Same shape as page translations (ADR-027): one row per locale with explicit
    fallback flags, so an empty field means "not translated yet" rather than
    "deliberately blank" only when somebody said so.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    profile = models.ForeignKey(
        PublicProfile,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    locale = models.CharField(max_length=10, choices=LOCALE_CHOICES)
    headline = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True, max_length=4000)
    allow_headline_fallback = models.BooleanField(default=True)
    allow_bio_fallback = models.BooleanField(default=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "profile_id", "locale")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "profile", "locale"],
                name="profiles_translation_org_profile_locale_uq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.locale}"

    def clean(self) -> None:
        super().clean()
        if "<" in self.bio or "<" in self.headline:
            raise ValidationError({"bio": "Opis nie może zawierać znaczników HTML."})
