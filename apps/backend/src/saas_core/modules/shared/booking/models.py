from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.timezone import now

from saas_core.modules.core.organizations.tenancy import TenantScopedModel
from saas_core.modules.shared.customers.api import CUSTOMER_MODEL


class AppointmentStatus(models.TextChoices):
    #: Waits for the company's answer (an offer booked „on request”, ADR-072
    #: §9): it holds its time like a confirmed one, until `hold_expires_at`.
    PENDING_REQUEST = "pending_request", "Czeka na odpowiedź"
    #: Waits for a payment the offer asks for before confirming: it holds its
    #: time the same way, until `hold_expires_at`.
    PENDING_PAYMENT = "pending_payment", "Czeka na wpłatę"
    CONFIRMED = "confirmed", "Potwierdzona"
    COMPLETED = "completed", "Zakończona"
    CANCELED = "canceled", "Anulowana"
    NO_SHOW = "no_show", "Nieobecność"


class TimeModel(models.TextChoices):
    """How an offer takes time (ADR-072 §1)."""

    #: A visit of a set length at a start the calendar offers.
    SLOT = "slot", "Termin"
    #: A stay from–to the customer picks: nights, days or hours.
    RANGE = "range", "Okres"
    #: Seats in an occurrence with a capacity (phase 8).
    SESSION = "session", "Wydarzenie"


class RangeUnit(models.TextChoices):
    NIGHT = "night", "Noc"
    DAY = "day", "Dzień"
    HOUR = "hour", "Godzina"


class PriceBasis(models.TextChoices):
    """What a price is charged for (ADR-072 §6)."""

    PER_BOOKING = "per_booking", "Za rezerwację"
    #: A night, a day or an hour — the offer's time unit.
    PER_TIME_UNIT = "per_time_unit", "Za jednostkę czasu"
    PER_PERSON = "per_person", "Za osobę"
    #: One price for the group that comes, whatever its size.
    PER_GROUP = "per_group", "Za grupę"


#: A booking that holds its time before it is confirmed.
PENDING_STATUSES = (AppointmentStatus.PENDING_REQUEST, AppointmentStatus.PENDING_PAYMENT)


class Confirmation(models.TextChoices):
    """Who confirms a booking a customer makes (ADR-072 §8)."""

    #: Booked is booked.
    INSTANT = "instant", "Od razu"
    #: The company answers each request; the time is held meanwhile.
    ON_REQUEST = "on_request", "Na prośbę"


class PaymentPolicy(models.TextChoices):
    """How the customer pays for an offer (ADR-072 §8). Paying before the
    visit — a transfer, a prepayment, the whole — needs orders (ADR-073): the
    booking then waits for the payment before it is confirmed."""

    #: Nothing is said about paying.
    NONE = "none", "Nie określono"
    ON_SITE = "on_site", "Płatność na miejscu"
    #: The whole amount by a transfer to the company's account.
    TRANSFER = "transfer", "Przelew przed wizytą"
    #: A part ahead (`Service.deposit_percent`), the rest on site.
    DEPOSIT = "deposit", "Przedpłata"
    #: The whole amount ahead, however it can be paid ahead.
    FULL = "full", "Całość z góry"


#: The policies that ask for money before the booking is confirmed.
PREPAID_POLICIES = (PaymentPolicy.TRANSFER, PaymentPolicy.DEPOSIT, PaymentPolicy.FULL)


class RefundBasis(models.TextChoices):
    """What an offer's refund thresholds are counted on (owner decision 28a,
    ADR-072 §8) — the switch „the thresholds cover the balance too”."""

    #: The prepayment only; whatever else was paid goes back whole.
    DEPOSIT = "deposit", "Tylko przedpłata"
    #: Everything the customer paid.
    PAID = "paid", "Wszystkie wpłaty"


class ExtraBasis(models.TextChoices):
    """What an extra is charged for (ADR-072 §6)."""

    PER_BOOKING = "per_booking", "Za rezerwację"
    PER_TIME_UNIT = "per_time_unit", "Za jednostkę czasu"
    PER_PERSON = "per_person", "Za osobę"
    PER_PERSON_PER_TIME_UNIT = "per_person_per_time_unit", "Za osobę i jednostkę czasu"


class ExtraKind(models.TextChoices):
    #: Something the customer pays for: cleaning, bed linen, a local tax.
    CHARGE = "charge", "Dopłata"
    #: Money held and given back: its own amount, never a line or revenue.
    SECURITY_DEPOSIT = "security_deposit", "Kaucja"


class VatCode(models.TextChoices):
    """A tax rate as a code, because an exemption is not 0% (ADR-072 §6).
    The warehouse keeps the same codes for products (`inventory.VatRate`)."""

    STANDARD = "23", "23%"
    REDUCED = "8", "8%"
    SUPER_REDUCED = "5", "5%"
    ZERO = "0", "0%"
    EXEMPT = "zw", "zw."
    #: Outside VAT: what the company only collects, like a local tax.
    OUTSIDE = "np", "np."


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
    #: Shown on the booking form on the company's site (B2); the team books
    #: a place that is not in the panel as before.
    online = models.BooleanField(default=True)
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


class ResourceGroup(TenantScopedModel):
    """A pool of identical units — „Domek 6-os.”, „Kajak 2-os.” (ADR-072 §3).

    A booking of the group gets a free unit of it, the least busy one; a unit
    belongs to one group at most, so that pick counts one pool.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    description = models.TextField(max_length=2000, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="booking_resourcegroup_org_name_uq"
            ),
        ]


class Resource(TenantScopedModel):
    """A resource a visit takes, or a unit a stay takes — a room, a chair, a
    cottage, a kayak (ADR-072 §3). One unit is always one booking at a time:
    a pool of identical ones is a group."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=80, default="generic")
    active = models.BooleanField(default=True)
    group = models.ForeignKey(
        ResourceGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="units"
    )
    #: Where the unit is; empty for a resource that goes wherever the visit does.
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="units"
    )
    #: How many people it takes; empty where the question makes no sense.
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(max_length=2000, blank=True)
    #: Shown to guests as content — its pictures, what it has, where it is
    #: (ADR-072 §3, slice 5c). A unit that is not is still booked, by its name.
    public = models.BooleanField(default=False)
    #: Its address segment where it has a page of its own; one per company.
    public_slug = models.SlugField(max_length=80, blank=True)
    #: Keys of `unit_content.UNIT_AMENITIES`, in the dictionary's order.
    amenities = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    #: Its town, from the catalogue's dictionary (`profiles.api.cities`).
    city_slug = models.SlugField(max_length=80, blank=True)
    #: For the company and the server — a map, a search nearby; never part of
    #: an answer to a guest.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    #: Media assets in the order shown; the first is the cover.
    photos = ArrayField(models.UUIDField(), default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__isnull=True) | models.Q(capacity__gte=1),
                name="booking_resource_capacity_ck",
            ),
            models.UniqueConstraint(
                fields=["organization", "public_slug"],
                condition=~models.Q(public_slug=""),
                name="booking_resource_public_slug_uq",
            ),
            # What guests are shown has an address.
            models.CheckConstraint(
                condition=models.Q(public=False) | ~models.Q(public_slug=""),
                name="booking_resource_public_slug_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(
                        latitude__gte=-90,
                        latitude__lte=90,
                        longitude__gte=-180,
                        longitude__lte=180,
                    )
                ),
                name="booking_resource_coordinates_ck",
            ),
        ]


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
    #: An offer with bookings never changes it (ADR-072 §1).
    time_model = models.CharField(max_length=8, choices=TimeModel, default=TimeModel.SLOT)
    #: A `range` offer counts nights, days or hours; empty otherwise.
    range_unit = models.CharField(max_length=8, choices=RangeUnit, blank=True)
    #: Check-in and check-out (nights), pickup and return (days): local times.
    range_start_local = models.TimeField(null=True, blank=True)
    range_end_local = models.TimeField(null=True, blank=True)
    #: A `slot` visit's length; empty for a `range` offer, whose length the
    #: customer picks within its rules.
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    buffer_before_minutes = models.PositiveSmallIntegerField(default=0)
    buffer_after_minutes = models.PositiveSmallIntegerField(default=0)
    minimum_notice_minutes = models.PositiveIntegerField(default=60)
    #: A `range` offer: at most this many days ahead of its first day a
    #: booking can be made. A season's own window comes first (`BookingRule.
    #: window_days`); empty — only the platform's bound.
    booking_window_days = models.PositiveIntegerField(null=True, blank=True)
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
    #: How often a visit may start, in minutes from the start of a person's
    #: hours (B6; ADR-058 §5): 5, 10, 15, 20, 30 or 60.
    slot_step_minutes = models.PositiveSmallIntegerField(default=5)
    #: On the booking form on the company's site (B2); off: the team books it
    #: in the panel only.
    online = models.BooleanField(default=True)
    #: What the customer is told about paying, frozen in each booking's quote.
    payment_policy = models.CharField(
        max_length=16, choices=PaymentPolicy, default=PaymentPolicy.NONE
    )
    #: Whether a customer's booking is confirmed at once or waits for the
    #: company's answer; the team's own bookings never wait for one.
    confirmation = models.CharField(
        max_length=16, choices=Confirmation, default=Confirmation.INSTANT
    )
    #: With `on_request`: how many hours the company has to answer before the
    #: request expires.
    response_hours = models.PositiveSmallIntegerField(default=24)
    #: With `deposit`: the part of the price paid ahead, in percent.
    deposit_percent = models.PositiveSmallIntegerField(default=30)
    #: With a payment ahead by a transfer: how many days the customer has
    #: before the booking expires.
    transfer_due_days = models.PositiveSmallIntegerField(default=3)
    #: With `deposit`: the rest is due by a transfer this many days before the
    #: booking starts; empty: the rest is paid on site.
    balance_due_days_before = models.PositiveSmallIntegerField(null=True, blank=True)
    #: What a customer who gives the booking up gets back (ADR-072 §8): rows
    #: `{"min_days_before", "refund_percent"}`, the longest notice first; less
    #: notice than the last row gives nothing back. Empty: no thresholds —
    #: everything paid goes back.
    cancellation_refunds = models.JSONField(default=list, blank=True)
    #: With `deposit`: what the thresholds are counted on (28a).
    cancellation_applies_to = models.CharField(
        max_length=8, choices=RefundBasis, default=RefundBasis.DEPOSIT
    )
    active = models.BooleanField(default=True)
    #: Never switched on since it was made. Only a draft can be discarded
    #: (`setup.discard_draft`); switching the offer on ends it for good.
    draft = models.BooleanField(default=False)
    #: Where the offer came from (ADR-072 §11): the preset it was copied from
    #: and, when the assistant made it, its conversation (`conversation:<uuid>`).
    preset_id = models.CharField(max_length=80, blank=True)
    preset_version = models.PositiveSmallIntegerField(null=True, blank=True)
    origin_ref = models.CharField(max_length=64, blank=True)
    #: The preset's words for a booking and for who comes, in the company's
    #: first language (§10): `{booking, bookings, participant, participants}`.
    vocabulary = models.JSONField(default=dict, blank=True)
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
            # ADR-072 §1: a range offer's length comes from its rules.
            models.CheckConstraint(
                condition=(
                    models.Q(time_model=TimeModel.RANGE, duration_minutes__isnull=True)
                    | (
                        ~models.Q(time_model=TimeModel.RANGE)
                        & models.Q(duration_minutes__gte=5, duration_minutes__lte=1440)
                    )
                ),
                name="booking_service_duration_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(time_model=TimeModel.RANGE, range_unit__in=list(RangeUnit.values))
                    | (~models.Q(time_model=TimeModel.RANGE) & models.Q(range_unit=""))
                ),
                name="booking_service_range_unit_ck",
            ),
            # ADR-072 §2: nobody is needed only where a unit or a seat is booked.
            models.CheckConstraint(
                condition=(
                    models.Q(staff_count__gte=1, staff_count__lte=10)
                    | (~models.Q(time_model=TimeModel.SLOT) & models.Q(staff_count=0))
                ),
                name="booking_service_staff_count_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(public_staff_choice=StaffChoice.PERSON)
                | models.Q(staff_count=1),
                name="booking_service_person_choice_ck",
            ),
        ]

    @property
    def slot_duration(self) -> timedelta:
        """A `slot` visit's length; a `range` offer has none (ADR-072 §1)."""
        if self.duration_minutes is None:
            raise ValueError("Oferta okresu nie ma długości wizyty.")
        return timedelta(minutes=self.duration_minutes)

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


class ServiceGroup(TenantScopedModel):
    """A group of units a `range` offer is booked in: the customer takes any
    free unit of it (ADR-072 §3). Single units go through `ServiceResource`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="group_links")
    group = models.ForeignKey(ResourceGroup, on_delete=models.PROTECT, related_name="service_links")
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["service", "group"], name="booking_service_group_uq"),
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


class TimeOffSource(models.TextChoices):
    MANUAL = "manual", "Ręczna"
    ICAL = "ical", "Kalendarz zewnętrzny"


class TimeOff(TenantScopedModel):
    """A person's absence, or a unit's block (ADR-072 §4).

    A unit's block holds its time with its own `AppointmentResourceAllocation`,
    under the same exclusion constraint as a booking, so a block and a guest
    cannot both win the same night. One that could not take its time (an
    import over a booking) has no active allocation and still keeps the unit
    busy in search.
    """

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
    source = models.CharField(max_length=8, choices=TimeOffSource, default=TimeOffSource.MANUAL)
    #: The event's UID in its calendar, for a block an import made (phase 6).
    external_uid = models.CharField(max_length=255, blank=True)
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


class BookingRule(TenantScopedModel):
    """A season's booking rules for an offer, a group of units or one unit
    (ADR-072 §5): a dated layer over the offer.

    For a day the most specific active rule that covers it applies — a unit's
    over its group's over the offer's; between two of one kind, the later
    start. Seasons are explicit dates with „copy to next year”, because the
    Saturdays move every year. Lengths count the offer's time units (nights,
    days, hours).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: For the company: „Sezon wysoki”, „Majówka”.
    name = models.CharField(max_length=160, blank=True)
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.PROTECT, related_name="booking_rules"
    )
    group = models.ForeignKey(
        ResourceGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="booking_rules"
    )
    resource = models.ForeignKey(
        Resource, null=True, blank=True, on_delete=models.PROTECT, related_name="booking_rules"
    )
    #: Local dates, both included.
    starts_on = models.DateField()
    ends_on = models.DateField()
    min_length = models.PositiveSmallIntegerField(null=True, blank=True)
    max_length = models.PositiveSmallIntegerField(null=True, blank=True)
    #: 7 — whole weeks only.
    length_multiple = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Weekdays a stay may begin and end on, 0 = Monday; empty — any.
    start_weekdays = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    end_weekdays = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    #: At least this long before its start a booking can still be made.
    notice_hours = models.PositiveIntegerField(null=True, blank=True)
    #: At most this far ahead a booking can be made.
    window_days = models.PositiveIntegerField(null=True, blank=True)
    #: No bookings in this season at all.
    closed = models.BooleanField(default=False)
    #: The break after a booking (cleaning); empty — the offer's own.
    buffer_after_minutes = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "starts_on", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(service__isnull=False, group__isnull=True, resource__isnull=True)
                    | models.Q(service__isnull=True, group__isnull=False, resource__isnull=True)
                    | models.Q(service__isnull=True, group__isnull=True, resource__isnull=False)
                ),
                name="booking_rule_one_scope_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="booking_rule_dates_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(min_length__isnull=True)
                | models.Q(max_length__isnull=True)
                | models.Q(max_length__gte=models.F("min_length")),
                name="booking_rule_length_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(start_weekdays__contained_by=list(range(7)))
                & models.Q(end_weekdays__contained_by=list(range(7))),
                name="booking_rule_weekdays_ck",
            ),
        ]


class BookingClosure(TenantScopedModel):
    """The company, or one of its places, takes no bookings on these days —
    Christmas Eve, a renovation (B11, ADR-078 pkt 17).

    A closure always restricts: no rule of an offer, a group or a unit opens
    it again, and it closes the calendar of people as well as of units.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: Empty — the whole company.
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="closures"
    )
    #: Local dates, both included.
    starts_on = models.DateField()
    ends_on = models.DateField()
    note = models.CharField(max_length=160, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "starts_on", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="booking_closure_dates_ck",
            ),
        ]


class ParticipantCategory(TenantScopedModel):
    """Who comes, when it changes the price — „Dziecko”, „Senior”, „Pies”
    (ADR-072 §6). A price rule may price a category; a participant without one
    is a standard person."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=160)
    #: A child takes a bed, a dog does not: only who counts is checked against
    #: a unit's capacity and may fill the people the price includes.
    counts_towards_capacity = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.UniqueConstraint(
                models.F("organization"),
                Lower("name"),
                name="booking_participantcategory_org_name_uq",
            ),
        ]


class PriceRule(TenantScopedModel):
    """A price of an offer, a group of units or one unit (ADR-072 §6).

    Without dates it is the base price; with dates a season's. `weekdays` and
    the hours narrow it to a weekend or a peak. For a day and an hour the most
    specific active rule applies (`prices.price_for`). Amounts are whole minor
    units of `currency`, read gross or net as the company set it
    (`pricing.entry.amounts`); the tax is a code.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: For the company: „Sezon wysoki”, „Weekend”.
    name = models.CharField(max_length=160, blank=True)
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.PROTECT, related_name="price_rules"
    )
    group = models.ForeignKey(
        ResourceGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="price_rules"
    )
    resource = models.ForeignKey(
        Resource, null=True, blank=True, on_delete=models.PROTECT, related_name="price_rules"
    )
    #: Local dates, both included; both empty — always.
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    #: The weekdays it prices, 0 = Monday; empty — every day. A night belongs
    #: to the day it begins on.
    weekdays = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    #: The local hours it prices, by a booking's start; both empty — all day.
    local_from = models.TimeField(null=True, blank=True)
    local_to = models.TimeField(null=True, blank=True)
    basis = models.CharField(max_length=16, choices=PriceBasis)
    amount_minor = models.PositiveIntegerField()
    #: The company's currency when the price was made (`Organization.currency`).
    currency = models.CharField(max_length=3)
    vat_code = models.CharField(max_length=2, choices=VatCode, default=VatCode.STANDARD)
    #: How many people the amount covers; empty — everybody who comes.
    included_people = models.PositiveSmallIntegerField(null=True, blank=True)
    #: What each further person adds; required with `included_people` (0 says
    #: they come free).
    extra_person_amount_minor = models.PositiveIntegerField(null=True, blank=True)
    #: Further people and priced categories pay per night or day, not once
    #: (a price per time unit only).
    extra_person_per_time_unit = models.BooleanField(default=False)
    #: A category's own amount instead of a person's:
    #: `[{"category_id", "amount_minor"}]`.
    category_prices = models.JSONField(default=list, blank=True)
    #: From this many time units the stay is cheaper; the longest threshold
    #: reached applies and a longer one always gives more:
    #: `[{"min_length", "percent"}]`.
    length_discounts = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "starts_on", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(service__isnull=False, group__isnull=True, resource__isnull=True)
                    | models.Q(service__isnull=True, group__isnull=False, resource__isnull=True)
                    | models.Q(service__isnull=True, group__isnull=True, resource__isnull=False)
                ),
                name="booking_price_one_scope_ck",
            ),
            models.CheckConstraint(
                # Both or neither: a check passes on NULL, so say it.
                condition=models.Q(starts_on__isnull=True, ends_on__isnull=True)
                | models.Q(
                    starts_on__isnull=False,
                    ends_on__isnull=False,
                    ends_on__gte=models.F("starts_on"),
                ),
                name="booking_price_dates_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(local_from__isnull=True, local_to__isnull=True)
                | models.Q(
                    local_from__isnull=False,
                    local_to__isnull=False,
                    local_to__gt=models.F("local_from"),
                ),
                name="booking_price_hours_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(weekdays__contained_by=list(range(7))),
                name="booking_price_weekdays_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(currency__regex=r"^[A-Z]{3}$"),
                name="booking_price_currency_ck",
            ),
        ]


class PriceChange(models.TextChoices):
    #: The price as it stood when the record began (the migration's line).
    BASELINE = "baseline", "Stan początkowy"
    CREATED = "created", "Dodana"
    UPDATED = "updated", "Zmieniona"
    DELETED = "deleted", "Usunięta"


class PriceHistoryEntry(TenantScopedModel):
    """What a price was (ADR-072 §6; ADR-073, slice 4i): one line for every
    write of a `PriceRule` — made, changed, deleted — with the whole rule as
    the write left it, who wrote it and when. Append-only: the price list of
    a past day is read from here (`price_history.rules_at`), not worked out
    from the audit, whose entries name fields and can be trimmed. A promotion
    must show the lowest price of the 30 days before it, and that cannot be
    made up afterwards.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: The price's id — not a foreign key: the line outlives a deleted price.
    rule_id = models.UUIDField()
    change = models.CharField(max_length=8, choices=PriceChange)
    #: Every column of the rule as this write left it, by column name; for a
    #: deletion, as it last was.
    state = models.JSONField()
    #: The amount after the write (a deleted price's last one) and before it
    #: (empty for a price just made and for the baseline).
    amount_minor = models.PositiveIntegerField()
    previous_amount_minor = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3)
    #: The person who wrote it; empty — nobody did (the baseline).
    actor_id = models.UUIDField(null=True, blank=True)
    #: `assistant` when the person's assistant wrote it for them (ADR-076 §6).
    acting_via = models.CharField(max_length=32, blank=True)
    recorded_at = models.DateTimeField(default=now)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "-recorded_at", "-id")
        indexes = [
            models.Index(
                fields=["organization", "rule_id", "recorded_at"],
                name="booking_pricehist_rule_idx",
            ),
            models.Index(fields=["organization", "recorded_at"], name="booking_pricehist_time_idx"),
        ]


class Extra(TenantScopedModel):
    """What an offer adds to its price — „Sprzątanie końcowe”, „Pościel”,
    „Opłata miejscowa” — or the deposit it holds (ADR-072 §6).

    A mandatory one is on every booking of the offer; an optional one the
    customer picks, up to `max_quantity`. Amounts are read gross or net like
    the price list's (`pricing.entry.amounts`). A security deposit is not a
    charge: the quote names it beside the total, without tax.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="extras")
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=16, choices=ExtraKind, default=ExtraKind.CHARGE)
    basis = models.CharField(max_length=24, choices=ExtraBasis, default=ExtraBasis.PER_BOOKING)
    amount_minor = models.PositiveIntegerField()
    #: The company's currency when it was made (`Organization.currency`).
    currency = models.CharField(max_length=3)
    vat_code = models.CharField(max_length=2, choices=VatCode, default=VatCode.STANDARD)
    mandatory = models.BooleanField(default=False)
    #: How many of an optional one a booking may take.
    max_quantity = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        ordering = ("organization_id", "name", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_quantity__gte=1), name="booking_extra_quantity_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(currency__regex=r"^[A-Z]{3}$"),
                name="booking_extra_currency_ck",
            ),
            # A deposit is one amount held for the booking, outside VAT.
            models.CheckConstraint(
                condition=~models.Q(kind=ExtraKind.SECURITY_DEPOSIT)
                | models.Q(
                    basis=ExtraBasis.PER_BOOKING,
                    vat_code=VatCode.OUTSIDE,
                    mandatory=True,
                    max_quantity=1,
                ),
                name="booking_extra_deposit_ck",
            ),
        ]


class Appointment(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    #: The company's customer, a record of `shared.customers` (ADR-073 §2).
    customer = models.ForeignKey(
        CUSTOMER_MODEL, on_delete=models.PROTECT, related_name="appointments"
    )
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="appointments")
    #: The lead; empty exactly when the booking takes nobody — a unit, a seat
    #: (ADR-072 §2, `staff_required` 0).
    staff = models.ForeignKey(
        StaffMember, null=True, blank=True, on_delete=models.PROTECT, related_name="appointments"
    )
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
    #: The service's name in the customer's language when the company translated
    #: it, frozen like `service_name`; empty: the same (TL12c). Customer-facing
    #: answers read it, the panel keeps the company's language.
    customer_service_name = models.CharField(max_length=160, blank=True)
    #: What the customer's link may do, as the company had it at booking (B4,
    #: UF-D1): `change_and_cancel`, `cancel_only` or `none`; and how many
    #: hours before the start it stops (0: at the start). A later change of the
    #: company's setting never changes a booking already made.
    self_service_mode = models.CharField(max_length=24, default="change_and_cancel")
    self_service_cutoff_hours = models.PositiveSmallIntegerField(default=0)
    #: Produkty tej wizyty: kopia z usługi albo wpisane ręcznie, z nazwą i
    #: ceną z chwili zapisu. Stan jest zarezerwowany do zakończenia wizyty.
    materials = models.JSONField(default=list, blank=True)
    #: The price worked out when the booking was made or last moved, frozen
    #: (ADR-072 §7, `quote.Quote.snapshot`): lines with net, tax and gross, who
    #: comes, the totals. A later change of the price list never changes it.
    #: Empty for a booking from before quotes.
    quote = models.JSONField(null=True, blank=True)
    quote_digest = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=AppointmentStatus, default=AppointmentStatus.CONFIRMED
    )
    #: Until when a pending booking holds its time: a copy of the awaited
    #: payment's date, for showing — the date itself is commerce's (ADR-073 §5).
    hold_expires_at = models.DateTimeField(null=True, blank=True)
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
    #: The group a stay was booked in: moving the stay picks a unit of it again.
    requested_group = models.ForeignKey(
        ResourceGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
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
            models.CheckConstraint(
                condition=models.Q(staff__isnull=True, staff_required=0)
                | models.Q(staff__isnull=False, staff_required__gte=1),
                name="booking_appointment_staff_ck",
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
    """The time a unit or resource is taken — by a booking or by a block,
    exactly one of them (ADR-072 §4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resource_allocations",
    )
    #: A block's own hold; deleting the block lets the time go with it.
    time_off = models.ForeignKey(
        TimeOff,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="resource_allocations",
    )
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT)
    occupied_range = DateTimeRangeField()
    active = models.BooleanField(default=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(appointment__isnull=False, time_off__isnull=True)
                    | models.Q(appointment__isnull=True, time_off__isnull=False)
                ),
                name="booking_resource_allocation_owner_ck",
            ),
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
    #: `service.create`, `service.update`, `service.discard`, `location.create`,
    #: `location.update`, `resource.create`, `resource.update`, `staff.hours.set`,
    #: `staff.add`.
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


class RequestRoute(models.Model):
    """Which request's time to answer runs out when (ADR-072 §9): what the
    task reads before it knows a tenant — identifiers and a date, never a
    customer's data, with the organization's own contract (the pattern of
    `ReminderRoute`)."""

    appointment_id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    signed_tenant_context = models.TextField()
    due_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["due_at"],
                condition=models.Q(dispatched_at__isnull=True),
                name="booking_requestroute_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.appointment_id)


class ItemTranslation(TenantScopedModel):
    """A booking item said in another language (ADR-069; plan TL12b).

    One row per item and language, `texts` by field (`name`, and `description`
    where the item has one) with each text's provenance (`content_protocol`).
    The item keeps its own text: the company's language. Without the
    translation engine the rows are simply what people wrote; nothing reads
    them but the item's own API and the public form.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    locale = models.CharField(max_length=10)
    texts = models.JSONField(default=dict, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        abstract = True


class ServiceTranslation(ItemTranslation):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "service", "locale"], name="booking_service_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"), name="booking_service_tr_locale_ck"
            ),
        ]


class LocationTranslation(ItemTranslation):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "location", "locale"], name="booking_location_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="booking_location_tr_locale_ck",
            ),
        ]


class ResourceTranslation(ItemTranslation):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "resource", "locale"], name="booking_resource_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="booking_resource_tr_locale_ck",
            ),
        ]


class ResourceGroupTranslation(ItemTranslation):
    group = models.ForeignKey(ResourceGroup, on_delete=models.CASCADE, related_name="translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "group", "locale"], name="booking_group_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"), name="booking_group_tr_locale_ck"
            ),
        ]


class StaffTeamTranslation(ItemTranslation):
    team = models.ForeignKey(StaffTeam, on_delete=models.CASCADE, related_name="translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "team", "locale"], name="booking_team_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"), name="booking_team_tr_locale_ck"
            ),
        ]


class ParticipantCategoryTranslation(ItemTranslation):
    category = models.ForeignKey(
        ParticipantCategory, on_delete=models.CASCADE, related_name="translations"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "category", "locale"], name="booking_category_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"),
                name="booking_category_tr_locale_ck",
            ),
        ]


class ExtraTranslation(ItemTranslation):
    extra = models.ForeignKey(Extra, on_delete=models.CASCADE, related_name="translations")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "extra", "locale"], name="booking_extra_tr_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(locale__regex=r"^[a-z]{2}$"), name="booking_extra_tr_locale_ck"
            ),
        ]


class CatalogTranslationWrite(TenantScopedModel):
    """The receipt of one translation write of the booking catalogue in one
    language (`translation_source`, TL12c): a repeat answers the same outcomes,
    and the texts it replaced let `revert` put them back."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    locale = models.CharField(max_length=10)
    idempotency_key = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    job_ref = models.CharField(max_length=160, blank=True, default="")
    outcomes = models.JSONField(default=list)
    # Unit key → [text, provenance] before the write; null where it had none.
    replaced = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "locale", "idempotency_key"],
                name="booking_catalogtranslationwrite_idem_uq",
            ),
        ]
        indexes = [models.Index(fields=["organization", "job_ref"])]


def validate_same_tenant(instance: Any, *related_names: str) -> None:
    for name in related_names:
        related = getattr(instance, name, None)
        if related is not None and related.organization_id != instance.organization_id:
            raise ValidationError({name: "Powiązany rekord należy do innej organizacji."})
