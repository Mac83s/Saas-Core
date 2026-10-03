"""The assistant's commands for services, places, people and working hours
(ADR-076 §1, A1b-12, A2).

Thin adapters over the setup services the panel's Ustawienia › Usługi i grafik
calls (ADR-072 §11): the same validation, the same preview — the write run in a
savepoint that is rolled back — the same receipt per key and the same version
check. A service the assistant creates is always switched off: switching it on
makes it bookable by the public, which is the person's own step. A place is
added the way the panel adds one — switched on and shown in online booking —
so adding one takes the click of a change to working configuration. So does a
person, who is in the team's calendar at once; an invitation to the panel is
an e-mail to somebody else and an account, and takes a click of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from typing import Any, cast
from uuid import UUID

from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.api import CommandSpec, Effect, Preview, register_command

from .models import AvailabilityRule, Location, Service, StaffChoice, TimeModel
from .offer_settings import SLOT_STEPS
from .presets import apply_preset, list_presets
from .serializers import (
    PersonCreateSerializer,
    PersonHoursInputSerializer,
    PlaceInputSerializer,
    PlaceUpdateSerializer,
    PresetApplyInputSerializer,
    ServiceInputSerializer,
    ServiceUpdateSerializer,
)
from .services import BOOKING_ENABLED, BOOKING_MANAGE
from .setup import list_setup, save_location, save_service
from .staff import add_person, person_detail, set_person_hours
from .views import _place_payload, _preset_payload, _resource_payload, _service_setup_payload

#: What the assistant may set on a service; `active`, `online` and `materials`
#: stay the person's (switching on and showing online is publishing, materials
#: touch the warehouse).
_SERVICE_FIELDS = (
    "name",
    "duration_minutes",
    "buffer_before_minutes",
    "buffer_after_minutes",
    "minimum_notice_minutes",
    "staff_count",
    "public_staff_choice",
    "slot_step_minutes",
    "staff_ids",
    "location_ids",
    "resource_ids",
)
#: What the assistant may set on a place; `active` and `online` stay the
#: person's (switching a place off, hiding it from the site's form).
_PLACE_FIELDS = ("name", "address")
_IDS = {"type": ["array", "null"], "items": {"type": "string"}}


def _nullable(kind: str, description: str) -> dict[str, Any]:
    return {"type": [kind, "null"], "description": description}


_SERVICE_PROPERTIES: dict[str, Any] = {
    "name": _nullable("string", "The service's name as customers see it, up to 160 characters."),
    "duration_minutes": _nullable("integer", "How long one visit takes, in minutes."),
    "buffer_before_minutes": _nullable("integer", "Free time kept before a visit, in minutes."),
    "buffer_after_minutes": _nullable("integer", "Free time kept after a visit, in minutes."),
    "minimum_notice_minutes": _nullable(
        "integer", "How long before its start a visit can still be booked, in minutes."
    ),
    "staff_count": _nullable("integer", "How many people one visit needs."),
    "public_staff_choice": {
        "type": ["string", "null"],
        "enum": [*StaffChoice.values, None],
        "description": (
            "Whether a customer picks the person; picking a person fits a one-person service."
        ),
    },
    "slot_step_minutes": {
        "type": ["integer", "null"],
        "enum": [*SLOT_STEPS, None],
        "description": "How often a visit may start, from the start of a person's hours.",
    },
    "staff_ids": {
        **_IDS,
        "description": "Who does it (ids from booking.setup.read); replaces the list.",
    },
    "location_ids": {**_IDS, "description": "Where it is offered (place ids); replaces the list."},
    "resource_ids": {**_IDS, "description": "Resources a visit takes one of; replaces the list."},
}
_SERVICE_OUTPUT_PROPERTIES = {
    "service_id": {"type": "string"},
    "name": {"type": "string"},
    "active": {"type": "boolean"},
    "version": {"type": "integer"},
}
_SERVICE_OUTPUT = {
    "type": "object",
    "x-data-class": "public",
    "properties": _SERVICE_OUTPUT_PROPERTIES,
}


def _given(arguments: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: arguments[field] for field in fields if arguments.get(field) is not None}


def _effect(kind: str, resource: str, resource_id: str, pl: str, en: str) -> Effect:
    return Effect(
        kind=kind, resource=resource, resource_id=resource_id, summary={"pl": pl, "en": en}
    )


def _changed(changes: Mapping[str, Any]) -> str:
    return ", ".join(sorted(changes)) or "—"


# booking.setup.read@1


def _read_setup(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    value = list_setup()
    weeks = _weeks(call.context.organization_id, [item.id for item in value.staff])
    return cast(
        dict[str, Any],
        _jsonable({
            "services": [_service_setup_payload(item) for item in value.services],
            "locations": [_place_payload(item) for item in value.locations],
            "resources": [_resource_payload(item) for item in value.resources],
            "staff": [
                {
                    "id": item.id,
                    "name": item.display_name,
                    "hours_version": item.hours_version,
                    "hours": weeks.get(item.id, []),
                }
                for item in value.staff
            ],
        }),
    )


def _weeks(organization_id: UUID, staff_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
    """Each person's week as `booking.staff.hours.set` takes it and as its
    "no change" compares it (`staff._week`): a week read here and sent back
    changes nothing."""
    weeks: dict[UUID, list[dict[str, Any]]] = {}
    for rule in AvailabilityRule.all_objects.filter(
        organization_id=organization_id, staff_id__in=staff_ids, active=True
    ).order_by("weekday", "local_start", "id"):
        weeks.setdefault(rule.staff_id, []).append({
            "weekday": rule.weekday,
            "local_start": rule.local_start.isoformat("minutes"),
            "local_end": rule.local_end.isoformat("minutes"),
            "location_id": str(rule.location_id),
        })
    return weeks


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, time):
        # A stay's check-in and check-out, as the week's hours are written.
        return value.isoformat("minutes")
    return value


# booking.offer.create@1


def _new_service(arguments: Mapping[str, Any]) -> dict[str, Any]:
    serializer = ServiceInputSerializer(data=_given(arguments, _SERVICE_FIELDS))
    serializer.is_valid(raise_exception=True)
    return {**serializer.validated_data, "active": False}


def _preview_create(arguments: Mapping[str, Any], call: Any) -> Preview:
    data = _new_service(arguments)
    save_service(service_id=None, data=dict(data), preview=True)
    name = data["name"]
    # A new service has no id until it is saved, so none is named here: the
    # digest has to be the same for the same plan on the same state.
    return Preview(
        effects=(
            _effect(
                "created",
                "booking.service",
                "",
                f"Nowa usługa „{name}” — wyłączona, dopóki jej nie włączysz",
                f"New service “{name}” — switched off until you switch it on",
            ),
        ),
        observed_versions={},
    )


def _create(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    saved = save_service(
        service_id=None, data=_new_service(arguments), idempotency_key=call.idempotency_key
    )
    service = saved.value.service
    return {
        "service_id": str(service.id),
        "name": service.name,
        "active": service.active,
        "version": service.version,
    }


# booking.offer.update@1


def _service_changes(arguments: Mapping[str, Any], version: int) -> dict[str, Any]:
    serializer = ServiceUpdateSerializer(
        data={**_given(arguments, _SERVICE_FIELDS), "expected_version": version}
    )
    serializer.is_valid(raise_exception=True)
    changes = dict(serializer.validated_data)
    changes.pop("expected_version")
    return changes


def _id(arguments: Mapping[str, Any], field: str) -> UUID:
    try:
        return UUID(str(arguments[field]))
    except ValueError:
        raise ValidationError({field: ["To nie jest identyfikator."]}, code="invalid") from None


def _current_service(arguments: Mapping[str, Any], call: Any) -> Service:
    found = Service.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "service_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiej usługi.")
    return found


def _preview_update(arguments: Mapping[str, Any], call: Any) -> Preview:
    service = _current_service(arguments, call)
    saved = save_service(
        service_id=service.id,
        data=_service_changes(arguments, service.version),
        expected_version=service.version,
        preview=True,
    )
    return Preview(
        effects=(
            _effect(
                "updated",
                "booking.service",
                str(service.id),
                f"Usługa „{service.name}”: {_changed(saved.changes)}",
                f"Service “{service.name}”: {_changed(saved.changes)}",
            ),
        ),
        observed_versions={f"booking.service:{service.id}": service.version},
        # A switched-on service is bookable now: changing it changes what
        # customers book, not a draft.
        escalate_to="apply" if service.active else None,
    )


def _update(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    service_id = _id(arguments, "service_id")
    version = call.preview.observed_versions[f"booking.service:{service_id}"]
    saved = save_service(
        service_id=service_id,
        data=_service_changes(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    service = saved.value.service
    return {
        "service_id": str(service.id),
        "name": service.name,
        "active": service.active,
        "version": service.version,
    }


# booking.location.save@1


def _current_place(arguments: Mapping[str, Any], call: Any) -> Location | None:
    if arguments["location_id"] is None:
        return None
    found = Location.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "location_id")
    ).first()
    if found is None:
        raise NotFound("Nie ma takiego miejsca.")
    return found


def _place_data(arguments: Mapping[str, Any], version: int | None) -> dict[str, Any]:
    given = _given(arguments, _PLACE_FIELDS)
    serializer = (
        PlaceInputSerializer(data=given)
        if version is None
        else PlaceUpdateSerializer(data={**given, "expected_version": version})
    )
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    data.pop("expected_version", None)
    return data


def _preview_place(arguments: Mapping[str, Any], call: Any) -> Preview:
    place = _current_place(arguments, call)
    if place is None:
        data = _place_data(arguments, None)
        save_location(location_id=None, data=dict(data), preview=True)
        name = data["name"]
        # No id before the save, as with a new service; and no address in the
        # words of a consent — the audit keeps a place's address out as well.
        return Preview(
            effects=(
                _effect(
                    "created",
                    "booking.location",
                    "",
                    f"Nowe miejsce „{name}” — włączone i pokazywane w rezerwacji online",
                    f"New place “{name}” — switched on and shown in online booking",
                ),
            ),
            observed_versions={},
        )
    saved = save_location(
        location_id=place.id,
        data=_place_data(arguments, place.version),
        expected_version=place.version,
        preview=True,
    )
    return Preview(
        effects=(
            _effect(
                "updated",
                "booking.location",
                str(place.id),
                f"Miejsce „{place.name}”: {_changed(saved.changes)}",
                f"Place “{place.name}”: {_changed(saved.changes)}",
            ),
        ),
        observed_versions={f"booking.location:{place.id}": place.version},
    )


def _save_place(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    if arguments["location_id"] is None:
        saved = save_location(
            location_id=None,
            data=_place_data(arguments, None),
            idempotency_key=call.idempotency_key,
        )
    else:
        location_id = _id(arguments, "location_id")
        version = call.preview.observed_versions[f"booking.location:{location_id}"]
        saved = save_location(
            location_id=location_id,
            data=_place_data(arguments, version),
            expected_version=version,
            idempotency_key=call.idempotency_key,
        )
    place = saved.value
    return {
        "location_id": str(place.id),
        "name": place.name,
        "address": place.address,
        "active": place.active,
        "online": place.online,
        "version": place.version,
    }


# booking.staff.hours.set@1


def _rules(arguments: Mapping[str, Any], version: int) -> list[dict[str, Any]]:
    serializer = PersonHoursInputSerializer(
        data={"rules": arguments["rules"], "expected_version": version}
    )
    serializer.is_valid(raise_exception=True)
    return list(serializer.validated_data["rules"])


def _preview_hours(arguments: Mapping[str, Any], call: Any) -> Preview:
    staff_id = _id(arguments, "staff_id")
    detail = person_detail(staff_id)
    version = detail.person.staff.hours_version
    saved = set_person_hours(
        staff_id=staff_id,
        rules=_rules(arguments, version),
        expected_version=version,
        preview=True,
    )
    name = detail.person.staff.display_name
    days = len({rule["weekday"] for rule in arguments["rules"]})
    return Preview(
        effects=(
            _effect(
                "updated",
                "booking.staff_hours",
                str(staff_id),
                f"Godziny pracy: {name} — {days} dni w tygodniu"
                + ("" if saved.changes else " (bez zmian)"),
                f"Working hours: {name} — {days} days a week"
                + ("" if saved.changes else " (no change)"),
            ),
        ),
        observed_versions={f"booking.staff_hours:{staff_id}": version},
    )


def _hours(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    staff_id = _id(arguments, "staff_id")
    version = call.preview.observed_versions[f"booking.staff_hours:{staff_id}"]
    saved = set_person_hours(
        staff_id=staff_id,
        rules=_rules(arguments, version),
        expected_version=version,
        idempotency_key=call.idempotency_key,
    )
    return {"staff_id": str(staff_id), "hours_version": saved.version}


SETUP_READ = CommandSpec(
    name="booking.setup.read",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj usługi i grafik", "en": "Read services and hours"},
    summary={
        "pl": "Usługi, miejsca, zasoby i osoby, z wersjami do zmian.",
        "en": "Services, places, resources and people, with the versions changes name.",
    },
    model_description=(
        "Returns every service (with who does it, where and with which resource), place, "
        "resource and current person of the company, switched-off ones included, each "
        "with its id and version; a person comes with their working week (hours), in the "
        "shape booking.staff.hours.set takes. Use it before creating or changing a service "
        "or someone's working hours, to know the ids. It does not return bookings."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "services": {"type": "array"},
            "locations": {"type": "array"},
            "resources": {"type": "array"},
            # The company's people by name, as its booking page names them,
            # each with the week they work.
            "staff": {"type": "array", "x-data-class": "public_personal"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_setup,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

OFFER_CREATE = CommandSpec(
    name="booking.offer.create",
    version=1,
    module="shared.booking",
    title={"pl": "Dodaj usługę", "en": "Add a service"},
    summary={
        "pl": "Nowa usługa, wyłączona do czasu, aż ją włączysz.",
        "en": "A new service, switched off until you switch it on.",
    },
    model_description=(
        "Creates a service the company offers: name, duration, buffers, notice, how many "
        "people it needs, who does it and where. The service is always created switched "
        "off, so customers cannot book it yet; tell the person to switch it on in the panel. "
        "Pass null for anything left at its default; name and duration are required. Use "
        "booking.setup.read first for the ids of people, places and resources."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": list(_SERVICE_FIELDS),
        "properties": _SERVICE_PROPERTIES,
    },
    output_schema=_SERVICE_OUTPUT,
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_create,
    undo="none:a service is never deleted; it stays switched off",
    preview=_preview_create,
    no_version_reason="A new service has no version yet.",
)

OFFER_UPDATE = CommandSpec(
    name="booking.offer.update",
    version=1,
    module="shared.booking",
    title={"pl": "Zmień usługę", "en": "Change a service"},
    summary={
        "pl": "Nazwa, czas, przerwy, osoby i miejsca usługi.",
        "en": "A service's name, duration, buffers, people and places.",
    },
    model_description=(
        "Changes a service by its service_id: name, duration, buffers, notice, how many "
        "people it needs, who does it and where. Pass null for every field that stays as it "
        "is; a list given replaces the list. It cannot switch a service on or off. Use "
        "booking.setup.read first for the ids."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["service_id", *_SERVICE_FIELDS],
        "properties": {
            "service_id": {"type": "string", "description": "The service to change."},
            **_SERVICE_PROPERTIES,
        },
    },
    output_schema=_SERVICE_OUTPUT,
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_update,
    undo="command:booking.offer.update@1",
    preview=_preview_update,
    version_field="expected_version",
)

LOCATION_SAVE = CommandSpec(
    name="booking.location.save",
    version=1,
    module="shared.booking",
    title={"pl": "Dodaj albo zmień miejsce", "en": "Add or change a place"},
    summary={
        "pl": "Nazwa i adres miejsca, w którym firma przyjmuje.",
        "en": "The name and address of a place where the company takes visits.",
    },
    model_description=(
        "Adds a place where the company works and takes visits, or changes one: its name "
        "and street address. Pass location_id null to add a place (name is then required), "
        "or an id from booking.setup.read to change that place, with null for a field that "
        "stays as it is. A new place is switched on and shown in online booking; this "
        "cannot switch a place off or hide it, which the person does in the panel. A place "
        "takes visits once a service is offered there (location_ids of booking.offer.create "
        "or booking.offer.update) and someone works there (booking.staff.hours.set)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["location_id", *_PLACE_FIELDS],
        "properties": {
            "location_id": _nullable("string", "The place to change; null adds a new place."),
            "name": _nullable(
                "string", "The place's name as customers see it, up to 160 characters."
            ),
            "address": _nullable(
                "string", "Street address, up to 240 characters; an empty text clears it."
            ),
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "location_id": {"type": "string"},
            "name": {"type": "string"},
            "address": {"type": "string"},
            "active": {"type": "boolean"},
            "online": {"type": "boolean"},
            "version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="apply",
    run=_save_place,
    undo="command:booking.location.save@1",
    preview=_preview_place,
    version_field="expected_version",
)

STAFF_HOURS_SET = CommandSpec(
    name="booking.staff.hours.set",
    version=1,
    module="shared.booking",
    title={"pl": "Ustaw godziny pracy", "en": "Set working hours"},
    summary={
        "pl": "Cały tydzień pracy jednej osoby, reguła po regule.",
        "en": "One person's whole working week, rule by rule.",
    },
    model_description=(
        "Replaces one person's whole working week: a list of rules, each a weekday (0 is "
        "Monday), a start and an end in the company's local time as HH:MM, and the place "
        "(location_id) they work at. An empty list clears the week. Use booking.setup.read "
        "first for staff and place ids."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["staff_id", "rules"],
        "properties": {
            "staff_id": {"type": "string", "description": "The person whose week this is."},
            "rules": {
                "type": "array",
                "description": "The whole week; an empty list clears it.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["weekday", "local_start", "local_end", "location_id"],
                    "properties": {
                        "weekday": {"type": "integer", "description": "0 is Monday, 6 Sunday."},
                        "local_start": {"type": "string", "description": "Start, HH:MM."},
                        "local_end": {"type": "string", "description": "End, HH:MM."},
                        "location_id": {"type": "string", "description": "The place."},
                    },
                },
            },
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {"staff_id": {"type": "string"}, "hours_version": {"type": "integer"}},
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="apply",
    run=_hours,
    undo="command:booking.staff.hours.set@1",
    preview=_preview_hours,
    version_field="expected_version",
)


# booking.staff.add@1

#: What the assistant may say of a new person. Linking an existing member's
#: account, copying somebody's week and teams stay the panel's.
_PERSON_FIELDS = ("name", "phone", "service_ids", "hours", "invitation")


def _new_person(arguments: Mapping[str, Any]) -> dict[str, Any]:
    serializer = PersonCreateSerializer(data=_given(arguments, _PERSON_FIELDS))
    serializer.is_valid(raise_exception=True)
    return {field: serializer.validated_data.get(field) for field in _PERSON_FIELDS}


def _preview_person(arguments: Mapping[str, Any], call: Any) -> Preview:
    data = _new_person(arguments)
    # The whole write in a savepoint that is rolled back: the invitation's
    # e-mail is queued on commit, so none leaves here (ADR-072 §11).
    add_person(**data, preview=True)
    name, invitation = data["name"], data["invitation"]
    pl, en = f"Nowa osoba w zespole: „{name}”", f"New person in the team: “{name}”"
    if invitation:
        # The person agrees to an e-mail to this address and to this role.
        pl += f" — z zaproszeniem do panelu na adres {invitation['email']}"
        pl += f" (rola: {invitation['role']})"
        en += f" — with an invitation to the panel sent to {invitation['email']}"
        en += f" (role: {invitation['role']})"
    else:
        pl, en = f"{pl} — bez konta w panelu", f"{en} — without a panel account"
    # No id before the save, as with a new service.
    return Preview(
        effects=(_effect("created", "booking.staff", "", pl, en),),
        observed_versions={},
        # An e-mail to somebody else and an account for them: its own click.
        escalate_to="publish" if invitation else None,
    )


def _add_person(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    data = _new_person(arguments)
    person = add_person(**data, idempotency_key=call.idempotency_key).value
    return {
        "staff_id": str(person.id),
        "name": person.display_name,
        "takes_visits": bool(data["service_ids"]),
        "invited": person.invitation_id is not None,
    }


STAFF_ADD = CommandSpec(
    name="booking.staff.add",
    version=1,
    module="shared.booking",
    title={"pl": "Dodaj osobę do zespołu", "en": "Add a person to the team"},
    summary={
        "pl": "Nowa osoba w kalendarzu firmy, z kontem w panelu albo bez.",
        "en": "A new person in the company's calendar, with a panel account or without.",
    },
    model_description=(
        "Adds a person to the company's team: someone who does services and has a working "
        "week. Only the name is required; pass null for everything the person did not say. "
        "service_ids are the services they do (ids from booking.setup.read). hours gives "
        "the same hours on chosen weekdays at one place; for a week that differs by day, "
        "pass null and use booking.staff.hours.set afterwards. invitation sends an e-mail "
        "inviting them to the panel with a role — pass it only when the person asked for an "
        "account for them and gave the address themselves; null adds the person without an "
        "account, which is enough for them to be booked. Use booking.setup.read first: a "
        "person who is already listed there must not be added again. It cannot remove or "
        "rename a person; that is done in the panel."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": list(_PERSON_FIELDS),
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's name as the team sees it, up to 160 characters.",
            },
            "phone": _nullable("string", "Their phone number, up to 40 characters."),
            "service_ids": {**_IDS, "description": "The services they do; null means none yet."},
            "hours": {
                "type": ["object", "null"],
                "description": "The same working hours on the chosen weekdays; null means "
                "no hours yet.",
                "additionalProperties": False,
                "required": ["weekdays", "local_start", "local_end", "location_id"],
                "properties": {
                    "weekdays": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "0 is Monday, 6 Sunday.",
                    },
                    "local_start": {"type": "string", "description": "Start, HH:MM."},
                    "local_end": {"type": "string", "description": "End, HH:MM."},
                    "location_id": _nullable(
                        "string", "The place they work at; null takes the company's only place."
                    ),
                },
            },
            "invitation": {
                "type": ["object", "null"],
                "description": "An invitation to the panel by e-mail; null means no account.",
                "additionalProperties": False,
                "required": ["email", "role"],
                "properties": {
                    "email": {"type": "string", "description": "Where the invitation goes."},
                    "role": {
                        "type": "string",
                        "description": "The key of the role they get, e.g. `staff`; the "
                        "company's rules decide which roles this person may hand out.",
                    },
                },
            },
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "staff_id": {"type": "string"},
            # A person by name, as the company's booking page names them.
            "name": {"type": "string", "x-data-class": "public_personal"},
            "takes_visits": {"type": "boolean"},
            "invited": {"type": "boolean"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="apply",
    run=_add_person,
    undo="none:a person is not removed; their work is ended in the panel (Zespół)",
    preview=_preview_person,
    no_version_reason="A new person has no version yet.",
)


# booking.preset.list@1


def _read_presets(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return {"presets": [_preset_payload(item) for item in list_presets()]}


PRESET_LIST = CommandSpec(
    name="booking.preset.list",
    version=1,
    module="shared.booking",
    title={"pl": "Odczytaj wzorce ofert", "en": "Read offer presets"},
    summary={
        "pl": "Wzorce, od których firma może zacząć ofertę: gotowe i zapowiedziane.",
        "en": "The presets a company may start an offer from: ready and announced.",
    },
    model_description=(
        "Returns the booking presets this company may start an offer from, in the order "
        "the company sees them, each in its latest version: id, readiness, names and "
        "descriptions in pl and en, the time model (slot, range or session), what a "
        "booking takes, whether a person does it, where it happens, the inputs the "
        "preset needs from the company, and whether customers can book it through the "
        "company's site (online_booking). Only a preset with readiness `ready` can be "
        "applied; one marked `soon` is announced and cannot be used yet — say so instead "
        "of substituting another. A ready preset with online_booking `soon` makes an offer "
        "the company's team books in the panel; tell the person that booking through the "
        "site is coming soon for it. This list is the only source of preset ids."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {"presets": {"type": "array"}},
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="read",
    run=_read_presets,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# booking.preset.apply@1

_PRESET_FIELDS = ("preset_id", "version", "name", "duration_minutes", "staff_ids", "location_ids")


def _from_preset(arguments: Mapping[str, Any]) -> dict[str, Any]:
    serializer = PresetApplyInputSerializer(data=_given(arguments, _PRESET_FIELDS))
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _preview_apply(arguments: Mapping[str, Any], call: Any) -> Preview:
    data = _from_preset(arguments)
    service = apply_preset(**data, preview=True).value.service
    name = data["name"]
    # What the offer still needs from the person, said before they agree.
    pl, en = "", ""
    if service.time_model == TimeModel.RANGE:
        pl += " Jednostki i ceny dodasz w panelu."
        en += " You add its units and prices in the panel."
    if not service.online:
        pl += " Rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce."
        en += " The team books it in the panel; booking through the site is coming soon."
    # No id before the save, as for booking.offer.create@1.
    return Preview(
        effects=(
            _effect(
                "created",
                "booking.service",
                "",
                f"Nowa usługa „{name}” ze wzorca — wyłączona, dopóki jej nie włączysz.{pl}",
                f"New service “{name}” from a preset — switched off until you switch it on.{en}",
            ),
        ),
        observed_versions={},
    )


def _apply(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    saved = apply_preset(**_from_preset(arguments), idempotency_key=call.idempotency_key)
    service = saved.value.service
    return {
        "service_id": str(service.id),
        "name": service.name,
        "active": service.active,
        "version": service.version,
        "preset_id": service.preset_id,
        "preset_version": service.preset_version,
    }


PRESET_APPLY = CommandSpec(
    name="booking.preset.apply",
    version=1,
    module="shared.booking",
    title={"pl": "Zacznij usługę od wzorca", "en": "Start a service from a preset"},
    summary={
        "pl": "Nowa usługa ze wzorca, wyłączona do czasu, aż ją włączysz.",
        "en": "A new service from a preset, switched off until you switch it on.",
    },
    model_description=(
        "Creates one service from a booking preset: the preset decides how it is booked, "
        "you give its name and, for a preset with time model `slot`, how long a visit "
        "takes. Take the preset id from booking.preset.list; only a preset with readiness "
        "`ready` applies — `preset_not_ready` and `preset_unknown` come back on the field "
        "preset_id, and then say so instead of trying another preset. It creates the "
        "service only, always switched off: no place, person, unit, price or working hours "
        "are made — a stay's or a rental's units and every price the person adds in the "
        "panel. Pass staff_ids and location_ids only for people and places that exist "
        "(ids from booking.setup.read); null leaves the service without them, none is "
        "picked for you. Pass null for version to take the latest. Tell the person to "
        "switch the service on in the panel when it is complete."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": list(_PRESET_FIELDS),
        "properties": {
            "preset_id": {"type": "string", "description": "From booking.preset.list."},
            "version": _nullable("integer", "The preset's version; null takes the latest."),
            "name": {
                "type": "string",
                "description": "The service's name as customers see it, up to 160 characters.",
            },
            "duration_minutes": _nullable(
                "integer", "How long one visit takes, in minutes; required for a `slot` preset."
            ),
            "staff_ids": {**_IDS, "description": "Who does it; null means nobody yet."},
            "location_ids": {**_IDS, "description": "Where it is offered; null means nowhere yet."},
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": "public",
        "properties": {
            **_SERVICE_OUTPUT_PROPERTIES,
            "preset_id": {"type": "string"},
            "preset_version": {"type": "integer"},
        },
    },
    permission=BOOKING_MANAGE,
    entitlement=BOOKING_ENABLED,
    risk="draft",
    run=_apply,
    undo="discard_run",
    preview=_preview_apply,
    no_version_reason="A new service has no version yet.",
)


def register_booking_commands() -> None:
    for spec in (
        SETUP_READ,
        OFFER_CREATE,
        OFFER_UPDATE,
        LOCATION_SAVE,
        STAFF_HOURS_SET,
        STAFF_ADD,
        PRESET_LIST,
        PRESET_APPLY,
    ):
        register_command(spec)
