from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class AppointmentStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Potwierdzona"
    COMPLETED = "completed", "Zakończona"
    CANCELED = "canceled", "Anulowana"
    NO_SHOW = "no_show", "Nieobecność"


class StaffChoice(models.TextChoices):
    """What a customer may pick on the public form (ADR-058 §8, answer 2)."""

    NONE = "none", "Nikogo"
    TEAM = "team", "Zespół"
    PERSON = "person", "Osobę"


class QueueReason(models.TextChoices):
    """Why a visit waits in „Do przydzielenia” (ADR-058 §3)."""

    PUBLIC = "public", "Rezerwacja ze strony"
    MOVED = "moved", "Klient przełożył wizytę"
    TIME_OFF = "time_off", "Nieobecność"
    ENDED = "ended", "Odejście z firmy"
    SHORT = "short", "Za mało osób"
    JOINED = "joined", "Osoba dołączyła do innej wizyty"


class Location(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    public_slug = models.SlugField(max_length=80)
    address = models.CharField(max_length=240, blank=True)
    active = models.BooleanField(default=True)
    #: Bumped by every setup write that changes the place (ADR-072 §11).
    version = models.PositiveIntegerField(default=1)
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
    #: „Pokazuj klientom”: the person's public profile, the only way a
    #: customer learns a name (ADR-036 §4, ADR-058 §8). None = internal only.
    profile = models.ForeignKey(
        "profiles.PublicProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    active = models.BooleanField(default=True)
    #: The person's week as one setup item: bumped by every change of the
    #: hours, and only by that, so editing a team never stales a week someone
    #: has open (ADR-072 §11).
    hours_version = models.PositiveIntegerField(default=1)
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


class StaffTeam(TenantScopedModel):
    """A standing group of people, e.g. a crew that drives out together.

    Choosing a team for a visit takes as many of its free members as the
    service needs (ADR-058 §2). Changing a team never touches booked visits.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            # Customers pick a team by its name, so two teams may not share one.
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="booking_team_org_name_uq"
            ),
        ]


class StaffTeamMember(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    team = models.ForeignKey(StaffTeam, on_delete=models.CASCADE, related_name="members")
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name="team_links")
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "staff"], name="booking_team_member_uq"),
        ]


class Resource(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=80, default="generic")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
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
    #: How many people one visit needs; each of them has the time blocked
    #: (ADR-058 §2). A visit keeps the number it was booked with.
    staff_count = models.PositiveSmallIntegerField(default=1)
    #: What the public form asks: nobody, a team, or a person — a person only
    #: when one does the visit (answer 2, 24.09).
    public_staff_choice = models.CharField(
        max_length=8, choices=StaffChoice, default=StaffChoice.NONE
    )
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
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
            models.CheckConstraint(
                condition=models.Q(staff_count__gte=1, staff_count__lte=10),
                name="booking_service_staff_count_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(public_staff_choice=StaffChoice.PERSON)
                | models.Q(staff_count=1),
                name="booking_service_person_choice_ck",
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
    #: A content language from the company's list (ADR-071 pkt 21).
    locale = models.CharField(max_length=10, default="pl")
    anonymized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="booking_customer_locale_format_ck",
            ),
        ]
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
    #: The people the visit was booked for (the service's number then): a
    #: later change of the service does not rewrite a booked visit.
    staff_required = models.PositiveSmallIntegerField(default=1)
    #: A vacancy: fewer active people than required, or the lead has none
    #: (absence, leaving, too few people) — ADR-058 §3.
    needs_assignment = models.BooleanField(default=False)
    #: The system chose the people and nobody from the company has looked yet.
    auto_assigned = models.BooleanField(default=False)
    #: Bumped by every change of the people; an assignment names the version it
    #: saw, so two offices cannot overwrite each other (ADR-058 §9).
    crew_version = models.PositiveIntegerField(default=0)
    #: The customer's choice on the public form, kept for the queue and for
    #: the customer's own rescheduling.
    requested_team = models.ForeignKey(
        "StaffTeam", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    requested_staff = models.ForeignKey(
        StaffMember, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    queue_reason = models.CharField(max_length=16, choices=QueueReason, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    #: What the customer wrote („Uwagi”, answer 1A of 28.09). It may be health
    #: data: shown in the panel with the visit, never in an e-mail, a log or the
    #: history of changes; anonymization clears it.
    customer_notes = models.CharField(max_length=500, blank=True)
    #: „Miejsce wizyty” (owner's decision 14a, 02.10): where the visit takes
    #: place when that is not the company's location — a town, and optionally
    #: a street and number. Empty: a module may still say (places.py).
    place_town = models.CharField(max_length=120, blank=True)
    place_address = models.CharField(max_length=240, blank=True)
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
            ),
            models.Index(
                fields=["organization", "starts_at"],
                condition=models.Q(needs_assignment=True) | models.Q(auto_assigned=True),
                name="booking_appt_queue_idx",
            ),
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


class BookingSetupMutation(TenantScopedModel):
    """The receipt of a setup write (ADR-072 §11): the same key again gets the
    first answer back instead of a second service. `BookingMutation` points at
    a visit, so setup keeps its own. The item the write made or changed is
    named by kind and id: one receipt table serves four kinds of item.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: `service.create`, `service.update`, `location.create`, `location.update`,
    #: `resource.create`, `resource.update`, `staff.hours.set`.
    action = models.CharField(max_length=40)
    principal_ref = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    result_kind = models.CharField(max_length=24)
    result_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "action", "principal_ref", "idempotency_key"],
                name="booking_setup_mutation_idem_uq",
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
