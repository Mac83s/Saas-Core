from __future__ import annotations

from typing import Any

from rest_framework import serializers


class FarmSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=160)
    village = serializers.CharField(max_length=120, required=False, allow_blank=True)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    keeper_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    housing = serializers.CharField(max_length=80, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    active = serializers.BooleanField(required=False, default=True)


class AnimalSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    farm_id = serializers.UUIDField(read_only=True)
    farm_name = serializers.CharField(source="farm.name", read_only=True)
    national_id = serializers.CharField(max_length=40)
    working_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    birth_date = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=("active", "sold", "culled", "dead"), required=False
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class FarmInputSerializer(serializers.Serializer[Any]):
    """What a client may send. Kept apart from the response on purpose: one
    serializer for both makes the generated client demand `id` when creating a
    row that does not have one yet."""

    name = serializers.CharField(max_length=160)
    village = serializers.CharField(max_length=120, required=False, allow_blank=True)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    keeper_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    housing = serializers.CharField(max_length=80, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)


class AnimalInputSerializer(serializers.Serializer[Any]):
    farm_id = serializers.UUIDField()
    national_id = serializers.CharField(max_length=40)
    working_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    birth_date = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=("active", "sold", "culled", "dead"), required=False
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class HerdVisitSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    farm_id = serializers.UUIDField(read_only=True)
    farm_name = serializers.CharField(source="farm.name", read_only=True)
    appointment_id = serializers.UUIDField(read_only=True)
    starts_at = serializers.DateTimeField(source="appointment.starts_at", read_only=True)
    status = serializers.CharField(source="appointment.status", read_only=True)
    arrived_at = serializers.DateTimeField(read_only=True)
    left_at = serializers.DateTimeField(read_only=True)
