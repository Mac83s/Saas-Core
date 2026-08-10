from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from saas_core.modules.core.organizations.tenancy import TenantScopedModel

CATALOG_KEY_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    message="Klucz musi składać się z co najmniej dwóch segmentów oddzielonych kropką.",
)


class QuotaUnit(models.TextChoices):
    COUNT = "count", "Liczba"
    BYTES = "bytes", "Bajty"


class QuotaPeriod(models.TextChoices):
    LIFETIME = "lifetime", "Bez resetu"
    MONTH = "month", "Miesięcznie"


class BillingInterval(models.TextChoices):
    MONTH = "month", "Miesięcznie"
    YEAR = "year", "Rocznie"


class GrantSource(models.TextChoices):
    PLAN = "plan", "Plan"
    TRIAL = "trial", "Trial"
    PROMOTION = "promotion", "Promocja"
    OVERRIDE = "override", "Nadpisanie administracyjne"
    PARTNER = "partner", "Partnerstwo"
    ADDON = "addon", "Dodatek"


class SubscriptionState(models.TextChoices):
    UNCONFIGURED = "unconfigured", "Nieskonfigurowana"
    TRIALING = "trialing", "Trial"
    ACTIVE = "active", "Aktywna"
    GRACE_PERIOD = "grace_period", "Okres karencji"
    READ_ONLY = "read_only", "Tylko do odczytu"
    SUSPENDED = "suspended", "Zawieszona"
    CANCELED = "canceled", "Anulowana"


class AccessMode(models.TextChoices):
    FULL = "full", "Pełny dostęp"
    READ_ONLY = "read_only", "Tylko do odczytu"
    BLOCKED = "blocked", "Zablokowany"


class Feature(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    key = models.CharField(max_length=100, unique=True, validators=[CATALOG_KEY_VALIDATOR])
    name = models.CharField(max_length=120)
    module = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return self.key


class QuotaDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    key = models.CharField(max_length=100, unique=True, validators=[CATALOG_KEY_VALIDATOR])
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=16, choices=QuotaUnit)
    period = models.CharField(max_length=16, choices=QuotaPeriod)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return self.key


class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    current_version = models.OneToOneField(
        "PlanVersion",
        on_delete=models.SET_NULL,
        related_name="current_for_plan",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return self.key


class PlanVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    currency = models.CharField(
        max_length=3,
        default="PLN",
        validators=[RegexValidator(r"^[A-Z]{3}$", "Waluta musi być kodem ISO 4217.")],
    )
    billing_interval = models.CharField(
        max_length=16,
        choices=BillingInterval,
        default=BillingInterval.MONTH,
    )
    unit_amount_minor = models.PositiveBigIntegerField()
    feature_keys = models.JSONField(default=list)
    quotas = models.JSONField(default=dict)
    trial_days = models.PositiveSmallIntegerField(default=3)
    grace_period_days = models.PositiveSmallIntegerField(default=7)
    effective_from = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("plan__key", "version")
        constraints = [
            models.UniqueConstraint(fields=["plan", "version"], name="billing_plan_version_uq")
        ]

    def __str__(self) -> str:
        return f"{self.plan.key}:v{self.version}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.currency = self.currency.strip().upper()
        if not self._state.adding:
            raise ValidationError("Opublikowana wersja planu jest niemutowalna.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Opublikowana wersja planu jest niemutowalna.")

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        self.currency = self.currency.strip().upper()
        if not isinstance(self.feature_keys, list) or not all(
            isinstance(key, str) and key for key in self.feature_keys
        ):
            errors["feature_keys"] = "Funkcje muszą być listą kluczy."
        elif len(self.feature_keys) != len(set(self.feature_keys)):
            errors["feature_keys"] = "Klucz funkcji nie może się powtarzać."
        if not isinstance(self.quotas, dict) or not all(
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for key, value in self.quotas.items()
        ):
            errors["quotas"] = "Limity muszą mapować klucze na liczby >= 0."
        if isinstance(self.feature_keys, list):
            missing_features = set(self.feature_keys) - set(
                Feature.objects.filter(key__in=self.feature_keys).values_list("key", flat=True)
            )
            if missing_features:
                errors["feature_keys"] = f"Nieznane funkcje: {', '.join(sorted(missing_features))}."
        if isinstance(self.quotas, dict):
            missing_quotas = set(self.quotas) - set(
                QuotaDefinition.objects.filter(key__in=self.quotas).values_list("key", flat=True)
            )
            if missing_quotas:
                errors["quotas"] = f"Nieznane limity: {', '.join(sorted(missing_quotas))}."
        if errors:
            raise ValidationError(errors)


class EntitlementGrant(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    source = models.CharField(max_length=16, choices=GrantSource)
    feature = models.ForeignKey(
        Feature,
        on_delete=models.PROTECT,
        related_name="grants",
        null=True,
        blank=True,
    )
    quota_definition = models.ForeignKey(
        QuotaDefinition,
        on_delete=models.PROTECT,
        related_name="grants",
        null=True,
        blank=True,
    )
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="entitlement_grants",
        null=True,
        blank=True,
    )
    enabled = models.BooleanField(null=True, blank=True)
    limit_value = models.PositiveBigIntegerField(null=True, blank=True)
    reason = models.TextField(blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="entitlement_grants",
        null=True,
        blank=True,
    )
    valid_from = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "source", "created_at")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        feature__isnull=False,
                        quota_definition__isnull=True,
                        enabled__isnull=False,
                        limit_value__isnull=True,
                    )
                    | models.Q(
                        feature__isnull=True,
                        quota_definition__isnull=False,
                        enabled__isnull=True,
                        limit_value__isnull=False,
                    )
                ),
                name="billing_grant_target_value_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("valid_from")),
                name="billing_grant_valid_window_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(source=GrantSource.OVERRIDE)
                    | (models.Q(granted_by__isnull=False) & ~models.Q(reason=""))
                ),
                name="billing_override_audit_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(source=GrantSource.PLAN) | models.Q(plan_version__isnull=False)
                ),
                name="billing_plan_grant_version_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "source"], name="bill_grant_org_source_idx"),
            models.Index(fields=["organization", "expires_at"], name="bill_grant_org_expiry_idx"),
        ]


class EntitlementSnapshot(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="snapshots",
        null=True,
        blank=True,
    )
    subscription_state = models.CharField(
        max_length=20,
        choices=SubscriptionState,
        default=SubscriptionState.UNCONFIGURED,
    )
    access_mode = models.CharField(
        max_length=16,
        choices=AccessMode,
        default=AccessMode.BLOCKED,
    )
    features = models.JSONField(default=dict, blank=True)
    quotas = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=dict, blank=True)
    effective_until = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    computed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization"], name="billing_snapshot_organization_uq"
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "subscription_state"],
                name="bill_snapshot_org_state_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if not isinstance(self.features, dict) or not all(
            isinstance(key, str) and isinstance(value, bool) for key, value in self.features.items()
        ):
            errors["features"] = "Snapshot funkcji musi mapować klucze na bool."
        if not isinstance(self.quotas, dict) or not all(
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for key, value in self.quotas.items()
        ):
            errors["quotas"] = "Snapshot limitów musi zawierać liczby >= 0."
        if not isinstance(self.sources, dict):
            errors["sources"] = "Źródła snapshotu muszą być mapą."
        if errors:
            raise ValidationError(errors)
