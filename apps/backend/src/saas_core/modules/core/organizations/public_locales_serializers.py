from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework import serializers

from .locales import ContentLocaleField


class PublicLocaleOptionSerializer(serializers.Serializer[dict[str, Any]]):
    code = serializers.CharField(help_text="Kod języka z rejestru platformy.")
    native_name = serializers.CharField(help_text="Nazwa języka w nim samym, np. Deutsch.")
    english_name = serializers.CharField()


class PublicLocalesLimitSerializer(serializers.Serializer[dict[str, Any]]):
    allowed = serializers.BooleanField(help_text="Czy plan pozwala teraz dodać język.")
    additional_max = serializers.IntegerField(
        allow_null=True, help_text="Ile języków poza pierwszym daje plan; null — bez limitu."
    )
    reason = serializers.CharField(
        allow_blank=True, help_text="Dlaczego nie, gdy `allowed` jest fałszem."
    )


class PublicLocalesSerializer(serializers.Serializer[dict[str, Any]]):
    public_locales = serializers.ListField(
        child=serializers.CharField(),
        help_text="Języki firmy w kolejności; pierwszy to język jej klientów.",
    )
    version = serializers.IntegerField(
        help_text="Wersja języków firmy; zapis z nieaktualną daje 409 settings_version_conflict."
    )
    offered = PublicLocaleOptionSerializer(
        many=True, help_text="Języki, które firma tego produktu może wybrać."
    )
    limit = PublicLocalesLimitSerializer()
    protected = serializers.DictField(
        child=serializers.CharField(),
        help_text="Języki, których nie da się usunąć, z kodem powodu "
        "(site_default_not_removable — język źródłowy strony).",
    )


class PublicLocalesChangeSerializer(serializers.Serializer[dict[str, Any]]):
    public_locales = serializers.ListField(
        child=ContentLocaleField(),
        min_length=1,
        max_length=len(settings.LOCALE_REGISTRY),
        help_text="Nowa lista języków firmy w kolejności; pierwszy to język jej klientów.",
    )
    expected_version = serializers.IntegerField(
        min_value=0, help_text="Wersja z odczytu (`version`)."
    )


class PublicLocalesPlanSerializer(serializers.Serializer[dict[str, Any]]):
    before = serializers.ListField(child=serializers.CharField())
    public_locales = serializers.ListField(
        child=serializers.CharField(), help_text="Języki firmy po zmianie."
    )
    added = serializers.ListField(child=serializers.CharField())
    removed = serializers.ListField(child=serializers.CharField())
    version = serializers.IntegerField(help_text="Wersja po zmianie.")
    limit = PublicLocalesLimitSerializer()
    person_gates = serializers.ListField(
        child=serializers.CharField(),
        help_text="Decyzje, które podejmuje tylko osoba (usunięcie języka).",
    )
