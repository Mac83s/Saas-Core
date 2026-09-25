from __future__ import annotations

from typing import Any

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

from .models import AnimalSex, AnimalStatus, HealthEntryKind
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
    #: Wpisane przez firmę, jeszcze nieprzejrzane przez hodowcę.
    review_requested_at = serializers.DateTimeField(read_only=True, allow_null=True)
    #: W karencji do (mleko, mięso) — z wpisów, które jeszcze trwają.
    withdrawal_milk_until = serializers.DateTimeField(read_only=True, allow_null=True)
    withdrawal_meat_until = serializers.DateTimeField(read_only=True, allow_null=True)
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
    #: `true` zdejmuje znacznik „do przejrzenia"; niczego nie kasuje.
    reviewed = serializers.BooleanField(required=False)


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


class AnimalHealthEntrySerializer(serializers.Serializer[Any]):
    """One entry of an animal's history, as the keeper reads it."""

    id = serializers.UUIDField()
    animal_id = serializers.UUIDField()
    kind = serializers.CharField()
    occurred_on = serializers.DateField()
    source = serializers.CharField()  # type: ignore[assignment]
    source_reference = serializers.CharField()
    author_name = serializers.CharField()
    author_organization_name = serializers.CharField()
    #: Written by somebody else's organization; set by the use case.
    author_is_external = serializers.BooleanField(default=False)
    private = serializers.BooleanField()
    #: Identyfikatory zdjęć autora; plik zostaje u niego, czytamy przez wpis.
    photos = serializers.ListField(child=serializers.UUIDField())
    summary = serializers.CharField()
    details = serializers.DictField()
    withdrawal_milk_until = serializers.DateTimeField(allow_null=True)
    withdrawal_meat_until = serializers.DateTimeField(allow_null=True)
    published_at = serializers.DateTimeField()


class AnimalHealthInputSerializer(serializers.Serializer[Any]):
    """An entry written here by hand. `source` belongs to the server."""

    kind = serializers.ChoiceField(choices=HealthEntryKind.choices, default=HealthEntryKind.NOTE)
    occurred_on = serializers.DateField(required=False)
    summary = serializers.CharField(max_length=240)
    details = serializers.DictField(required=False)
    private = serializers.BooleanField(required=False, default=False)
    photos = serializers.ListField(child=serializers.UUIDField(), required=False)


class FarmActivationCodeSerializer(serializers.Serializer[Any]):
    """The code is returned once, when it is issued; only its digest is kept."""

    code = serializers.CharField()
    expires_at = serializers.DateTimeField()


class FarmActivationRedeemSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(max_length=40)


class FarmHerdPushSerializer(serializers.Serializer[Any]):
    """Ile sztuk dopisano, ile poprawiono, ile było już zgodnych."""

    added = serializers.IntegerField()
    updated = serializers.IntegerField()
    unchanged = serializers.IntegerField()


class FarmShareSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    registry_farm_id = serializers.UUIDField()
    company_farm_id = serializers.UUIDField()
    company_organization_id = serializers.UUIDField()
    registry_organization_id = serializers.UUIDField()
    can_write_herd = serializers.BooleanField()
    #: Zgoda rolnika na grafik firmy; domyślnie wyłączona (ADR-052 pkt 4).
    can_publish_schedule = serializers.BooleanField()
    can_publish_health = serializers.BooleanField()
    basis = serializers.CharField()
    status = serializers.CharField()
    granted_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    #: The other side, as the caller sees it: set by `list_shares`.
    partner_name = serializers.CharField()
    partner_is_company = serializers.BooleanField()


class FarmShareScheduleSerializer(serializers.Serializer[Any]):
    """Zgoda rolnika na grafik firmy — włączana i wyłączana tym samym polem."""

    can_publish_schedule = serializers.BooleanField()


class FarmVisitEntrySerializer(serializers.Serializer[Any]):
    """Jedna wizyta firmy w gospodarstwie, jak czyta ją rolnik (ADR-052).

    Bez `source` i `source_reference`: to numer wizyty w systemie firmy, a nie
    coś, czym rolnik operuje.
    """

    id = serializers.UUIDField()
    status = serializers.CharField()
    scheduled_for = serializers.DateTimeField(allow_null=True)
    occurred_on = serializers.DateField(allow_null=True)
    company_name = serializers.CharField()
    summary = serializers.CharField()
    #: Raport w kształcie rozwiązanym przez wertykał (ADR-052 pkt 7).
    details = serializers.DictField()


class FarmTakeoverSerializer(serializers.Serializer[Any]):
    """What the farmer got: the farm, whether it is new, and its new animals."""

    farm = FarmSerializer()
    created = serializers.BooleanField()
    animals_added = serializers.IntegerField()
    share = FarmShareSerializer()
