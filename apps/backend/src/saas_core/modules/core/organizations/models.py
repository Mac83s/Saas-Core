from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class OrganizationStatus(models.TextChoices):
    ONBOARDING = "onboarding", "W trakcie konfiguracji"
    ACTIVE = "active", "Aktywna"
    SUSPENDED = "suspended", "Zawieszona"
    ARCHIVED = "archived", "Zarchiwizowana"


class WorkspaceKind(models.TextChoices):
    PERSONAL = "personal", "Osobista"
    BUSINESS = "business", "Firmowa"


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    slug = models.SlugField(
        max_length=80,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
                message="Slug może zawierać małe litery, cyfry i pojedyncze łączniki.",
            )
        ],
    )
    workspace_kind = models.CharField(
        max_length=16,
        choices=WorkspaceKind,
        default=WorkspaceKind.BUSINESS,
    )
    status = models.CharField(
        max_length=16,
        choices=OrganizationStatus,
        default=OrganizationStatus.ONBOARDING,
    )
    default_locale = models.CharField(
        max_length=10,
        choices=[("pl", "Polski"), ("en", "English")],
        default="pl",
    )
    timezone = models.CharField(max_length=64, default="Europe/Warsaw")
    currency = models.CharField(
        max_length=3,
        default="PLN",
        validators=[RegexValidator(r"^[A-Z]{3}$", "Waluta musi być kodem ISO 4217.")],
    )
    version = models.PositiveBigIntegerField(default=1)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("slug"), name="organizations_slug_ci_unique"),
            models.CheckConstraint(
                condition=(
                    models.Q(status=OrganizationStatus.ARCHIVED, archived_at__isnull=False)
                    | (
                        ~models.Q(status=OrganizationStatus.ARCHIVED)
                        & models.Q(archived_at__isnull=True)
                    )
                ),
                name="organizations_archived_at_status_ck",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.strip().lower()
        self.currency = self.currency.strip().upper()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        self.slug = self.slug.strip().lower()
        self.currency = self.currency.strip().upper()
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValidationError({"timezone": "Nieznana strefa czasowa."}) from error

    def archive(self) -> None:
        if self.status != OrganizationStatus.ARCHIVED:
            self.status = OrganizationStatus.ARCHIVED
            self.archived_at = timezone.now()
            self.version += 1
            self.save(update_fields=["status", "archived_at", "version", "updated_at"])


class RoleScope(models.TextChoices):
    SYSTEM = "system", "Systemowa"
    ORGANIZATION = "organization", "Organizacyjna"


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="roles",
        null=True,
        blank=True,
    )
    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=80)
    scope = models.CharField(max_length=16, choices=RoleScope)
    permissions = models.JSONField(default=list)
    is_immutable = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scope", "key")
        constraints = [
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(organization__isnull=True),
                name="organizations_role_system_key_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "key"],
                condition=models.Q(organization__isnull=False),
                name="organizations_role_org_key_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope=RoleScope.SYSTEM, organization__isnull=True, is_immutable=True)
                    | models.Q(scope=RoleScope.ORGANIZATION, organization__isnull=False)
                ),
                name="organizations_role_scope_org_ck",
            ),
        ]

    def __str__(self) -> str:
        return self.key

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.permissions, list) or not all(
            isinstance(permission, str) and permission for permission in self.permissions
        ):
            raise ValidationError({"permissions": "Permissions muszą być listą kluczy."})
        if len(self.permissions) != len(set(self.permissions)):
            raise ValidationError({"permissions": "Permission nie może się powtarzać."})


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", "Aktywne"
    SUSPENDED = "suspended", "Zawieszone"
    REVOKED = "revoked", "Odebrane"
    LEFT = "left", "Zakończone przez użytkownika"


class Membership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(
        max_length=16, choices=MembershipStatus, default=MembershipStatus.ACTIVE
    )
    joined_at = models.DateTimeField(default=timezone.now)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_memberships",
        null=True,
        blank=True,
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization_id", "user_id", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                condition=models.Q(
                    status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED]
                ),
                name="organizations_membership_current_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=[MembershipStatus.REVOKED, MembershipStatus.LEFT],
                        revoked_at__isnull=False,
                    )
                    | (
                        models.Q(status__in=[MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED])
                        & models.Q(revoked_at__isnull=True)
                    )
                ),
                name="organizations_membership_revoked_at_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="org_membership_status_idx")
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.user_id}:{self.role.key}"

    def clean(self) -> None:
        super().clean()
        if self.role_id and self.role.organization_id not in (None, self.organization_id):
            raise ValidationError({"role": "Rola należy do innej organizacji."})


class BillingCustomerKind(models.TextChoices):
    PERSON = "person", "Osoba"
    COMPANY = "company", "Firma"


class BillingProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        related_name="billing_profile",
    )
    customer_kind = models.CharField(
        max_length=16,
        choices=BillingCustomerKind,
        default=BillingCustomerKind.COMPANY,
    )
    legal_name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(max_length=32, blank=True)
    country_code = models.CharField(
        max_length=2, default="PL", validators=[RegexValidator(r"^[A-Z]{2}$")]
    )
    address_line1 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    city = models.CharField(max_length=120, blank=True)
    billing_email = models.EmailField(blank=True)
    external_customer_id = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["external_customer_id"],
                condition=~models.Q(external_customer_id=""),
                name="org_billing_external_customer_uq",
            )
        ]

    def __str__(self) -> str:
        return str(self.organization_id)


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Oczekuje"
    ACCEPTED = "accepted", "Przyjęte"
    REVOKED = "revoked", "Wycofane"


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="invitations",
    )
    email = models.EmailField(max_length=254)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="invitations")
    status = models.CharField(
        max_length=16,
        choices=InvitationStatus,
        default=InvitationStatus.PENDING,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_organization_invitations",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_organization_invitations",
        null=True,
        blank=True,
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                "organization",
                condition=models.Q(status=InvitationStatus.PENDING),
                name="org_invite_pending_email_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=InvitationStatus.PENDING,
                        accepted_at__isnull=True,
                        accepted_by__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | models.Q(
                        status=InvitationStatus.ACCEPTED,
                        accepted_at__isnull=False,
                        accepted_by__isnull=False,
                        revoked_at__isnull=True,
                    )
                    | models.Q(
                        status=InvitationStatus.REVOKED,
                        accepted_at__isnull=True,
                        accepted_by__isnull=True,
                        revoked_at__isnull=False,
                    )
                ),
                name="org_invite_terminal_state_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "expires_at"],
                name="org_invite_status_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.email}:{self.status}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = self.email.strip().casefold()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        self.email = self.email.strip().casefold()
        if self.role_id and self.role.organization_id not in (None, self.organization_id):
            raise ValidationError({"role": "Rola należy do innej organizacji."})

    def is_usable(self, *, at: datetime | None = None) -> bool:
        checked_at = at or timezone.now()
        return self.status == InvitationStatus.PENDING and self.expires_at > checked_at


class OrganizationAuditAction(models.TextChoices):
    ORGANIZATION_CREATED = "organization.created", "Utworzono organizację"
    ORGANIZATION_UPDATED = "organization.updated", "Zmieniono organizację"
    ORGANIZATION_ARCHIVED = "organization.archived", "Zarchiwizowano organizację"
    INVITATION_CREATED = "invitation.created", "Utworzono zaproszenie"
    INVITATION_REVOKED = "invitation.revoked", "Wycofano zaproszenie"
    INVITATION_ACCEPTED = "invitation.accepted", "Przyjęto zaproszenie"
    MEMBERSHIP_ROLE_CHANGED = "membership.role_changed", "Zmieniono rolę członka"
    MEMBERSHIP_SUSPENDED = "membership.suspended", "Zawieszono członka"
    MEMBERSHIP_RESUMED = "membership.resumed", "Wznowiono członka"
    MEMBERSHIP_REVOKED = "membership.revoked", "Odebrano dostęp członkowi"
    MEMBERSHIP_LEFT = "membership.left", "Członek opuścił organizację"
    OWNERSHIP_TRANSFERRED = "ownership.transferred", "Przeniesiono własność"
    BILLING_CHECKOUT_CREATED = "billing.checkout.created", "Utworzono Checkout"
    BILLING_PORTAL_CREATED = "billing.portal.created", "Utworzono sesję portalu"
    BILLING_TRIAL_STARTED = "billing.trial.started", "Rozpoczęto trial"
    BILLING_ACCESS_READ_ONLY = "billing.access.read_only", "Włączono tryb tylko do odczytu"


class OrganizationAuditEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_audit_entries",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=64, choices=OrganizationAuditAction)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    correlation_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(
                fields=["organization", "occurred_at"],
                name="org_audit_occurred_idx",
            ),
            models.Index(
                fields=["organization", "action", "occurred_at"],
                name="org_audit_action_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}:{self.action}:{self.id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError("Wpis audytu jest append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValidationError("Wpis audytu jest append-only.")
