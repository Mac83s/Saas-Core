"""The farm register (ADR-051): farms and the animals standing in them.

The same models serve both layers the ADR describes. In a service company's
organization a farm is that company's card of a client's farm; in a farmer's
organization (stage 3 of plan 15) it is the farmer's own register. Which one a
row is follows from the organization's type, not from a column here.
"""

from __future__ import annotations

import uuid

from django.db import models

from saas_core.modules.core.organizations.tenancy import TenantScopedModel


class AnimalStatus(models.TextChoices):
    ACTIVE = "active", "W stadzie"
    SOLD = "sold", "Sprzedane"
    CULLED = "culled", "Wybrakowane"
    DEAD = "dead", "Padłe"


class AnimalSex(models.TextChoices):
    FEMALE = "female", "Samica"
    MALE = "male", "Samiec"
    UNKNOWN = "unknown", "Nieznana"


class Farm(TenantScopedModel):
    """A farm: where the animals stand and whom it belongs to.

    `herd_number` is the official herd registration number (numer siedziby
    stada) — the identifier a farmer's own account is matched by when it joins
    (ADR-051). It is optional on a company's card, because a trimmer often
    learns it later, but unique within one organization when given.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    herd_number = models.CharField(max_length=20, blank=True)
    tax_id = models.CharField(max_length=10, blank=True)
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
            models.UniqueConstraint(fields=["organization", "name"], name="farms_farm_org_name_uq"),
            models.UniqueConstraint(
                fields=["organization", "herd_number"],
                condition=~models.Q(herd_number=""),
                name="farms_farm_org_herd_number_uq",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Animal(TenantScopedModel):
    """One animal, identified by species and the national identifier on its tag.

    Unique within a farm rather than within the organization: a company that
    serves both the seller and the buyer records the same animal at both farms,
    and the farm it stood in at the time is part of the history.
    `working_number` is the short number people call it by in the barn.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="animals")
    species = models.CharField(max_length=16, default="cattle")
    national_id = models.CharField(max_length=40)
    working_number = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=80, blank=True)
    sex = models.CharField(max_length=8, choices=AnimalSex.choices, default=AnimalSex.FEMALE)
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
                fields=["organization", "farm", "species", "national_id"],
                name="farms_animal_farm_tag_uq",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "species", "national_id"], name="farms_animal_tag_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.national_id} ({self.name})" if self.name else self.national_id
