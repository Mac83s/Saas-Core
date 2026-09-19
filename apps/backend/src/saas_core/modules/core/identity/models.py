from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone as django_timezone


class UserStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje na weryfikację"
    ACTIVE = "active", "Aktywny"
    SUSPENDED = "suspended", "Zawieszony"
    DISABLED = "disabled", "Wyłączony"


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        return super().normalize_email(email).strip().lower()

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> User:
        if not email:
            raise ValueError("Adres e-mail jest wymagany")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> User:
        extra_fields.setdefault("status", UserStatus.PENDING)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("status", UserStatus.ACTIVE)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser wymaga is_staff=True oraz is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    status = models.CharField(max_length=16, choices=UserStatus, default=UserStatus.PENDING)
    locale = models.CharField(max_length=10, default="pl")
    timezone = models.CharField(max_length=64, default="Europe/Warsaw")
    #: How the person is greeted and shown to a team ("Dzień dobry, Marcin",
    #: initials, who did the visit). Optional: an account starts with an e-mail.
    first_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=django_timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering = ("email",)
        constraints = [
            models.UniqueConstraint(Lower("email"), name="identity_user_email_ci_unique"),
            models.CheckConstraint(
                condition=(
                    models.Q(status=UserStatus.ACTIVE, is_active=True)
                    | (~models.Q(status=UserStatus.ACTIVE) & models.Q(is_active=False))
                ),
                name="identity_user_active_status_ck",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.email = type(self).objects.normalize_email(self.email)
        self.is_active = self.status == UserStatus.ACTIVE

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = type(self).objects.normalize_email(self.email)
        self.is_active = self.status == UserStatus.ACTIVE
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


class UserSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    session_key_hash = models.CharField(max_length=64, unique=True)
    device_label = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=django_timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-last_seen_at",)
        indexes = [
            models.Index(
                fields=["user", "revoked_at", "expires_at"],
                name="identity_session_user_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.id}"

    def is_valid(self, *, at: datetime | None = None) -> bool:
        checked_at = at or django_timezone.now()
        return self.revoked_at is None and self.expires_at > checked_at

    def revoke(self, *, at: datetime | None = None) -> None:
        if self.revoked_at is None:
            self.revoked_at = at or django_timezone.now()
            self.save(update_fields=["revoked_at"])


class OneTimeToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def is_usable(self, *, at: datetime | None = None) -> bool:
        checked_at = at or django_timezone.now()
        return self.used_at is None and self.expires_at > checked_at


class EmailVerification(OneTimeToken):
    email = models.EmailField(max_length=254)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "created_at"], name="identity_verify_user_idx"),
        ]

    def __str__(self) -> str:
        return str(self.id)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = User.objects.normalize_email(self.email)
        super().save(*args, **kwargs)


class PasswordReset(OneTimeToken):
    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "created_at"], name="identity_reset_user_idx"),
        ]

    def __str__(self) -> str:
        return str(self.id)


class LoginOutcome(models.TextChoices):
    SUCCESS = "success", "Sukces"
    MFA_REQUIRED = "mfa_required", "Wymagany drugi składnik"
    MFA_SETUP_REQUIRED = "mfa_setup", "Wymagana konfiguracja MFA"
    INVALID = "invalid", "Nieprawidłowe dane"
    INACTIVE = "inactive", "Konto nieaktywne"
    RATE_LIMITED = "rate_limited", "Limit prób"


class LoginAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="login_attempts",
        null=True,
        blank=True,
    )
    identifier_hash = models.CharField(max_length=64)
    ip_hash = models.CharField(max_length=64)
    outcome = models.CharField(max_length=16, choices=LoginOutcome)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["identifier_hash", "created_at"],
                name="identity_login_ident_idx",
            ),
            models.Index(fields=["ip_hash", "created_at"], name="identity_login_ip_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.outcome}:{self.id}"


class MfaMethodType(models.TextChoices):
    TOTP = "totp", "Aplikacja uwierzytelniająca"


class UserMfaMethod(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mfa_method")
    method_type = models.CharField(
        max_length=16,
        choices=MfaMethodType,
        default=MfaMethodType.TOTP,
    )
    secret_ciphertext = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_counter = models.BigIntegerField(default=-1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user_id",)

    def __str__(self) -> str:
        return f"{self.user_id}:{self.method_type}"

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class MfaRecoveryCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    method = models.ForeignKey(
        UserMfaMethod,
        on_delete=models.CASCADE,
        related_name="recovery_codes",
    )
    code_hash = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(
                fields=["method", "used_at"],
                name="identity_mfa_recovery_idx",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)


class AccountAuditEventType(models.TextChoices):
    EMAIL_VERIFIED = "email_verified", "Potwierdzono adres e-mail"
    PASSWORD_RESET = "password_reset", "Zmieniono hasło przez reset"
    MFA_ENABLED = "mfa_enabled", "Włączono MFA"
    SESSION_REVOKED = "session_revoked", "Unieważniono sesję"
    PROFILE_UPDATED = "profile_updated", "Zmieniono dane osobowe"


class AccountAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    event_type = models.CharField(max_length=32, choices=AccountAuditEventType)
    subject_user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="account_audit_events"
    )
    actor_user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="initiated_account_audit_events",
        null=True,
        blank=True,
    )
    correlation_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(
                fields=["subject_user", "occurred_at"],
                name="identity_audit_subject_idx",
            ),
            models.Index(
                fields=["event_type", "occurred_at"],
                name="identity_audit_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}:{self.subject_user_id}:{self.id}"
