from __future__ import annotations

import uuid

from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel
from saas_core.modules.shared.booking.api import APPOINTMENT_MODEL


class AnimalStatus(models.TextChoices):
    ACTIVE = "active", "W stadzie"
    SOLD = "sold", "Sprzedane"
    CULLED = "culled", "Wybrakowane"
    DEAD = "dead", "Padłe"


class Farm(TenantScopedModel):
    """A customer's farm — the place a trimmer drives to, not a company location.

    `shared.booking` already owns `Location`, but that is where the company
    provides a service from. Hoof trimming happens at the client's premises, and
    a farm carries things a booking location has no reason to know: how the herd
    is housed, who keeps it, how many animals stand there.

    Linking a farm to `booking.Customer` waits until visits arrive: booking has
    no `api.py` yet, and reaching into another module's models is what the module
    contract forbids.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    village = models.CharField(max_length=120, blank=True)
    address = models.CharField(max_length=240, blank=True)
    keeper_name = models.CharField(max_length=160, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    housing = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="hoofcare_farm_org_name_uq"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Animal(TenantScopedModel):
    """One animal in a herd.

    The national identifier is the one printed on the ear tag and is what a
    trimmer reads or scans in the barn. It is unique within a farm rather than
    within the organization: the same animal may be recorded again after moving
    between two farms the same company serves, and the herd it stood in at the
    time is part of the history.

    `working_number` is the short number a farm paints on the animal and calls it
    by; section 13.2 of the pre-implementation document requires both, because in
    the field people say the short one.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="animals")
    national_id = models.CharField(max_length=40)
    working_number = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=80, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=AnimalStatus.choices, default=AnimalStatus.ACTIVE
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "farm_id", "national_id")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "farm", "national_id"],
                name="hoofcare_animal_farm_tag_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "national_id"], name="hoofcare_animal_tag_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.national_id} ({self.name})" if self.name else self.national_id


class HerdVisit(TenantScopedModel):
    """A trimming visit: the detail an appointment for a herd carries.

    The appointment itself stays in `shared.booking` — slots, staff, the
    calendar and cancellation are solved there and a vertical has no business
    building a second one. What booking cannot know is which farm the trimmer
    drove to, when he walked into the barn and when he left it.

    The relation is one-to-one and the appointment is the parent: cancel the
    visit in the calendar and this row goes with it, never the other way round.
    `APPOINTMENT_KIND` is the key a service declares in
    `Service.appointment_kind` so the panel knows an appointment of that service
    is a herd visit.
    """

    APPOINTMENT_KIND = "hoofcare.herd_visit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    appointment = models.OneToOneField(
        APPOINTMENT_MODEL, on_delete=models.CASCADE, related_name="herd_visit"
    )
    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="visits")
    arrived_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(left_at__isnull=True)
                | models.Q(arrived_at__isnull=False),
                name="hoofcare_visit_left_needs_arrival_ck",
            )
        ]

    def __str__(self) -> str:
        # The related ids are not on the stub for a lazily referenced relation,
        # and loading the farm just to print a label would cost a query.
        return f"wizyta {self.pk}"
