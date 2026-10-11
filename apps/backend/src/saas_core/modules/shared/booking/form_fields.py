"""The offer's own fields of the booking form (ADR-072 §8, slice 5j).

A company asks its customer for what its kind of booking needs beyond a name
and a contact — a driving licence number at a rental, the pet's name at a pet
hotel, the arrival hour at a lodging. A `FormField` belongs to one offer, has
a kind (`text`, `long_text`, `number`, `choice`, `date`, `consent`), may be
mandatory — for the customer always, for the staff booking in the panel only
where `mandatory_for_staff` says so — and has its place in the order. The
public form reads the fields of what the customer books (`offered_fields`), in
the customer's language where the company translated them (`booking.catalog`, kind `field`).

A setup item like an extra (§11): a key with a receipt, a version, a preview;
never deleted — bookings name it — only switched off. What a preset says of
fields is copied with the offer (`copy_preset_fields`).

What may be set lives in one constant, `FIELD_LIMITS`, served with the list
(AGENTS.md: what a company could want otherwise is a setting, and one of an
offer lives in a named constant until the registry takes it).

What a customer answers is not here: `form_answers`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import ErrorDetail, ValidationError

from saas_core.content_protocol.provenance import ORIGIN_TEMPLATE, Provenance, unit_hash
from saas_core.content_protocol.units import UNIT_TEXT
from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.locales import organization_content_locales
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.decisions import FeatureOperation

from .form_answers import MAX_LONG_TEXT_ANSWER, MAX_TEXT_ANSWER
from .item_translations import (
    apply_item_translation,
    item_units,
    localized_texts,
    source_locale,
    translatable,
)
from .models import FieldKind, FormField, Service
from .rules import FIELD_CHANGED, _replay, _write
from .setup import Saved, _manage, _own, setup_write

#: What an offer's fields may be: the bounds, the kinds and their labels.
FIELD_LIMITS: dict[str, Any] = {
    #: Switched-on fields of one offer — a form longer than that is not filled.
    "max_fields": 20,
    "max_options": 20,
    "min_options": 2,
    "max_option_length": 80,
    "max_name_length": 160,
    "max_answer_length": MAX_TEXT_ANSWER,
    "max_long_answer_length": MAX_LONG_TEXT_ANSWER,
    "kinds": [
        {"value": FieldKind.TEXT.value, "label": {"pl": "Tekst", "en": "Text"}},
        {"value": FieldKind.LONG_TEXT.value, "label": {"pl": "Dłuższy tekst", "en": "Long text"}},
        {"value": FieldKind.NUMBER.value, "label": {"pl": "Liczba", "en": "Number"}},
        {"value": FieldKind.DATE.value, "label": {"pl": "Data", "en": "Date"}},
        {"value": FieldKind.CHOICE.value, "label": {"pl": "Wybór z listy", "en": "Choice"}},
        {
            "value": FieldKind.CONSENT.value,
            "label": {"pl": "Zgoda (pole do zaznaczenia)", "en": "Consent (a box to tick)"},
        },
    ],
}

_FIELDS = (
    "name",
    "service_id",
    "kind",
    "options",
    "mandatory",
    "mandatory_for_staff",
    "position",
    "active",
)


def _refuse(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: [ErrorDetail(message, code=code)]})


def list_fields() -> list[FormField]:
    _, organization = _manage(FeatureOperation.READ)
    return list(FormField.all_objects.filter(organization=organization))


@transaction.atomic
def save_field(
    *,
    field_id: UUID | None,
    data: dict[str, Any],
    idempotency_key: str = "",
    expected_version: int | None = None,
    preview: bool = False,
) -> Saved[FormField]:
    """A field of an offer's booking form: added, changed or switched off.
    `data["options"]` is a list of a choice's options, in order. Never deleted
    — bookings name it — only switched off."""
    context, organization = _manage()
    created = field_id is None
    return setup_write(
        context=context,
        action="field.create" if created else "field.update",
        target_id=field_id,
        request={"data": data, "expected_version": expected_version},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_field(context, organization, field_id, dict(data), expected_version),
        replay=lambda item_id: _replay(FormField, organization, item_id, created),
    )


def _write_field(
    context: TenantContext,
    organization: Organization,
    field_id: UUID | None,
    data: dict[str, Any],
    expected_version: int | None,
) -> Saved[FormField]:
    if "options" in data:
        # One per line in the row: the translation of a list is a list.
        data["options"] = "\n".join(str(option).strip() for option in data["options"] or ())
    saved = _write(
        context,
        organization,
        FormField,
        field_id,
        data,
        expected_version,
        _FIELDS,
        _check_field,
        FIELD_CHANGED,
    )
    if saved.created or set(saved.changes) & {"name", "options", "active"}:
        # The catalogue's text, or what it offers, changed (TL12c).
        from .translation_source import notify_catalog_changed  # noqa: PLC0415

        notify_catalog_changed(context=context)
    return saved


def _check_field(organization: Organization, asked: FormField) -> None:
    if asked.service_id is None:
        raise _refuse("service_id", "Wybierz usługę, której dotyczy pole.", "required")
    _own(Service, organization, [asked.service_id], "service_id")
    asked.name = asked.name.strip()
    if not asked.name:
        raise _refuse("name", "Wpisz pytanie, które zobaczy klient.", "required")
    others = FormField.all_objects.filter(
        organization=organization, service_id=asked.service_id
    ).exclude(pk=asked.pk)
    if others.filter(name__iexact=asked.name).exists():
        raise _refuse("name", "Ta usługa ma już takie pole.", "name_taken")
    if asked.kind == FieldKind.CHOICE:
        options = [line.strip() for line in asked.options.split("\n") if line.strip()]
        if len(options) < FIELD_LIMITS["min_options"]:
            raise _refuse("options", "Podaj co najmniej dwie możliwości.", "options_required")
        if len(options) > FIELD_LIMITS["max_options"]:
            raise _refuse(
                "options",
                f"Najwyżej {FIELD_LIMITS['max_options']} możliwości.",
                "options_too_many",
            )
        if any(len(option) > FIELD_LIMITS["max_option_length"] for option in options):
            raise _refuse(
                "options",
                f"Jedna możliwość ma najwyżej {FIELD_LIMITS['max_option_length']} znaków.",
                "option_too_long",
            )
        if len({option.casefold() for option in options}) != len(options):
            raise _refuse("options", "Możliwości się powtarzają.", "options_repeated")
        asked.options = "\n".join(options)
    else:
        asked.options = ""
    if asked.active and others.filter(active=True).count() >= FIELD_LIMITS["max_fields"]:
        raise _refuse(
            "service_id",
            f"Jedna usługa ma najwyżej {FIELD_LIMITS['max_fields']} włączonych pól.",
            "fields_too_many",
        )
    if asked._state.adding and not asked.position:
        # A new one goes last.
        last = others.aggregate(last=Max("position"))["last"]
        asked.position = (last or 0) + 1


def _options(asked: FormField, texts: Mapping[str, str]) -> list[dict[str, str]]:
    """A choice's options: `value` — the company's own word, which an answer
    sends back; `label` — how the form says it. A translation with another
    number of lines is not one of this list, and the company's own is shown."""
    own = asked.option_list
    said = [line.strip() for line in texts.get("options", "").split("\n") if line.strip()]
    labels = said if len(said) == len(own) else own
    return [{"value": value, "label": label} for value, label in zip(own, labels, strict=True)]


def offered_fields(
    organization: Organization, services: Sequence[Service], locale: str | None
) -> list[dict[str, Any]]:
    """What the booking form asks with each of these offers, in order: the
    switched-on fields, in the customer's language where the company
    translated them. One query, and one more for a language."""
    fields = list(
        FormField.all_objects.filter(
            organization=organization, service__in=list(services), active=True
        ).order_by("service_id", "position", "name", "id")
    )
    texts = localized_texts(translatable("field"), fields, locale) if locale and fields else {}
    return [
        {
            "id": asked.id,
            "service_id": asked.service_id,
            "name": texts.get(asked.id, {}).get("name", asked.name),
            "kind": asked.kind,
            "mandatory": asked.mandatory,
            "options": _options(asked, texts.get(asked.id, {})),
        }
        for asked in fields
    ]


def _first_label(organization: Organization, labels: Mapping[str, str]) -> str:
    """A label in the company's first language, else in English, else in Polish."""
    return str(
        labels.get(source_locale(organization)) or labels.get("en") or labels.get("pl") or ""
    )


def copy_preset_fields(
    context: TenantContext,
    organization: Organization,
    service_id: UUID,
    fields: Sequence[Mapping[str, Any]],
    *,
    first_position: int = 1,
) -> list[FormField]:
    """A preset's fields as the new offer's own (ADR-072 §10): each in the
    company's first language — else in English, else in Polish — and, in the
    company's other languages the preset speaks, as a translation that says
    it came from a template, so a person or the engine may replace it.
    Inside the write that makes the offer. `first_position` is where the first
    goes, for fields that follow others."""
    own = source_locale(organization)
    others = [code for code in organization_content_locales(organization) if code != own]
    entry = translatable("field")

    def said(labels: Mapping[str, str], locale: str) -> str:
        return str(labels.get(locale) or "")

    def first(labels: Mapping[str, str]) -> str:
        return _first_label(organization, labels)

    made = []
    for position, given in enumerate(fields, start=first_position):
        options = given.get("options") or []
        asked = _write_field(
            context,
            organization,
            None,
            {
                "service_id": service_id,
                "name": first(given["labels"]),
                "kind": given["type"],
                "mandatory": bool(given["mandatory"]),
                "mandatory_for_staff": bool(given.get("mandatoryForStaff", True)),
                "position": position,
                "options": [first(option["labels"]) for option in options],
            },
            None,
        ).value
        units = {unit.key: unit for unit in item_units(entry, asked)}
        for locale in others:
            texts = {"name": said(given["labels"], locale)}
            lines = [said(option["labels"], locale) for option in options]
            if lines and all(lines):
                texts["options"] = "\n".join(lines)
            written = {
                key: (
                    text,
                    Provenance(
                        origin=ORIGIN_TEMPLATE,
                        source_hash=units[key].source_hash,
                        written_hash=unit_hash(UNIT_TEXT, text),
                    ),
                )
                for key, text in texts.items()
                if text and key in units
            }
            if written:
                apply_item_translation(entry, asked, locale, written, actor_id=context.actor_id)
        made.append(asked)
    return made


def missing_kind_fields(organization: Organization, service: Service) -> list[Mapping[str, Any]]:
    """Of the fields the service's kind of visit brings, those it lacks: a
    field of the same name — switched on or off — counts as there."""
    declared = settings.APPOINTMENT_KIND_FIELDS.get(service.appointment_kind) or ()
    if not declared:
        return []
    names = {
        name.casefold()
        for name in FormField.all_objects.filter(
            organization=organization, service_id=service.id
        ).values_list("name", flat=True)
    }
    return [
        given
        for given in declared
        if _first_label(organization, given["labels"]).casefold() not in names
    ]


def copy_kind_fields(
    context: TenantContext, organization: Organization, service: Service
) -> list[FormField]:
    """The fields the service's kind of visit brings (`appointmentKindFields`
    in its module's descriptor), written as the preset's are, after the fields
    the service already has; ones it already has are left alone, so running it
    again adds nothing. Inside the write that makes the service, or the
    command that completes older ones."""
    missing = missing_kind_fields(organization, service)
    if not missing:
        return []
    last = FormField.all_objects.filter(organization=organization, service_id=service.id).aggregate(
        last=Max("position")
    )["last"]
    return copy_preset_fields(
        context, organization, service.id, missing, first_position=(last or 0) + 1
    )
