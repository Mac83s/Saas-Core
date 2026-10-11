"""The assistant's commands for an offer's own form fields (ADR-076 §1;
ADR-072 §8 and §11, slice 5j).

Thin adapters over the setup service the panel calls: a read of what each
offer's booking form asks, and the write of one field.

**What a form asks is configuration; what a customer answers is not.** These
commands carry questions — a company's own words. No command here, and none
of the visit reads, returns an answer: an answer is a customer's personal
data, read in the panel by whoever sees that customer's phone.

A field of an offer that is still switched off changes nothing anybody
fills in, so it takes the click of a draft; on an offer customers book now
the preview raises it to `apply` — from that moment the form asks it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from rest_framework.exceptions import NotFound

from saas_core.modules.core.organizations.api import CommandSpec, Preview

from .command_declarations import _effect, _given, _id, _jsonable, _nullable
from .field_views import FormFieldInputSerializer, FormFieldUpdateSerializer, _field_payload
from .form_fields import FIELD_LIMITS, list_fields, save_field
from .models import FieldKind, FormField, Service
from .services import BOOKING_ENABLED, BOOKING_MANAGE

_PUBLIC = "public"
_KINDS = {
    FieldKind.TEXT.value: ("tekst", "text"),
    FieldKind.LONG_TEXT.value: ("dłuższy tekst", "a long text"),
    FieldKind.NUMBER.value: ("liczba", "a number"),
    FieldKind.DATE.value: ("data", "a date"),
    FieldKind.CHOICE.value: ("wybór z listy", "a choice"),
    FieldKind.CONSENT.value: ("zgoda do zaznaczenia", "a consent to tick"),
}

# --- booking.form_fields.read@1 ------------------------------------------------------


def _read_fields(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    fields = [_field_payload(item) for item in list_fields()]
    offers = Service.all_objects.filter(
        organization_id=call.context.organization_id,
        pk__in={item["service_id"] for item in fields},
    ).order_by("name", "pk")
    answer: dict[str, Any] = _jsonable({
        "fields": fields,
        "names": {str(offer.id): offer.name for offer in offers},
        "switched_off": [str(offer.id) for offer in offers if not offer.active],
        "limits": {key: value for key, value in FIELD_LIMITS.items() if key != "kinds"},
    })
    return answer


FIELDS_READ = CommandSpec(
    name="booking.form_fields.read",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj pola formularza rezerwacji", "en": "Read the booking form's fields"},
    summary={
        "pl": "O co formularz każdej usługi pyta klienta ponad imię i kontakt.",
        "en": "What each service's booking form asks beyond a name and a contact.",
    },
    model_description=(
        "Returns the fields the company added to its services' booking forms, in the "
        "form's order, switched-off ones included, each with its id and version: `name` "
        "is the question as the customer reads it (for kind `consent`, the statement they "
        "tick), `kind` one of text, long_text, number, date, choice or consent, `options` a "
        "choice's options, `mandatory` whether a customer must answer, "
        "`mandatory_for_staff` whether a mandatory field also binds the team booking in "
        "the panel. `names` gives the name of "
        "every service a field belongs to, by id; `switched_off` the ids of the services "
        "nobody can book yet; `limits` what a field may be. Use it before changing a "
        "field, to know the ids. These are the questions, never anybody's answers: what a "
        "customer answered is their personal data and no command returns it."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "fields": {"type": "array"},
            "names": {"type": "object"},
            "switched_off": {"type": "array"},
            "limits": {"type": "object"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_fields,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# --- booking.form_field.save@2 -------------------------------------------------------

# @2 takes `mandatory_for_staff`: the key set of a version's input is frozen.
_FIELD_FIELDS = (
    "service_id",
    "name",
    "kind",
    "options",
    "mandatory",
    "mandatory_for_staff",
    "position",
    "active",
)


def _field_data(arguments: Mapping[str, Any], version: int | None) -> dict[str, Any]:
    given = _given(arguments, _FIELD_FIELDS)
    if version is None:
        serializer: Any = FormFieldInputSerializer(data=given)
    else:
        # A field stays with its offer: the service is not a field of a change.
        given.pop("service_id", None)
        serializer = FormFieldUpdateSerializer(data={**given, "expected_version": version})
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("expected_version", None)
    return data


def _current_field(arguments: Mapping[str, Any], call: Any) -> FormField | None:
    if arguments["field_id"] is None:
        return None
    found = FormField.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "field_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiego pola.")
    return found


def _field_words(asked: FormField, at: int) -> str:
    words = [_KINDS[asked.kind][at]]
    if asked.kind == FieldKind.CHOICE:
        words.append(" / ".join(asked.option_list))
    words.append(
        (("obowiązkowe", "mandatory") if asked.mandatory else ("nieobowiązkowe", "optional"))[at]
    )
    if asked.mandatory and not asked.mandatory_for_staff:
        words.append(("zespół może pominąć", "the team may leave it empty")[at])
    if not asked.active:
        words.append(("wyłączone", "switched off")[at])
    return ", ".join(words)


def _preview_field(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = _current_field(arguments, call)
    version = current.version if current is not None else None
    saved = save_field(
        field_id=current.id if current is not None else None,
        data=_field_data(arguments, version),
        expected_version=version,
        preview=True,
    )
    asked = saved.value
    service = Service.all_objects.get(
        organization_id=call.context.organization_id, pk=asked.service_id
    )
    new = ("Nowe pole", "New field") if current is None else ("Pole", "Field")
    pl = f"{new[0]} formularza usługi „{service.name}”: „{asked.name}” — {_field_words(asked, 0)}"
    en = (
        f"{new[1]} of the booking form of “{service.name}”: “{asked.name}” — "
        f"{_field_words(asked, 1)}"
    )
    if service.active:
        pl += " — formularz pyta o nie od razu"
        en += " — the form asks it at once"
    return Preview(
        effects=(
            _effect(
                "created" if current is None else "updated",
                "booking.form_field",
                str(current.id) if current is not None else "",
                pl,
                en,
            ),
        ),
        observed_versions=(
            {f"booking.form_field:{current.id}": current.version} if current is not None else {}
        ),
        escalate_to="apply" if service.active else None,
    )


def _save_field(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    field_id = _id(arguments, "field_id") if arguments["field_id"] is not None else None
    version = (
        call.preview.observed_versions[f"booking.form_field:{field_id}"]
        if field_id is not None
        else None
    )
    saved = save_field(
        field_id=field_id,
        data=_field_data(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    asked = saved.value
    return {
        "field_id": str(asked.id),
        "service_id": str(asked.service_id),
        "name": asked.name,
        "kind": asked.kind,
        "options": asked.option_list,
        "mandatory": asked.mandatory,
        "mandatory_for_staff": asked.mandatory_for_staff,
        "position": asked.position,
        "active": asked.active,
        "version": asked.version,
    }


FIELD_SAVE = CommandSpec(
    name="booking.form_field.save",
    version=2,
    module="shared.booking",
    title={"pl": "Zapisz pole formularza rezerwacji", "en": "Save a booking form field"},
    summary={
        "pl": "O co formularz usługi pyta klienta: numer prawa jazdy, imię pupila, godzina.",
        "en": "What a service's booking form asks: a licence number, a pet's name, an hour.",
    },
    model_description=(
        "Adds a field to one service's booking form (field_id null, with service_id) or "
        "changes one (its field_id from booking.form_fields.read). `name` is the question "
        "as the customer reads it, in the company's first language; `kind` text, "
        "long_text (several lines, up to 500 characters), number, date, choice (give "
        "`options`, at least two) or consent — a box to tick whose "
        "`name` is the statement, kept word for word in the consent journal when ticked. "
        "`mandatory` true means a customer cannot book without answering (for a consent: "
        "without ticking). `mandatory_for_staff` (default true) matters only for a mandatory "
        "field: false lets the team leave it empty when booking for a customer in the "
        "panel, while a customer booking for themselves must always answer. `position` "
        "orders the form, smallest first; a new field goes "
        "last. A field is never deleted — bookings keep the question they were asked — "
        "only switched off with active false. What customers answer is their personal "
        "data, removed with the customer: never add a field that asks about health, "
        "beliefs or other special-category data — say that this needs the company's own "
        "legal basis and is not offered here. Pass null for every field that stays as it "
        "is; a new field needs service_id and name."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["field_id", *_FIELD_FIELDS],
        "properties": {
            "field_id": _nullable("string", "The field to change; null adds a new one."),
            "service_id": _nullable("string", "The service whose form a new field joins."),
            "name": _nullable("string", "The question as customers read it, up to 160 characters."),
            "kind": {
                "type": ["string", "null"],
                "enum": [*FieldKind.values, None],
                "description": "What the field takes.",
            },
            "options": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": "A choice's options in order, 2–20; ignored for other kinds.",
            },
            "mandatory": _nullable("boolean", "Whether a customer must answer to book."),
            "mandatory_for_staff": _nullable(
                "boolean",
                "For a mandatory field: whether the team booking in the panel must answer it "
                "too (true on a new field); false lets the team leave it empty.",
            ),
            "position": _nullable("integer", "The order on the form, smallest first."),
            "active": _nullable("boolean", "False switches the field off."),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "field_id": {"type": "string"},
            "service_id": {"type": "string"},
            "name": {"type": "string"},
            "kind": {"type": "string"},
            "options": {"type": "array"},
            "mandatory": {"type": "boolean"},
            "mandatory_for_staff": {"type": "boolean"},
            "position": {"type": "integer"},
            "active": {"type": "boolean"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_save_field,
    undo="command:booking.form_field.save@2",
    preview=_preview_field,
    version_field="expected_version",
)

# --- booking.form_field.save@1 -------------------------------------------------------
# ADR-076 §1: an old version lives while a plan or a consent may bind it. @1 keeps
# its frozen input (no `mandatory_for_staff`) and the same run: a new field binds
# the team, a changed one keeps what it had.


def _legacy(run: Any) -> Any:
    def wrapped(arguments: Mapping[str, Any], call: Any) -> Any:
        return run({**arguments, "mandatory_for_staff": None}, call)

    return wrapped


_LEGACY_PROPERTIES = {
    key: value
    for key, value in FIELD_SAVE.input_schema["properties"].items()
    if key != "mandatory_for_staff"
}

FIELD_SAVE_V1 = replace(
    FIELD_SAVE,
    version=1,
    input_schema={
        **FIELD_SAVE.input_schema,
        "required": ["field_id", *(k for k in _FIELD_FIELDS if k != "mandatory_for_staff")],
        "properties": _LEGACY_PROPERTIES,
    },
    run=_legacy(_save_field),
    preview=_legacy(_preview_field),
    undo="command:booking.form_field.save@2",
)

FIELD_COMMANDS = (FIELDS_READ, FIELD_SAVE_V1, FIELD_SAVE)
