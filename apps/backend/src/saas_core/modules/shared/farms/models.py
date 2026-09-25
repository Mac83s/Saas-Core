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
    #: A company wrote this animal into the register and the keeper has not
    #: looked at it yet. Nothing is ever deleted here — the keeper decides.
    review_requested_at = models.DateTimeField(null=True, blank=True)
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


class HealthEntryKind(models.TextChoices):
    """What kind of thing happened. Deliberately about animals, not about a
    trade: a vertical says what it did in `source` and `details`, and the
    register renders the kind (ADR-049)."""

    NOTE = "note", "Notatka"
    ALERT = "alert", "Uwaga"
    TREATMENT = "treatment", "Zabieg"
    MEDICATION = "medication", "Lek lub szczepienie"
    VISIT = "visit", "Wizyta specjalisty"


class AnimalHealthEntry(TenantScopedModel):
    """What happened to one animal, in the register that keeps its history.

    The register is the farmer's; a service company publishes into it through
    the share the farmer granted (ADR-051 pt 8), so an animal keeps its history
    across companies and, later, across farms. The entry is the summary a
    keeper reads — the company's own record stays in its vertical, in the
    detail that vertical needs.
    """

    #: Whether the author is another organization, as the reader sees it.
    #: Filled by the use case for the API; never stored.
    author_is_external: bool = False

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    animal = models.ForeignKey(Animal, on_delete=models.PROTECT, related_name="health_entries")
    kind = models.CharField(max_length=16, choices=HealthEntryKind, default=HealthEntryKind.NOTE)
    occurred_on = models.DateField()
    #: Which vertical wrote it, e.g. "hoofcare.visit".
    source = models.CharField(max_length=32)
    #: The entry's identity in that vertical, so publishing twice is one row.
    source_reference = models.CharField(max_length=64)
    #: Who did the work, as the keeper would name them: the person when the
    #: writer knows them, the company otherwise.
    author_name = models.CharField(max_length=160, blank=True)
    author_organization_id = models.UUIDField(null=True, blank=True)
    #: Copied, not looked up: no tenant reads another tenant's organization row,
    #: and a history wants the name from the day of the entry.
    author_organization_name = models.CharField(max_length=160, blank=True)
    #: The keeper's own entry, kept out of what a company reads through a share.
    private = models.BooleanField(default=False)
    #: Identifiers of the author's own media. The file stays in the author's
    #: storage and the reader is let in through this entry — a copy per company
    #: serving the same farm would multiply the same photo for nothing, and a
    #: photo the author deletes has to disappear (decision of 20.09).
    photos = models.JSONField(default=list)
    summary = models.CharField(max_length=240)
    #: Structured detail the panel renders; shape belongs to the source.
    details = models.JSONField(default=dict)
    #: A medicine's withdrawal period: until when milk and meat of the animal
    #: may not be sold. The animal is "in withdrawal" while any entry still
    #: runs — computed from the entries, not a flag somebody has to clear.
    withdrawal_milk_until = models.DateTimeField(null=True, blank=True)
    withdrawal_meat_until = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-occurred_on", "-published_at")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "animal", "source", "source_reference"],
                name="farms_health_source_uq",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "animal"], name="farms_health_animal_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.occurred_on}: {self.summary}"


class VisitStatus(models.TextChoices):
    PLANNED = "planned", "Zaplanowana"
    DONE = "done", "Odbyta"
    CANCELED = "canceled", "Odwołana"


class FarmVisitEntry(TenantScopedModel):
    """A company's visit to this farm, in the register the keeper reads.

    The company's own record of the visit stays in its vertical, with the detail
    that vertical needs (ADR-052). This is the part the keeper is entitled to:
    when somebody is coming, when they came, and what the report said.

    It carries a *planned* date, which no other published row can: a health
    entry needs an animal and a day in the past, and at planning time a visit
    knows neither. Cancelling does not delete the row — a visit that was called
    off is a fact the keeper may remember.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="visit_entries")
    #: Which vertical wrote it, e.g. "hoofcare.visit".
    source = models.CharField(max_length=32)
    #: The visit's identity in that vertical, so publishing twice is one row.
    source_reference = models.CharField(max_length=64)
    #: Not a foreign key, for the same reason `AnimalHealthEntry` keeps its
    #: author that way: a key to Organization would put rows in somebody else's
    #: tenant inside the company's erasure.
    company_organization_id = models.UUIDField()
    company_name = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=10, choices=VisitStatus.choices)
    #: When somebody is coming. Set while the visit is still ahead.
    scheduled_for = models.DateTimeField(null=True, blank=True)
    #: The day it happened. Set when the report is sent.
    occurred_on = models.DateField(null=True, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    #: The report as the keeper reads it: the vertical resolves its own codes
    #: first, because the register may not import a vertical to do it here.
    details = models.JSONField(default=dict)
    published_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-scheduled_for", "-occurred_on")
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "farm",
                    "company_organization_id",
                    "source",
                    "source_reference",
                ],
                name="farms_visit_source_uq",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "farm"], name="farms_visit_farm_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.scheduled_for or self.occurred_on}: {self.summary}"


class ShareBasis(models.TextChoices):
    ACTIVATION_CODE = "activation_code", "Kod aktywacji od firmy"
    SUPPORT = "support", "Połączenie przez obsługę platformy"


class ShareStatus(models.TextChoices):
    ACTIVE = "active", "Aktywny"
    REVOKED = "revoked", "Cofnięty"


class FarmActivationCode(models.Model):
    """A one-time code for one farm card; only its digest is stored.

    The code carries the handover itself — the card's public fields, its animals
    and the company's name — because the farmer redeems it inside their own
    tenant, where row-level security hides the company's rows. Copying at issue
    time also makes the handover what the company agreed to give, frozen.
    """

    token_digest = models.CharField(max_length=64, primary_key=True)
    company_organization_id = models.UUIDField()
    company_name = models.CharField(max_length=160, blank=True)
    handover = models.JSONField(default=dict)
    farm_id = models.UUIDField()
    created_by_id = models.UUIDField(null=True, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by_organization_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["farm_id", "used_at"], name="farms_code_farm_idx"),
        ]

    def __str__(self) -> str:
        return str(self.farm_id)


class FarmShare(models.Model):
    """What one company may do with one farm of the register, and since when."""

    #: Who the other side is, as the caller sees it. Derived by `list_shares`
    #: from the names below; never stored.
    partner_name: str = ""
    partner_is_company: bool = False

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    registry_organization_id = models.UUIDField()
    registry_farm_id = models.UUIDField()
    company_organization_id = models.UUIDField()
    company_farm_id = models.UUIDField()
    #: Both names are copied here: neither side may read the other's
    #: organization row, and a handover is a record of who it was with.
    company_name = models.CharField(max_length=160, blank=True)
    registry_name = models.CharField(max_length=160, blank=True)
    #: The company writes herd changes straight into the register (ADR-051 pt 7).
    can_write_herd = models.BooleanField(default=True)
    #: Its visits and their reports reach the farm's register (ADR-052). Off by
    #: default: a future date is something no share sent before, so consenting
    #: to health entries is not consenting to the company's schedule.
    can_publish_schedule = models.BooleanField(default=False)
    #: Its health entries are copied to the animal's history (ADR-051 pt 8).
    can_publish_health = models.BooleanField(default=True)
    basis = models.CharField(max_length=20, choices=ShareBasis)
    status = models.CharField(max_length=10, choices=ShareStatus, default=ShareStatus.ACTIVE)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("registry_organization_id", "-granted_at")
        constraints = [
            models.UniqueConstraint(
                fields=["registry_farm_id", "company_farm_id"], name="farms_share_pair_uq"
            )
        ]
        indexes = [
            models.Index(fields=["registry_organization_id"], name="farms_share_registry_idx"),
            models.Index(fields=["company_organization_id"], name="farms_share_company_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.registry_farm_id} ↔ {self.company_farm_id}"
