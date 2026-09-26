from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class AppointmentStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Potwierdzona"
    COMPLETED = "completed", "Zakończona"
    CANCELED = "canceled", "Anulowana"
    NO_SHOW = "no_show", "Nieobecność"


class Location(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    public_slug = models.SlugField(max_length=80)
    address = models.CharField(max_length=240, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "public_slug"], name="booking_location_org_slug_uq"
            )
        ]


class StaffMember(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    display_name = models.CharField(max_length=160)
    public_slug = models.SlugField(max_length=80)
    #: The team member's account, when the person in the calendar also logs in.
    #: That is what makes "my visits" computable; a calendar entry for someone
    #: without an account (a subcontractor) simply has none.
    membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    #: Internal contact: management and the person see it, nobody else (ADR-058 §1).
    phone = models.CharField(max_length=40, blank=True)
    #: The invitation of a person added with an e-mail: accepting it links the
    #: account to this entry, so the office's name and hours stay (ADR-058 §1).
    invitation = models.ForeignKey(
        "organizations.Invitation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "display_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "public_slug"], name="booking_staff_org_slug_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "membership"],
                condition=models.Q(membership__isnull=False),
                name="booking_staff_org_membership_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "invitation"],
                condition=models.Q(invitation__isnull=False),
                name="booking_staff_org_invitation_uq",
            ),
        ]


class Resource(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=80, default="generic")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")


class Service(TenantScopedModel):
    """One sellable service, and optionally the kind of visit it is.

    `appointment_kind` is how a vertical says "an appointment for this service
    carries my detail row": it holds a key from `settings.APPOINTMENT_KINDS`,
    which the deployment composes from its modules. Booking does not know what
    any key means, only that a service may name one and that the name has to
    come from a module this product actually has. Empty is the normal case —
    a plain appointment needs no extension.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    public_slug = models.SlugField(max_length=80)
    appointment_kind = models.CharField(max_length=64, blank=True)
    duration_minutes = models.PositiveSmallIntegerField()
    buffer_before_minutes = models.PositiveSmallIntegerField(default=0)
    buffer_after_minutes = models.PositiveSmallIntegerField(default=0)
    minimum_notice_minutes = models.PositiveIntegerField(default=60)
    #: Produkty z magazynu, które wizyta tej usługi zabiera (ADR-055):
    #: `[{"item_id", "quantity", "mode": "consume" | "sale"}]`. Magazyn nie
    #: jest zależnością rezerwacji, więc bez kluczy obcych — sprawdza je
    #: `materials.py`, gdy moduł magazynu jest w profilu.
    materials = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "public_slug"], name="booking_service_org_slug_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gte=5, duration_minutes__lte=1440),
                name="booking_service_duration_ck",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.appointment_kind and self.appointment_kind not in settings.APPOINTMENT_KINDS:
            available = ", ".join(sorted(settings.APPOINTMENT_KINDS)) or "brak"
            raise ValidationError({
                "appointment_kind": (
                    f"Nieznany rodzaj wizyty '{self.appointment_kind}'. "
                    f"Ten deployment składa: {available}."
                )
            })


class ServiceStaff(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="staff_links")
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name="service_links")
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "service", "staff"], name="booking_service_staff_uq"
            )
        ]


class ServiceLocation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="location_links")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="service_links")
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "service", "location"], name="booking_service_location_uq"
            )
        ]


class ServiceResource(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="resource_links")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="service_links")
    required = models.BooleanField(default=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "service", "resource"], name="booking_service_resource_uq"
            )
        ]


class AvailabilityRule(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    staff = models.ForeignKey(
        StaffMember, on_delete=models.PROTECT, related_name="availability_rules"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="availability_rules"
    )
    weekday = models.PositiveSmallIntegerField()
    local_start = models.TimeField()
    local_end = models.TimeField()
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "staff_id", "weekday", "local_start")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0, weekday__lte=6),
                name="booking_availability_weekday_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(local_end__gt=models.F("local_start")),
                name="booking_availability_time_ck",
            ),
        ]


class TimeOff(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    staff = models.ForeignKey(
        StaffMember, null=True, blank=True, on_delete=models.PROTECT, related_name="time_off"
    )
    resource = models.ForeignKey(
        Resource, null=True, blank=True, on_delete=models.PROTECT, related_name="time_off"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "starts_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="booking_timeoff_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(staff__isnull=False) | models.Q(resource__isnull=False),
                name="booking_timeoff_target_ck",
            ),
        ]


class Customer(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    display_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    contact_hash = models.CharField(max_length=64)
    locale = models.CharField(
        max_length=10, choices=(("pl", "Polski"), ("en", "English")), default="pl"
    )
    anonymized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at", "id")
        indexes = [
            models.Index(
                fields=["organization", "contact_hash"], name="booking_customer_contact_idx"
            )
        ]


class Appointment(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="appointments")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="appointments")
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name="appointments")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="appointments")
    resource = models.ForeignKey(
        Resource, null=True, blank=True, on_delete=models.PROTECT, related_name="appointments"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    occupied_from = models.DateTimeField()
    occupied_until = models.DateTimeField()
    timezone = models.CharField(max_length=64)
    service_name = models.CharField(max_length=160)
    #: Produkty tej wizyty: kopia z usługi albo wpisane ręcznie, z nazwą i
    #: ceną z chwili zapisu. Stan jest zarezerwowany do zakończenia wizyty.
    materials = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16, choices=AppointmentStatus, default=AppointmentStatus.CONFIRMED
    )
    self_service_token_ciphertext = models.TextField()
    self_service_expires_at = models.DateTimeField()
    reminder_due_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "starts_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="booking_appointment_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(occupied_until__gt=models.F("occupied_from")),
                name="booking_appointment_occupied_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "starts_at", "status"], name="booking_appt_calendar_idx"
            )
        ]


class AppointmentStatusHistory(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.PROTECT, related_name="status_history"
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=AppointmentStatus)
    reason = models.CharField(max_length=240, blank=True)
    actor_kind = models.CharField(max_length=24)
    occurred_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "appointment_id", "occurred_at", "id")


class AppointmentStaffAllocation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.PROTECT, related_name="staff_allocations"
    )
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT)
    occupied_range = DateTimeRangeField()
    active = models.BooleanField(default=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="booking_staff_no_overlap_excl",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("staff", RangeOperators.EQUAL),
                    ("occupied_range", RangeOperators.OVERLAPS),
                ],
                condition=models.Q(active=True),
            ),
        ]


class AppointmentResourceAllocation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.PROTECT, related_name="resource_allocations"
    )
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT)
    occupied_range = DateTimeRangeField()
    active = models.BooleanField(default=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="booking_resource_no_overlap_excl",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("resource", RangeOperators.EQUAL),
                    ("occupied_range", RangeOperators.OVERLAPS),
                ],
                condition=models.Q(active=True),
            ),
        ]


class BookingMutation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    appointment = models.ForeignKey(Appointment, on_delete=models.PROTECT, related_name="mutations")
    action = models.CharField(max_length=24)
    principal_ref = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "action", "principal_ref", "idempotency_key"],
                name="booking_mutation_idem_uq",
            )
        ]


class PublicBookingRoute(models.Model):
    public_slug = models.SlugField(max_length=100, unique=True)
    organization_id = models.UUIDField(unique=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.public_slug


class SelfServiceRoute(models.Model):
    token_digest = models.CharField(max_length=64, primary_key=True)
    organization_id = models.UUIDField()
    appointment_id = models.UUIDField(unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.appointment_id)


class ReminderRoute(models.Model):
    appointment_id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    signed_tenant_context = models.TextField()
    due_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.appointment_id)


def validate_same_tenant(instance: Any, *related_names: str) -> None:
    for name in related_names:
        related = getattr(instance, name, None)
        if related is not None and related.organization_id != instance.organization_id:
            raise ValidationError({name: "Powiązany rekord należy do innej organizacji."})
