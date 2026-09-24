from __future__ import annotations

from typing import Any

from rest_framework import serializers


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


class StaffUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    name = serializers.CharField(max_length=160, required=False)
    active = serializers.BooleanField(required=False)
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
    locale = serializers.ChoiceField(choices=("pl", "en"), default="pl")


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
    location_id = serializers.UUIDField()
    resource_id = serializers.UUIDField(required=False, allow_null=True)
    starts_at = serializers.DateTimeField()
    customer = CustomerInputSerializer()
    #: Pominięte: produkty z usługi. Podane: dokładnie te (wymaga inventory.use).
    materials = MaterialInputSerializer(many=True, required=False)


class PublicAppointmentCreateSerializer(serializers.Serializer[dict[str, Any]]):
    """The customer names the service, place and time; who takes the visit, the
    room it needs and the stock it uses are the server's (ADR-058 §4)."""

    service_id = serializers.UUIDField()
    location_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    customer = CustomerInputSerializer()


class RescheduleSerializer(serializers.Serializer[dict[str, Any]]):
    starts_at = serializers.DateTimeField()


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
    resource_name = serializers.CharField(allow_null=True)
    #: Tylko w panelu firmy; klient w self-service tego nie dostaje.
    materials = MaterialLineSerializer(many=True, required=False)
    self_service_token = serializers.CharField(required=False, allow_null=True)


class PublicAppointmentSerializer(serializers.Serializer[dict[str, Any]]):
    """What the customer sees of their visit: no people, no stock (ADR-058 §8)."""

    id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    service_name = serializers.CharField()
    location_name = serializers.CharField()
    status = serializers.CharField()
    self_service_token = serializers.CharField(required=False)


class AppointmentListSerializer(serializers.Serializer[dict[str, Any]]):
    items = AppointmentSerializer(many=True)


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


class ServiceSerializer(PublicServiceSerializer):
    #: Produkty z magazynu, które wizyta tej usługi zabiera.
    materials = MaterialInputSerializer(many=True, required=False)


class ResourceSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()


class CatalogSerializer(serializers.Serializer[dict[str, Any]]):
    locations = LocationSerializer(many=True)
    staff = StaffSerializer(many=True)
    services = ServiceSerializer(many=True)
    resources = ResourceSerializer(many=True)


class PublicCatalogSerializer(serializers.Serializer[dict[str, Any]]):
    """The catalogue without the team: who works here is not listed (ADR-058 §8)."""

    locations = LocationSerializer(many=True)
    services = PublicServiceSerializer(many=True)
    resources = ResourceSerializer(many=True)
    #: The organization's zone: the days and times offered are its wall clock.
    timezone = serializers.CharField()
