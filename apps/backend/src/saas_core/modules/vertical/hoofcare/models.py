from __future__ import annotations

import uuid

from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


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
