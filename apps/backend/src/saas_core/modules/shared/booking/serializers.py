from __future__ import annotations

from typing import Any

from rest_framework import serializers

from saas_core.modules.core.organizations.serializers import LocalizedTextSerializer

from .models import StaffChoice
from .offer_settings import offer_setting


def _changes() -> serializers.DictField:
    return serializers.DictField(
        child=serializers.JSONField(),
        help_text="What the write changes, per field: `{from, to}`, or `{changed: true}` for "
        "a private value and a list of links. Empty for a new item and for no change.",
    )


class CatalogCreateSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(choices=("location", "staff", "service", "resource"))
    name = serializers.CharField(max_length=160)
    public_slug = serializers.SlugField(max_length=80, required=False)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    resource_kind = serializers.CharField(max_length=80, required=False)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=1440, required=False)
    buffer_before_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    buffer_after_minutes = serializers.IntegerField(min_value=0, max_value=1440, required=False)
    minimum_notice_minutes = serializers.IntegerField(min_value=0, required=False)
    #: For a service: the kind of visit a module provides (e.g. from a service
    #: template of the organization's type, ADR-050).
    appointment_kind = serializers.CharField(max_length=64, required=False, allow_blank=True)
    #: For staff: the team member's account this calendar entry stands for.
    membership_id = serializers.UUIDField(required=False, allow_null=True)


class ScheduleCreateSerializer(serializers.Serializer[dict[str, Any]]):
    kind = serializers.ChoiceField(
        choices=(
            "availability",
            "time_off",
            "service_staff",
            "service_location",
            "service_resource",
        )
    )
    service_id = serializers.UUIDField(required=False)
    staff_id = serializers.UUIDField(required=False, allow_null=True)
    location_id = serializers.UUIDField(required=False)
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    weekday = serializers.IntegerField(min_value=0, max_value=6, required=False)
    local_start = serializers.TimeField(required=False)
    local_end = serializers.TimeField(required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    reason = serializers.CharField(max_length=160, required=False, allow_blank=True)


class CustomerInputSerializer(serializers.Serializer[dict[str, Any]]):
    display_name = serializers.CharField(min_length=1, max_length=160)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    #: The visitor's language. Not refused when the company does not offer
    #: it: the booking falls back to the company's first language (ADR-071 pkt 21).
    locale = serializers.CharField(
        max_length=10,
        required=False,
        help_text="Język klienta; spoza języków firmy zamieniany na pierwszy język firmy.",
    )


class MaterialInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Produkt z magazynu przy usłudze albo wizycie (ADR-055)."""

    item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0)
    #: `consume` — zużycie na koszt firmy (RW); `sale` — sprzedaż klientowi (WZ).
    mode = serializers.ChoiceField(choices=("consume", "sale"), default="consume")


class MaterialLineSerializer(serializers.Serializer[dict[str, Any]]):
    item_id = serializers.UUIDField()
    name = serializers.CharField()
    unit = serializers.CharField()
    quantity = serializers.CharField()
    mode = serializers.ChoiceField(choices=("consume", "sale"))
    #: Cena sprzedaży netto z chwili zapisu; null dla zużycia.
    unit_price_minor = serializers.IntegerField(allow_null=True)
    currency = serializers.CharField()


class MaterialsInputSerializer(serializers.Serializer[dict[str, Any]]):
    materials = MaterialInputSerializer(many=True)


class AppointmentCreateSerializer(serializers.Serializer[dict[str, Any]]):
    service_id = serializers.UUIDField()
    #: Omitted: the server picks the least busy free person (ADR-058 §4).
    staff_id = serializers.UUIDField(required=False, allow_null=True)
    #: The people, the lead first; fewer than the service needs make a vacancy.
    staff_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=10)
    #: Choose only among this team's free members (with no people named).
    team_id = serializers.UUIDField(required=False, allow_null=True)
    location_id = serializers.UUIDField()
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    starts_at = serializers.DateTimeField()
    customer = CustomerInputSerializer()
    #: Pominięte: produkty z usługi. Podane: dokładnie te (wymaga inventory.use).
    materials = MaterialInputSerializer(many=True, required=False)
    #: „Uwagi”: what the customer wants the company to know (never in an e-mail).
    customer_notes = serializers.CharField(required=False, allow_blank=True, max_length=500)
    place_town = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
        help_text="„Miejsce wizyty”: the town, when the visit is not at the company's location.",
    )
    place_address = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=240,
        help_text="Street and number in that town; optional, and only with a town.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _street_needs_town(
            attrs.get("place_town", ""), attrs.get("place_address", ""), "place_town"
        )
        return attrs


def _street_needs_town(town: str, address: str, town_field: str) -> None:
    if address.strip() and not town.strip():
        raise serializers.ValidationError({town_field: "Podaj miejscowość do tej ulicy."})


class VisitPlaceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """„Miejsce wizyty” of a booked visit; both empty clear it (ADR-066)."""

    town = serializers.CharField(allow_blank=True, max_length=120, help_text="The town.")
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=240,
        help_text="Street and number; optional, and only with a town.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _street_needs_town(attrs.get("town", ""), attrs.get("address", ""), "town")
        return attrs


class VisitPlaceSuggestionSerializer(serializers.Serializer[dict[str, Any]]):
    """A place the company keeps (a farm, say); choosing it fills the visit's place."""

    name = serializers.CharField(help_text="What the office knows the place by.")
    town = serializers.CharField()
    address = serializers.CharField()


class VisitPlaceSuggestionListSerializer(serializers.Serializer[dict[str, Any]]):
    items = VisitPlaceSuggestionSerializer(many=True)


class PublicAppointmentCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """The customer names the service, place and time, and — where the service
    lets them — a team or a person shown to customers; everything else is the
    server's (ADR-058 §4, §8)."""

    service_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    customer = CustomerInputSerializer()
    team_id = serializers.UUIDField(required=False, allow_null=True)
    person_id = serializers.UUIDField(required=False, allow_null=True)
    #: „Uwagi”: for the company's eyes only, never in an e-mail (answer 1A).
    customer_notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class RescheduleSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()


class CrewMemberSerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    #: The person's account, for "my visits" (null: no account).
    membership_id = serializers.UUIDField(allow_null=True)
    lead = serializers.BooleanField()


class TeamRefSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AppointmentSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    service_name = serializers.CharField()
    status = serializers.CharField()
    customer_name = serializers.CharField()
    staff_id = serializers.UUIDField()
    staff_name = serializers.CharField()
    #: The calendar entry's team member, for "my visits" (null: no account).
    staff_membership_id = serializers.UUIDField(allow_null=True)
    location_name = serializers.CharField()
    place = serializers.CharField(
        allow_null=True,
        help_text=(
            "Where the visit takes place, as a town: the visit's own place_town, "
            "else what the module that owns the visit's detail knows (a field "
            "visit's farm). Null when neither says."
        ),
    )
    place_town = serializers.CharField(
        help_text="The visit's own „Miejsce wizyty”: its town, or empty."
    )
    #: Null when the caller may not see it: only who plans visits and the
    #: people on this visit do (ADR-067).
    customer_phone = serializers.CharField(
        allow_null=True,
        help_text="The customer's phone, for whoever plans visits and the people on it.",
    )
    customer_email = serializers.CharField(
        allow_null=True,
        help_text="The customer's e-mail, for whoever plans visits and the people on it.",
    )
    appointment_kind = serializers.CharField(
        help_text="The kind of the visit's service; a product's own kinds name its visits.",
    )
    flags = serializers.ListField(
        child=serializers.CharField(),
        help_text="Marks a product puts on the visit's card, e.g. farm_missing (ADR-067).",
    )
    place_address = serializers.CharField(
        allow_blank=True,
        help_text=(
            "Street and number of the visit's own place, or empty; empty also for "
            "whoever may not see the customer's phone."
        ),
    )
    resource_name = serializers.CharField(allow_null=True)
    #: Tylko w panelu firmy; klient w self-service tego nie dostaje.
    materials = MaterialLineSerializer(many=True, required=False)
    #: False, gdy materiał tej wizyty rozlicza jej moduł (ADR-055) albo nie ma magazynu.
    takes_materials = serializers.BooleanField(required=False)
    self_service_token = serializers.CharField(required=False, allow_null=True)
    #: Everybody on the visit, the lead first (ADR-058 §2).
    crew = CrewMemberSerializer(many=True)
    #: How many people the visit was booked for.
    staff_required = serializers.IntegerField()
    #: A vacancy: fewer people than required, or no lead.
    needs_assignment = serializers.BooleanField()
    #: The system chose the people; the office has not looked yet.
    auto_assigned = serializers.BooleanField()
    #: Name it in an assignment (`expected_version`).
    crew_version = serializers.IntegerField()
    #: Why it waits in „Do przydzielenia”, and since when.
    queue_reason = serializers.CharField()
    queued_at = serializers.DateTimeField(allow_null=True)
    #: The team the customer chose (null also once that team was removed).
    requested_team = TeamRefSerializer(allow_null=True)
    #: The person the customer chose on the public form.
    requested_staff_id = serializers.UUIDField(allow_null=True)
    #: „Uwagi” from the customer. Panel only; never in an e-mail.
    customer_notes = serializers.CharField()


class PublicAppointmentSerializer(serializers.Serializer[dict[str, Any]]):
    """What the customer sees of their visit: no stock, and of the people
    only the team they chose or a name shown to customers (ADR-058 §8)."""

    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    service_name = serializers.CharField()
    location_name = serializers.CharField()
    status = serializers.CharField()
    #: The team the customer chose, by name.
    team_name = serializers.CharField(allow_null=True)
    #: „Przyjmie Cię”: the lead's name when it is shown to customers.
    person_name = serializers.CharField(allow_null=True)
    self_service_token = serializers.CharField(required=False)


class AppointmentListSerializer(serializers.Serializer[dict[str, Any]]):
    items = AppointmentSerializer(many=True)


class QueueItemSerializer(AppointmentSerializer):
    """A visit in „Do przydzielenia”, with what the office phones or reads."""

    customer_phone = serializers.CharField()
    customer_email = serializers.CharField()


class QueueSerializer(serializers.Serializer[dict[str, Any]]):
    items = QueueItemSerializer(many=True)


class OverviewSerializer(serializers.Serializer[dict[str, Any]]):
    #: People who take visits: an active entry with a service and hours.
    bookable_staff = serializers.IntegerField()
    teams = serializers.IntegerField()
    #: Visits in „Do przydzielenia”; null for whoever may not assign.
    waiting = serializers.IntegerField(allow_null=True)


class CrewInputSerializer(serializers.Serializer[dict[str, Any]]):
    #: Exactly the people who should be on the visit; the same ones again is „Zostaw”.
    staff_ids = serializers.ListField(child=serializers.UUIDField(), max_length=10)
    #: One of `staff_ids`; omitted: the first of them.
    lead_id = serializers.UUIDField(required=False, allow_null=True)
    #: The `crew_version` the office looked at (ADR-058 §9).
    expected_version = serializers.IntegerField(min_value=0)
    #: „Powiadom pracowników”: in the app and by e-mail.
    notify = serializers.BooleanField(default=True)


class WorkRangeSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class CandidateSerializer(serializers.Serializer[dict[str, Any]]):
    """One person for one visit („kto jest wolny”, ADR-058 §9)."""

    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    team_ids = serializers.ListField(child=serializers.UUIDField())
    #: active, suspended, invited or none.
    account = serializers.CharField()
    #: Null for whoever may not see it (management and the person only).
    phone = serializers.CharField(allow_null=True)
    does_service = serializers.BooleanField()
    #: free, busy, time_off, off_schedule — never the reason of an absence.
    state = serializers.CharField()
    until = serializers.DateTimeField(allow_null=True)
    hours = WorkRangeSerializer(many=True)
    on_visit = serializers.BooleanField()
    lead = serializers.BooleanField()
    day_visits = serializers.IntegerField()
    day_minutes = serializers.IntegerField()
    next_free = serializers.DateTimeField(allow_null=True)


class CandidateListSerializer(serializers.Serializer[dict[str, Any]]):
    items = CandidateSerializer(many=True)


class CandidateQuerySerializer(serializers.Serializer[dict[str, Any]]):
    #: Everybody in the company, not only who does the service („Pokaż: Wszyscy”).
    everyone = serializers.BooleanField(default=False)


class TeamSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    member_ids = serializers.ListField(child=serializers.UUIDField())


class TeamListSerializer(serializers.Serializer[dict[str, Any]]):
    items = TeamSerializer(many=True)


class TeamInputSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160)
    member_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100)


class TeamUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, required=False)
    member_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=100, required=False
    )


class ServiceSetupSerializer(serializers.Serializer[dict[str, Any]]):
    """A service as Ustawienia › Usługi i grafik edits it (team phase 3c)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    appointment_kind = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    buffer_before_minutes = serializers.IntegerField()
    buffer_after_minutes = serializers.IntegerField()
    minimum_notice_minutes = serializers.IntegerField()
    staff_count = serializers.IntegerField()
    public_staff_choice = serializers.CharField()
    active = serializers.BooleanField()
    #: Who does it; the places it is offered at; the resources a visit takes
    #: one of.
    staff_ids = serializers.ListField(child=serializers.UUIDField())
    location_ids = serializers.ListField(child=serializers.UUIDField())
    resource_ids = serializers.ListField(child=serializers.UUIDField())
    materials = MaterialInputSerializer(many=True)
    #: False when the visit's module takes its own material (ADR-055).
    takes_materials = serializers.BooleanField()
    version = serializers.IntegerField(
        help_text="The service's version; a change names it (`expected_version`)."
    )


class PlaceSetupSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    address = serializers.CharField()
    active = serializers.BooleanField()
    version = serializers.IntegerField(
        help_text="The place's version; a change names it (`expected_version`)."
    )


class ResourceSetupSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    active = serializers.BooleanField()
    version = serializers.IntegerField(
        help_text="The resource's version; a change names it (`expected_version`)."
    )


class ServiceSetupPreviewSerializer(ServiceSetupSerializer):
    """The service as the write would leave it; nothing is saved."""

    changes = _changes()


class PlaceSetupPreviewSerializer(PlaceSetupSerializer):
    """The place as the write would leave it; nothing is saved."""

    changes = _changes()


class ResourceSetupPreviewSerializer(ResourceSetupSerializer):
    """The resource as the write would leave it; nothing is saved."""

    changes = _changes()


class SetupPersonSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    hours_version = serializers.IntegerField(
        help_text="The version of the person's week, for a change of their hours."
    )


class SetupOptionValueSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.CharField()
    label = LocalizedTextSerializer()  # type: ignore[assignment]


#: The registry's types and units (ADR-078); one enum name each in the contract.
SETTING_TYPES = ("int", "decimal", "bool", "enum", "text")
SETTING_UNITS = ("minute", "hour", "day", "percent")


class SetupOptionSerializer(serializers.Serializer[dict[str, Any]]):
    """One setting of an offer, in the shape of the settings registry (ADR-078)."""

    key = serializers.CharField(help_text="`booking.offer.<field>`; the field is the key's tail.")
    type = serializers.ChoiceField(choices=SETTING_TYPES)
    minimum = serializers.IntegerField(allow_null=True)
    maximum = serializers.IntegerField(allow_null=True)
    unit = serializers.ChoiceField(choices=SETTING_UNITS, allow_null=True)
    values = SetupOptionValueSerializer(
        many=True, allow_null=True, help_text="The variants of an `enum`, in order."
    )
    default = serializers.JSONField(help_text="What a new offer gets when nothing is said.")
    label = LocalizedTextSerializer()  # type: ignore[assignment]
    help = LocalizedTextSerializer(allow_null=True)
    description = serializers.CharField(help_text="What the value does, for the assistant.")
    scopes = serializers.ListField(child=serializers.CharField())
    depends_on = serializers.CharField(allow_null=True)


class SetupOptionsSerializer(serializers.Serializer[dict[str, Any]]):
    keys = SetupOptionSerializer(many=True)


class SetupSerializer(serializers.Serializer[dict[str, Any]]):
    services = ServiceSetupSerializer(many=True)
    locations = PlaceSetupSerializer(many=True)
    resources = ResourceSetupSerializer(many=True)
    staff = SetupPersonSerializer(many=True)


def _bounded(field: str, **kwargs: Any) -> serializers.IntegerField:
    """An offer's number with the bounds `OFFER_SETTINGS` declares for it."""
    setting = offer_setting(field)
    assert setting.minimum is not None and setting.maximum is not None
    return serializers.IntegerField(
        min_value=setting.minimum,
        max_value=setting.maximum,
        help_text=setting.description,
        **kwargs,
    )


def _expected_version() -> serializers.IntegerField:
    return serializers.IntegerField(
        min_value=1,
        help_text="The version the change was made on, as the last read gave it; another "
        "one answers 409 `booking_version_conflict`.",
    )


class ServiceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new service."""

    name = serializers.CharField(max_length=160)
    duration_minutes = _bounded("duration_minutes")
    buffer_before_minutes = _bounded("buffer_before_minutes", required=False)
    buffer_after_minutes = _bounded("buffer_after_minutes", required=False)
    minimum_notice_minutes = _bounded("minimum_notice_minutes", required=False)
    staff_count = _bounded("staff_count", required=False)
    public_staff_choice = serializers.ChoiceField(choices=StaffChoice.choices, required=False)
    active = serializers.BooleanField(required=False)
    #: A new service only: the kind of visit a module provides (ADR-050).
    appointment_kind = serializers.CharField(max_length=64, required=False, allow_blank=True)
    staff_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100, required=False)
    location_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=50, required=False
    )
    resource_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=50, required=False
    )
    materials = MaterialInputSerializer(many=True, required=False)


class ServiceUpdateSerializer(ServiceInputSerializer):
    """A change to a service: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    duration_minutes = _bounded("duration_minutes", required=False)
    appointment_kind = None  # type: ignore[assignment]
    expected_version = _expected_version()


class PlaceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new place where the company works."""

    name = serializers.CharField(max_length=160)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)


class PlaceUpdateSerializer(PlaceInputSerializer):
    """A change to a place: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    expected_version = _expected_version()


class ResourceInputSerializer(serializers.Serializer[dict[str, Any]]):
    """A new resource (a room, a device) a visit can take."""

    name = serializers.CharField(max_length=160)
    active = serializers.BooleanField(required=False)


class ResourceUpdateSerializer(ResourceInputSerializer):
    """A change to a resource: only the fields sent change."""

    name = serializers.CharField(max_length=160, required=False)
    expected_version = _expected_version()


class CustomerAnonymizedSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    anonymized_at = serializers.DateTimeField()


class SlotSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    staff_id = serializers.UUIDField()
    resource_id = serializers.UUIDField(allow_null=True)


class SlotListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SlotSerializer(many=True)


class SlotDayListSerializer(serializers.Serializer[dict[str, Any]]):
    items = serializers.ListField(child=serializers.DateField())


class SlotTimeSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class SlotTimeListSerializer(serializers.Serializer[dict[str, Any]]):
    items = SlotTimeSerializer(many=True)


class SlotStaffSerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    #: The resource that goes with this person at this start, for the create call.
    resource_id = serializers.UUIDField(allow_null=True)


class StaffSlotTimeSerializer(SlotTimeSerializer):
    #: Who is free at this start; only the panel sees it (ADR-058 §8).
    staff = SlotStaffSerializer(many=True)


class StaffSlotTimeListSerializer(serializers.Serializer[dict[str, Any]]):
    items = StaffSlotTimeSerializer(many=True)


class LocationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()


class StaffSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    membership_id = serializers.UUIDField(allow_null=True)


class PublicServiceSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    #: Lets a vertical's screen offer only its own kind of visit (ADR-050).
    appointment_kind = serializers.CharField()


class PublicChoiceServiceSerializer(PublicServiceSerializer):
    #: „Do kogo?”: none, a team or a person (answer 2, 24.09).
    staff_choice = serializers.CharField()
    #: The teams able to take it, or the people shown to customers who do it.
    team_ids = serializers.ListField(child=serializers.UUIDField())
    person_ids = serializers.ListField(child=serializers.UUIDField())


class PublicNameSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ServiceSerializer(PublicServiceSerializer):
    #: How many people one visit needs (ADR-058 §2).
    staff_count = serializers.IntegerField()
    #: What the public form lets a customer choose: none, team or person.
    public_staff_choice = serializers.CharField()
    #: Produkty z magazynu, które wizyta tej usługi zabiera.
    materials = MaterialInputSerializer(many=True, required=False)
    #: False, gdy materiał tej usługi rozlicza jej moduł (ADR-055) albo nie ma magazynu.
    takes_materials = serializers.BooleanField(required=False)


class ResourceSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()


class CatalogSerializer(serializers.Serializer[dict[str, Any]]):
    locations = LocationSerializer(many=True)
    staff = StaffSerializer(many=True)
    services = ServiceSerializer(many=True)
    resources = ResourceSerializer(many=True)
    #: A module offers the company's places (GET /booking/places/) in the visit form.
    place_search = serializers.BooleanField(required=False)


class PublicCatalogSerializer(serializers.Serializer[dict[str, Any]]):
    """The catalogue without the staff list: only teams by name and people the
    company shows its customers (ADR-058 §8)."""

    locations = LocationSerializer(many=True)
    services = PublicChoiceServiceSerializer(many=True)
    resources = ResourceSerializer(many=True)
    teams = PublicNameSerializer(many=True)
    people = PublicNameSerializer(many=True)
    #: The organization's zone: the days and times offered are its wall clock.
    timezone = serializers.CharField()


class PersonSerializer(serializers.Serializer[dict[str, Any]]):
    """A person of the company as booking keeps them (ADR-058 §1)."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    public_slug = serializers.CharField()
    #: The person's account; null: no account (a subcontractor) or not yet.
    membership_id = serializers.UUIDField(allow_null=True)
    #: The invitation the person was added under; accepting it links the account.
    invitation_id = serializers.UUIDField(allow_null=True)
    #: Null for whoever may not see it: management and the person only (ADR-058 §9).
    phone = serializers.CharField(allow_null=True)
    #: False: a former employee.
    active = serializers.BooleanField()
    #: The services the person does; with hours, that is "takes visits".
    service_ids = serializers.ListField(child=serializers.UUIDField())
    has_hours = serializers.BooleanField()
    #: The teams the person belongs to (ADR-058 §2).
    team_ids = serializers.ListField(child=serializers.UUIDField())
    #: „Pokazuj klientom”: the name customers see; null: not shown (ADR-058 §8).
    public_name = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class PersonPublicInputSerializer(serializers.Serializer[dict[str, Any]]):
    shown = serializers.BooleanField()
    #: The name for customers, e.g. with a title; empty: the person's own.
    name = serializers.CharField(max_length=160, required=False, allow_blank=True)


class PersonListSerializer(serializers.Serializer[dict[str, Any]]):
    items = PersonSerializer(many=True)


class PersonListQuerySerializer(serializers.Serializer[dict[str, Any]]):
    #: Only the caller's own entry ("my card").
    mine = serializers.BooleanField(default=False)


class WorkingHoursSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    #: 0 is Monday; the times are the organization's wall clock.
    weekday = serializers.IntegerField()
    local_start = serializers.TimeField()
    local_end = serializers.TimeField()
    location_id = serializers.UUIDField()
    location_name = serializers.CharField()


class TimeOffSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    #: Null for whoever may not see it: an illness is health data (ADR-058 §9).
    reason = serializers.CharField(allow_null=True)


class PersonDetailSerializer(PersonSerializer):
    hours = WorkingHoursSerializer(many=True)
    #: Current and coming absences.
    time_off = TimeOffSerializer(many=True)
    hours_version = serializers.IntegerField(
        help_text="The version of the person's week; a change of the hours names it "
        "(`expected_version`)."
    )


class PersonHoursPreviewSerializer(PersonDetailSerializer):
    """The person as the change of hours would leave them; nothing is saved."""

    changes = _changes()


class PersonInvitationInputSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField()
    role = serializers.SlugField(max_length=64)


class WeeklyHoursInputSerializer(serializers.Serializer[dict[str, Any]]):
    """The same hours on the chosen weekdays, as "Add employee" asks for them."""

    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), min_length=1, max_length=7
    )
    local_start = serializers.TimeField()
    local_end = serializers.TimeField()
    #: Omitted: the organization's only place of work.
    location_id = serializers.UUIDField(required=False, allow_null=True)


class PersonCreateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(min_length=1, max_length=160)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    #: An e-mail and a role: the person gets an invitation to the panel.
    invitation = PersonInvitationInputSerializer(required=False, allow_null=True)
    #: An existing member's own entry, when they have none yet.
    membership_id = serializers.UUIDField(required=False, allow_null=True)
    service_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    hours = WeeklyHoursInputSerializer(required=False, allow_null=True)
    #: "Hours like …": another person's week instead of `hours`.
    copy_hours_from = serializers.UUIDField(required=False, allow_null=True)
    #: The teams the person joins (ADR-058 §2).
    team_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)


class PersonUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(min_length=1, max_length=160, required=False)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    #: Links an entry added without an account to a team member's (null: unlinks).
    membership_id = serializers.UUIDField(required=False, allow_null=True)


class PersonServicesInputSerializer(serializers.Serializer[dict[str, Any]]):
    service_ids = serializers.ListField(child=serializers.UUIDField())


class HoursRuleInputSerializer(serializers.Serializer[dict[str, Any]]):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    local_start = serializers.TimeField()
    local_end = serializers.TimeField()
    location_id = serializers.UUIDField()


class PersonHoursInputSerializer(serializers.Serializer[dict[str, Any]]):
    rules = serializers.ListField(
        child=HoursRuleInputSerializer(),
        max_length=70,
        help_text="The person's whole week, rule by rule; an empty list clears it. A refusal "
        "names the rule: `rules.<i>.location_id`, `rules.<i>.local_end`, `rules.<i>.local_start`.",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="The week's version (`hours_version`) the change was made on; another one "
        "answers 409 `booking_version_conflict`.",
    )


class TimeOffInputSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")


class TimeOffCreatedSerializer(serializers.Serializer[dict[str, Any]]):
    time_off = TimeOffSerializer()
    #: The person's visits the absence runs into; they stay until someone moves them.
    conflicts = serializers.IntegerField()


class PersonInvitationSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()


class IntervalSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class AwayIntervalSerializer(IntervalSerializer):
    #: Null for whoever may not see it (ADR-058 §9).
    reason = serializers.CharField(allow_null=True)


class PersonDaySerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    #: Working hours that day, as instants.
    works = IntervalSerializer(many=True)
    time_off = AwayIntervalSerializer(many=True)
    #: Visits that occupy the person, buffers included.
    busy = IntervalSerializer(many=True)


class PeopleDaySerializer(serializers.Serializer[dict[str, Any]]):
    date = serializers.DateField()
    timezone = serializers.CharField()
    items = PersonDaySerializer(many=True)


class StaffMetricSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    value = serializers.IntegerField()
    #: "count", "minutes" or "money" (minor units of the organization's currency).
    unit = serializers.CharField()
    #: A number's parts, e.g. visits as the lead and in the crew.
    parts = serializers.DictField(child=serializers.IntegerField())
    #: The same number over the period before; null for a state like today's stock.
    previous = serializers.IntegerField(allow_null=True)


class StaffFactGroupSerializer(serializers.Serializer[dict[str, Any]]):
    #: The module that counts: "calendar", "inventory", a product's own.
    provider = serializers.CharField()
    metrics = StaffMetricSerializer(many=True)


class StaffFactsSerializer(serializers.Serializer[dict[str, Any]]):
    """A person's numbers for a period (team plan, phase 5)."""

    period_from = serializers.DateField()
    period_to = serializers.DateField()
    previous_from = serializers.DateField()
    previous_to = serializers.DateField()
    groups = StaffFactGroupSerializer(many=True)


class StaffEventSerializer(serializers.Serializer[dict[str, Any]]):
    at = serializers.DateTimeField()
    kind = serializers.CharField()
    event = serializers.CharField()
    #: What the panel needs to tell the event: names, numbers, times.
    params = serializers.DictField()
    value = serializers.IntegerField(allow_null=True)
    unit = serializers.CharField(allow_blank=True)


class StaffHistorySerializer(serializers.Serializer[dict[str, Any]]):
    period_from = serializers.DateField()
    period_to = serializers.DateField()
    #: The kinds the viewer may filter by.
    kinds = serializers.ListField(child=serializers.CharField())
    items = StaffEventSerializer(many=True)
    #: Pass as `before` for the next, older page; null: nothing older.
    next_before = serializers.DateTimeField(allow_null=True)


class PerformanceMetricSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    unit = serializers.CharField()


class PerformanceColumnSerializer(serializers.Serializer[dict[str, Any]]):
    provider = serializers.CharField()
    metrics = PerformanceMetricSerializer(many=True)


class PerformanceRowSerializer(serializers.Serializer[dict[str, Any]]):
    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    membership_id = serializers.UUIDField(allow_null=True)
    team_ids = serializers.ListField(child=serializers.UUIDField())
    #: provider → metric key → value.
    groups = serializers.DictField(child=serializers.DictField(child=serializers.IntegerField()))


class PerformanceSerializer(serializers.Serializer[dict[str, Any]]):
    period_from = serializers.DateField()
    period_to = serializers.DateField()
    columns = PerformanceColumnSerializer(many=True)
    items = PerformanceRowSerializer(many=True)
