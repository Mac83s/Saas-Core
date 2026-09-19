from __future__ import annotations

from typing import Any

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

from .models import AnimalSex, AnimalStatus
from .species import SPECIES


class FarmSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    herd_number = serializers.CharField(read_only=True)
    tax_id = serializers.CharField(read_only=True)
    village = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    keeper_name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    housing = serializers.CharField(read_only=True)
    notes = serializers.CharField(read_only=True)
    active = serializers.BooleanField(read_only=True)
    animal_count = serializers.IntegerField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class FarmInputSerializer(serializers.Serializer[Any]):
    """What a client may send; kept apart from the response so the generated
    client does not demand `id` for a row that does not exist yet."""

    name = serializers.CharField(max_length=160)
    herd_number = serializers.CharField(max_length=24, required=False, allow_blank=True)
    tax_id = serializers.CharField(max_length=16, required=False, allow_blank=True)
    village = serializers.CharField(max_length=120, required=False, allow_blank=True)
    address = serializers.CharField(max_length=240, required=False, allow_blank=True)
    keeper_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    housing = serializers.CharField(max_length=80, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)


class FarmUpdateSerializer(FarmInputSerializer):
    name = serializers.CharField(max_length=160, required=False)


class AnimalSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    farm_id = serializers.UUIDField(read_only=True)
    farm_name = serializers.CharField(source="farm.name", read_only=True)
    species = serializers.CharField(read_only=True)
    national_id = serializers.CharField(read_only=True)
    working_number = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    sex = serializers.CharField(read_only=True)
    birth_date = serializers.DateField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    notes = serializers.CharField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class AnimalInputSerializer(serializers.Serializer[Any]):
    farm_id = serializers.UUIDField()
    species = serializers.ChoiceField(choices=tuple(SPECIES), required=False)
    national_id = serializers.CharField(max_length=40)
    working_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    sex = serializers.ChoiceField(choices=AnimalSex.choices, required=False)
    birth_date = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=AnimalStatus.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class AnimalUpdateSerializer(serializers.Serializer[Any]):
    national_id = serializers.CharField(max_length=40, required=False)
    working_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    sex = serializers.ChoiceField(choices=AnimalSex.choices, required=False)
    birth_date = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=AnimalStatus.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


#: `label` would shadow `Field.label` on a declared serializer class.
SpeciesListSerializer = inline_serializer(
    name="FarmSpecies",
    many=True,
    fields={
        "key": serializers.CharField(),
        "label": serializers.DictField(child=serializers.CharField()),
        "active": serializers.BooleanField(),
    },
)
