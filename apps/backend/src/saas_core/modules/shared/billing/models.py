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


class QuotaReservationState(models.TextChoices):
    RESERVED = "reserved", "Zarezerwowana"
    COMMITTED = "committed", "Rozliczona"
    RELEASED = "released", "Zwolniona"


class StripeSubscriptionStatus(models.TextChoices):
    INCOMPLETE = "incomplete", "Niekompletna"
    INCOMPLETE_EXPIRED = "incomplete_expired", "Niekompletna i wygasła"
    TRIALING = "trialing", "Trial"
    ACTIVE = "active", "Aktywna"
    PAST_DUE = "past_due", "Płatność zaległa"
    CANCELED = "canceled", "Anulowana"
    UNPAID = "unpaid", "Nieopłacona"
    PAUSED = "paused", "Wstrzymana"


class WebhookProcessingStatus(models.TextChoices):
    RECEIVED = "received", "Odebrane"
    PROCESSING = "processing", "Przetwarzane"
    PROCESSED = "processed", "Przetworzone"
    FAILED = "failed", "Błąd"
    IGNORED = "ignored", "Pominięte"


class CheckoutStatus(models.TextChoices):
    OPEN = "open", "Otwarty"
    COMPLETE = "complete", "Zakończony"
    EXPIRED = "expired", "Wygasły"


class TrialActivationStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    ACTIVE = "active", "Aktywowana"
    FAILED = "failed", "Błąd"


class LifecycleActionType(models.TextChoices):
    TRIAL_ENDING_NOTICE = "trial_ending_notice", "Ostrzeżenie o końcu triala"
    GRACE_ENDING_NOTICE = "grace_ending_notice", "Ostrzeżenie o końcu karencji"
    GRACE_EXPIRED = "grace_expired", "Koniec karencji"
    CANCELED_PERIOD_ENDED = "canceled_period_ended", "Koniec opłaconego okresu"


class LifecycleActionStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    PROCESSED = "processed", "Przetworzona"
    CANCELED = "canceled", "Anulowana"
    FAILED = "failed", "Błąd"


class BillingNoticeType(models.TextChoices):
    TRIAL_ENDING = "trial_ending", "Koniec triala"
    GRACE_ENDING = "grace_ending", "Koniec karencji"


class ReconciliationStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    SUCCEEDED = "succeeded", "Zsynchronizowana"
    NO_CHANGE = "no_change", "Bez zmian"
    CONFLICT = "conflict", "Konflikt wersji"
    FAILED = "failed", "Błąd"


class InvoiceDocumentStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    PROCESSING = "processing", "Przetwarzany"
    SUCCEEDED = "succeeded", "Obsłużony"
    FAILED = "failed", "Błąd"


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


class StripePriceMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="stripe_prices",
    )
    stripe_product_id = models.CharField(max_length=160)
    stripe_price_id = models.CharField(max_length=160, unique=True)
    # Which catalog this price came from. A price id, like a customer id,
    # means nothing outside the provider that issued it: handing Stripe the
    # simulator's sim_price_… is a rejected request, and reconciling a
    # simulated subscription against Stripe is a failure filed every five
    # minutes.
    provider = models.CharField(max_length=16, default="stripe")
    livemode = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("plan_version__plan__key", "plan_version__version", "livemode")
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "livemode"],
                condition=models.Q(is_active=True),
                name="billing_active_price_plan_mode_uq",
            )
        ]

    def __str__(self) -> str:
        return self.stripe_price_id


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
    idempotency_key = models.CharField(max_length=120, blank=True)
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
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="billing_grant_idempotency_uq",
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


class BillingSubscription(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    price_mapping = models.ForeignKey(
        StripePriceMapping,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    stripe_subscription_id = models.CharField(max_length=160, unique=True)
    state = models.CharField(
        max_length=20,
        choices=SubscriptionState,
        default=SubscriptionState.UNCONFIGURED,
    )
    provider_status = models.CharField(max_length=24, choices=StripeSubscriptionStatus)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    grace_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    last_event_created_at = models.DateTimeField(null=True, blank=True)
    last_event_id = models.CharField(max_length=160, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=~models.Q(state=SubscriptionState.CANCELED),
                name="billing_subscription_current_org_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(current_period_start__isnull=True, current_period_end__isnull=True)
                    | (
                        models.Q(
                            current_period_start__isnull=False,
                            current_period_end__isnull=False,
                        )
                        & models.Q(current_period_end__gt=models.F("current_period_start"))
                    )
                ),
                name="billing_subscription_period_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(trial_start__isnull=True, trial_end__isnull=True)
                    | (
                        models.Q(trial_start__isnull=False, trial_end__isnull=False)
                        & models.Q(trial_end__gt=models.F("trial_start"))
                    )
                ),
                name="billing_subscription_trial_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "state"],
                name="bill_sub_org_state_idx",
            )
        ]


class BillingCheckout(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    price_mapping = models.ForeignKey(
        StripePriceMapping,
        on_delete=models.PROTECT,
        related_name="checkouts",
    )
    stripe_checkout_session_id = models.CharField(max_length=160, unique=True)
    idempotency_key = models.CharField(max_length=120)
    checkout_url = models.URLField(max_length=2048)
    status = models.CharField(
        max_length=16,
        choices=CheckoutStatus,
        default=CheckoutStatus.OPEN,
    )
    setup_intent_id = models.CharField(max_length=160, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="billing_checkout_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status=CheckoutStatus.COMPLETE, completed_at__isnull=False)
                    | (
                        ~models.Q(status=CheckoutStatus.COMPLETE)
                        & models.Q(completed_at__isnull=True)
                    )
                ),
                name="billing_checkout_completed_ck",
            ),
        ]


class BillingTrialActivation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    checkout = models.OneToOneField(
        BillingCheckout,
        on_delete=models.PROTECT,
        related_name="trial_activation",
    )
    subscription = models.OneToOneField(
        BillingSubscription,
        on_delete=models.PROTECT,
        related_name="trial_activation",
        null=True,
        blank=True,
    )
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=160)
    status = models.CharField(
        max_length=16,
        choices=TrialActivationStatus,
        default=TrialActivationStatus.PENDING,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id",)
        # One activation per Checkout, not per organization. The organization
        # used to be unique here, which read as "a company activates its plan
        # once" and turned out to mean "a company can never buy again": a
        # customer whose plan ended paid through a new Checkout and got a
        # conflict. One live subscription at a time is still the rule — it is
        # enforced where subscriptions are written, which is where it belongs.
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=TrialActivationStatus.ACTIVE,
                        subscription__isnull=False,
                        activated_at__isnull=False,
                    )
                    | (
                        ~models.Q(status=TrialActivationStatus.ACTIVE)
                        & models.Q(subscription__isnull=True, activated_at__isnull=True)
                    )
                ),
                name="billing_trial_activation_state_ck",
            ),
        ]


class BillingLifecycleAction(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    subscription = models.ForeignKey(
        BillingSubscription,
        on_delete=models.PROTECT,
        related_name="lifecycle_actions",
    )
    action_type = models.CharField(max_length=32, choices=LifecycleActionType)
    due_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=LifecycleActionStatus,
        default=LifecycleActionStatus.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("due_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "action_type", "due_at"],
                name="billing_lifecycle_action_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=[
                            LifecycleActionStatus.PROCESSED,
                            LifecycleActionStatus.CANCELED,
                        ],
                        processed_at__isnull=False,
                    )
                    | (
                        models.Q(
                            status__in=[
                                LifecycleActionStatus.PENDING,
                                LifecycleActionStatus.FAILED,
                            ]
                        )
                        & models.Q(processed_at__isnull=True)
                    )
                ),
                name="billing_lifecycle_processed_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "due_at"],
                name="bill_lifecycle_due_idx",
            )
        ]


class BillingNotice(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    lifecycle_action = models.OneToOneField(
        BillingLifecycleAction,
        on_delete=models.PROTECT,
        related_name="notice",
    )
    subscription = models.ForeignKey(
        BillingSubscription,
        on_delete=models.PROTECT,
        related_name="notices",
    )
    notice_type = models.CharField(max_length=24, choices=BillingNoticeType)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(
                fields=["organization", "notice_type", "created_at"],
                name="bill_notice_org_type_idx",
            )
        ]


class BillingReconciliation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    subscription = models.ForeignKey(
        BillingSubscription,
        on_delete=models.PROTECT,
        related_name="reconciliations",
    )
    scheduled_for = models.DateTimeField()
    baseline_version = models.PositiveBigIntegerField()
    status = models.CharField(
        max_length=16,
        choices=ReconciliationStatus,
        default=ReconciliationStatus.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    changes = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("scheduled_for", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "scheduled_for"],
                name="billing_reconciliation_schedule_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status=ReconciliationStatus.PENDING, completed_at__isnull=True)
                    | (
                        ~models.Q(status=ReconciliationStatus.PENDING)
                        & models.Q(completed_at__isnull=False)
                    )
                ),
                name="billing_reconciliation_completed_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "scheduled_for"],
                name="bill_reconcile_status_idx",
            )
        ]


class StripeWebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    stripe_event_id = models.CharField(max_length=160, unique=True)
    event_type = models.CharField(max_length=120)
    api_version = models.CharField(max_length=32, blank=True)
    livemode = models.BooleanField()
    provider_created_at = models.DateTimeField()
    payload = models.JSONField()
    status = models.CharField(
        max_length=16,
        choices=WebhookProcessingStatus,
        default=WebhookProcessingStatus.RECEIVED,
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="stripe_webhook_events",
        null=True,
        blank=True,
    )
    subscription = models.ForeignKey(
        BillingSubscription,
        on_delete=models.PROTECT,
        related_name="webhook_events",
        null=True,
        blank=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    processing_error = models.TextField(blank=True)
    signature_verified_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("received_at",)
        indexes = [
            models.Index(fields=["status", "received_at"], name="bill_webhook_status_idx"),
            models.Index(
                fields=["event_type", "provider_created_at"],
                name="bill_webhook_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.stripe_event_id


class QuotaUsage(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    quota_definition = models.ForeignKey(
        QuotaDefinition,
        on_delete=models.PROTECT,
        related_name="usage_periods",
    )
    period_start = models.DateField()
    period_end = models.DateField(null=True, blank=True)
    used = models.PositiveBigIntegerField(default=0)
    reserved = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "quota_definition_id", "period_start")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "quota_definition", "period_start", "period_end"],
                name="billing_quota_usage_period_uq",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__isnull=True)
                | models.Q(period_end__gt=models.F("period_start")),
                name="billing_quota_usage_window_ck",
            ),
        ]


class QuotaReservation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    usage = models.ForeignKey(
        QuotaUsage,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    idempotency_key = models.CharField(max_length=120)
    amount = models.PositiveBigIntegerField()
    state = models.CharField(
        max_length=16,
        choices=QuotaReservationState,
        default=QuotaReservationState.RESERVED,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="billing_quota_reservation_key_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="billing_quota_reservation_amount_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "state", "expires_at"],
                name="bill_reservation_state_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.usage_id and self.usage.organization_id != self.organization_id:
            raise ValidationError({"usage": "Licznik quota należy do innej organizacji."})


class BillingInvoiceDocument(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    subscription = models.ForeignKey(
        BillingSubscription,
        on_delete=models.PROTECT,
        related_name="invoice_documents",
    )
    origin_event = models.ForeignKey(
        StripeWebhookEvent,
        on_delete=models.PROTECT,
        related_name="invoice_documents",
    )
    stripe_invoice_id = models.CharField(max_length=160, unique=True)
    status = models.CharField(
        max_length=16,
        choices=InvoiceDocumentStatus,
        default=InvoiceDocumentStatus.PENDING,
    )
    adapter_key = models.CharField(max_length=64, default="internal")
    request = models.JSONField(default=dict)
    result = models.JSONField(default=dict, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    payment_confirmed_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=[
                            InvoiceDocumentStatus.PENDING,
                            InvoiceDocumentStatus.PROCESSING,
                        ],
                        completed_at__isnull=True,
                    )
                    | models.Q(
                        status=InvoiceDocumentStatus.SUCCEEDED,
                        completed_at__isnull=False,
                        last_error="",
                    )
                    | (
                        models.Q(
                            status=InvoiceDocumentStatus.FAILED,
                            completed_at__isnull=False,
                        )
                        & ~models.Q(last_error="")
                    )
                ),
                name="billing_invoice_document_state_ck",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "created_at"],
                name="bill_invoice_org_status_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.subscription_id and self.subscription.organization_id != self.organization_id:
            raise ValidationError({"subscription": "Subskrypcja należy do innej organizacji."})
        if self.origin_event_id and self.origin_event.organization_id not in (
            None,
            self.organization_id,
        ):
            raise ValidationError({"origin_event": "Event należy do innej organizacji."})


# --------------------------------------------------------------------------
# Credits — a prepaid pool our own customers spend on metered operations.
#
# This is the same relationship as the subscription: an organization pays the
# platform. What a company later charges its own end customers for is a
# different domain and does not belong here (ADR-037).
#
# Two buckets, one balance. The plan grants a monthly allowance that resets and
# does not carry over; purchased credits never expire. Spending takes the
# allowance first, so nobody loses what they paid for separately. The ledger is
# the truth and the balance row is its cached sum — a test rebuilds one from
# the other.
# --------------------------------------------------------------------------


class CreditBucket(models.TextChoices):
    ALLOWANCE = "allowance", "Pula planu"
    PURCHASED = "purchased", "Kredyty kupione"


class CreditLedgerKind(models.TextChoices):
    ALLOWANCE_GRANTED = "allowance_granted", "Przyznano pulę planu"
    ALLOWANCE_EXPIRED = "allowance_expired", "Wygasła pula planu"
    PURCHASED = "purchased", "Zakup kredytów"
    CONSUMED = "consumed", "Zużycie"
    REFUNDED = "refunded", "Zwrot zużycia"
    OPERATOR_ADJUSTMENT = "operator_adjustment", "Korekta operatora"


class CreditReservationState(models.TextChoices):
    RESERVED = "reserved", "Zarezerwowane"
    COMMITTED = "committed", "Rozliczone"
    RELEASED = "released", "Zwolnione"


class CreditPurchaseStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    SUCCEEDED = "succeeded", "Opłacony"
    FAILED = "failed", "Nieudany"
    CANCELED = "canceled", "Anulowany"


class CreditPack(models.Model):
    """A pack of credits offered for sale, priced like a plan version."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    credits = models.PositiveBigIntegerField()
    currency = models.CharField(
        max_length=3,
        default="PLN",
        validators=[RegexValidator(r"^[A-Z]{3}$", "Waluta musi być kodem ISO 4217.")],
    )
    unit_amount_minor = models.PositiveBigIntegerField()
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("credits", "key")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(credits__gt=0), name="billing_credit_pack_credits_ck"
            )
        ]

    def __str__(self) -> str:
        return self.key


class CreditPackPrice(models.Model):
    """A pack's price in Stripe, mirroring StripePriceMapping for plans.

    Deliberately a separate table rather than a nullable target on
    StripePriceMapping: a subscription and a checkout both point at a plan
    mapping, and a shared table would make "subscription priced as a credit
    pack" a state the schema allows. The `livemode` flag is the same safety
    check — a test-mode price must never be usable by a live deployment, even
    if somebody restores the wrong database.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    pack = models.ForeignKey(
        "CreditPack",
        on_delete=models.PROTECT,
        related_name="stripe_prices",
    )
    stripe_product_id = models.CharField(max_length=160)
    stripe_price_id = models.CharField(max_length=160, unique=True)
    livemode = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("pack__credits", "livemode")
        constraints = [
            models.UniqueConstraint(
                fields=["pack", "livemode"],
                condition=models.Q(is_active=True),
                name="billing_active_price_pack_mode_uq",
            )
        ]

    def __str__(self) -> str:
        return self.stripe_price_id


class CreditOperation(models.Model):
    """What one metered operation costs, in credits.

    The price is mutable catalog data, so the ledger records the cost that
    applied at the time. A later change never rewrites what somebody was
    already charged.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    key = models.CharField(max_length=100, unique=True, validators=[CATALOG_KEY_VALIDATOR])
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    cost = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key",)

    def __str__(self) -> str:
        return f"{self.key}={self.cost}"


class CreditBalance(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    allowance_remaining = models.PositiveBigIntegerField(default=0)
    allowance_reserved = models.PositiveBigIntegerField(default=0)
    #: What the plan granted for the current period. Kept so a mid-month
    #: upgrade tops the allowance up instead of waiting for the next month.
    allowance_granted = models.PositiveBigIntegerField(default=0)
    allowance_period_start = models.DateField(null=True, blank=True)
    allowance_period_end = models.DateField(null=True, blank=True)
    purchased_remaining = models.PositiveBigIntegerField(default=0)
    purchased_reserved = models.PositiveBigIntegerField(default=0)
    version = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id",)
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="billing_credit_balance_org_uq"),
            models.CheckConstraint(
                condition=models.Q(allowance_reserved__lte=models.F("allowance_remaining")),
                name="billing_credit_allowance_reserved_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(purchased_reserved__lte=models.F("purchased_remaining")),
                name="billing_credit_purchased_reserved_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(allowance_period_end__isnull=True)
                | models.Q(allowance_period_start__isnull=False),
                name="billing_credit_allowance_window_ck",
            ),
        ]

    @property
    def available(self) -> int:
        return (self.allowance_remaining - self.allowance_reserved) + (
            self.purchased_remaining - self.purchased_reserved
        )


class CreditPurchase(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    pack = models.ForeignKey(CreditPack, on_delete=models.PROTECT, related_name="purchases")
    credits = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    unit_amount_minor = models.PositiveBigIntegerField()
    status = models.CharField(
        max_length=16, choices=CreditPurchaseStatus, default=CreditPurchaseStatus.PENDING
    )
    checkout_session_id = models.CharField(max_length=160, blank=True)
    checkout_url = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=160, blank=True)
    idempotency_key = models.CharField(max_length=120)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="billing_credit_purchase_key_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(credits__gt=0), name="billing_credit_purchase_credits_ck"
            ),
        ]


class CreditReservation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    idempotency_key = models.CharField(max_length=120)
    operation_key = models.CharField(max_length=100)
    cost = models.PositiveIntegerField()
    allowance_amount = models.PositiveIntegerField(default=0)
    purchased_amount = models.PositiveIntegerField(default=0)
    state = models.CharField(
        max_length=16, choices=CreditReservationState, default=CreditReservationState.RESERVED
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="billing_credit_reservation_key_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(cost__gt=0), name="billing_credit_reservation_cost_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    cost=models.F("allowance_amount") + models.F("purchased_amount")
                ),
                name="billing_credit_reservation_split_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "state", "expires_at"],
                name="bill_credit_res_state_idx",
            )
        ]


class CreditLedgerEntry(TenantScopedModel):
    """Append-only record of every credit that moved, and why."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    kind = models.CharField(max_length=24, choices=CreditLedgerKind)
    bucket = models.CharField(max_length=16, choices=CreditBucket)
    amount = models.BigIntegerField()
    balance_after = models.PositiveBigIntegerField()
    operation_key = models.CharField(max_length=100, blank=True)
    operation_cost = models.PositiveIntegerField(null=True, blank=True)
    reservation = models.ForeignKey(
        CreditReservation,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    purchase = models.ForeignKey(
        CreditPurchase,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    reason = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="credit_ledger_entries",
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=120, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "occurred_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="billing_credit_ledger_amount_ck"
            ),
            # One operation can move both buckets, so the key identifies the
            # movement per bucket rather than per operation.
            models.UniqueConstraint(
                fields=["organization", "kind", "bucket", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="billing_credit_ledger_key_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "occurred_at"],
                name="bill_credit_ledger_time_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        reservation = self.reservation
        if reservation is not None and reservation.organization_id != self.organization_id:
            raise ValidationError({"reservation": "Rezerwacja należy do innej organizacji."})
        purchase = self.purchase
        if purchase is not None and purchase.organization_id != self.organization_id:
            raise ValidationError({"purchase": "Zakup należy do innej organizacji."})
