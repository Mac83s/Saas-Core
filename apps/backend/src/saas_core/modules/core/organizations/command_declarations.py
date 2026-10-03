"""The company's own commands: read its basic settings, change them (ADR-076 §1).

The pilot of the command layer: it runs through the registry, the executor,
consent, receipts, the manifest and the evals without any shared module. Both
are thin adapters over the services the panel's `organizations/current/` view
calls; validation, audit and the version check stay there.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .command_registry import CommandSpec, Effect, Preview, register_command
from .models import Organization
from .permissions import ORGANIZATION_READ, SETTINGS_MANAGE
from .public_locales import (
    PUBLIC_LOCALES_GROUP,
    REMOVAL_GATE,
    change_public_locales,
    offered_locales,
    read_public_locales,
)
from .serializers import OrganizationUpdateSerializer
from .services import current_organization, planned_organization, update_current_organization

_FIELDS = ("name", "default_locale", "timezone", "currency")
_LABELS = {
    "name": ("Nazwa", "Name"),
    "default_locale": ("Język panelu", "Panel language"),
    "timezone": ("Strefa czasowa", "Time zone"),
    "currency": ("Waluta", "Currency"),
}
_OUTPUT = {
    "type": "object",
    "x-data-class": "public",
    "properties": {
        "name": {"type": "string"},
        "slug": {"type": "string"},
        # The kind of company the product knows it as; set once, at creation.
        "organization_type": {"type": "string"},
        "default_locale": {"type": "string"},
        "timezone": {"type": "string"},
        "currency": {"type": "string"},
        "version": {"type": "integer"},
    },
}


def _settings(organization: Organization) -> dict[str, Any]:
    return {
        "name": organization.name,
        "slug": organization.slug,
        "organization_type": organization.organization_type,
        "default_locale": organization.default_locale,
        "timezone": organization.timezone,
        "currency": organization.currency,
        "version": organization.version,
    }


def _read(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return _settings(current_organization())


def _changes(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """The fields to change, checked by the panel's own serializer; null keeps
    a field as it is."""
    given = {field: arguments[field] for field in _FIELDS if arguments[field] is not None}
    serializer = OrganizationUpdateSerializer(data={**given, "version": 1})
    serializer.is_valid(raise_exception=True)
    return {
        field: value for field, value in serializer.validated_data.items() if field != "version"
    }


def _preview_update(arguments: Mapping[str, Any], call: Any) -> Preview:
    planned, changed = planned_organization(changes=_changes(arguments))
    effects = (
        (
            Effect(
                kind="updated",
                resource="organization",
                resource_id=str(planned.id),
                summary={
                    language: "; ".join(
                        f"{_LABELS[field][index]}: {old} → {new}"
                        for field, (old, new) in changed.items()
                    )
                    for index, language in enumerate(("pl", "en"))
                },
            ),
        )
        if changed
        else ()
    )
    # The version the person sees; the save refuses if it moved since.
    return Preview(effects=effects, observed_versions={_resource(call): planned.version})


def _update(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    version = call.preview.observed_versions[_resource(call)]
    access = update_current_organization(changes={**_changes(arguments), "version": version})
    return _settings(access.organization)


def _resource(call: Any) -> str:
    return f"organization:{call.context.organization_id}"


ORGANIZATION_READ_COMMAND = CommandSpec(
    name="organization.read",
    version=1,
    module="core.organizations",
    title={"pl": "Odczytaj dane firmy", "en": "Read company details"},
    summary={
        "pl": "Nazwa, język panelu, strefa czasowa i waluta firmy.",
        "en": "The company's name, panel language, time zone and currency.",
    },
    model_description=(
        "Returns the company's basic settings: name, slug, the kind of company "
        "(organization_type, fixed at creation), panel language (pl or en), IANA time "
        "zone, ISO 4217 currency and the settings version. Use it before proposing a "
        "change to them. It does not return the site's public languages, the company "
        "profile or billing."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema=_OUTPUT,
    permission=ORGANIZATION_READ,
    risk="read",
    run=_read,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

ORGANIZATION_UPDATE_COMMAND = CommandSpec(
    name="organization.update",
    version=1,
    module="core.organizations",
    title={"pl": "Zmień dane firmy", "en": "Change company details"},
    summary={
        "pl": "Nazwa, język panelu, strefa czasowa albo waluta firmy.",
        "en": "The company's name, panel language, time zone or currency.",
    },
    model_description=(
        "Changes the company's name, panel language, time zone or currency. Pass null "
        "for every field that should stay as it is; at least one field must change. "
        "Use it when the person asks for one of these changes. Do not use it for the "
        "site's public languages, the public company profile or billing."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": list(_FIELDS),
        "properties": {
            "name": {
                "type": ["string", "null"],
                "description": "The company's new name, up to 160 characters; null keeps it.",
            },
            "default_locale": {
                "type": ["string", "null"],
                "enum": ["pl", "en", None],
                "description": "Language of the panel and of e-mails to the team; null keeps it.",
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "IANA time zone such as Europe/Warsaw; null keeps it.",
            },
            "currency": {
                "type": ["string", "null"],
                "description": "ISO 4217 currency code such as PLN or EUR; null keeps it.",
            },
        },
    },
    output_schema=_OUTPUT,
    permission=SETTINGS_MANAGE,
    risk="apply",
    run=_update,
    undo="command:organization.update@1",
    preview=_preview_update,
    version_field="version",
)


_LOCALES_OUTPUT = {
    "type": "object",
    "x-data-class": "public",
    "properties": {
        "public_locales": {"type": "array", "items": {"type": "string"}},
        "version": {"type": "integer"},
        "offered": {"type": "array", "items": {"type": "string"}},
        "additional_max": {"type": ["integer", "null"]},
        "adding_allowed": {"type": "boolean"},
        "protected": {"type": "array", "items": {"type": "string"}},
    },
}


def _locales() -> dict[str, Any]:
    state = read_public_locales()
    return {
        "public_locales": list(state.locales),
        "version": state.version,
        "offered": list(state.offered),
        "additional_max": state.limit.additional_max,
        "adding_allowed": state.limit.allowed,
        "protected": sorted(state.protected),
    }


def _read_locales(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    return _locales()


def _locales_resource(call: Any) -> str:
    return f"{PUBLIC_LOCALES_GROUP}:{call.context.organization_id}"


def _preview_locales(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = read_public_locales()
    plan = change_public_locales(
        locales=arguments["public_locales"],
        expected_version=current.version,
        idempotency_key="",
        preview=True,
    )
    moved = len(plan.redirects)
    summary = {
        "pl": f"Języki firmy: {', '.join(plan.before)} → {', '.join(plan.after)}"
        + (f"; adresy przekierowane do języka źródłowego: {moved}" if moved else ""),
        "en": f"Company languages: {', '.join(plan.before)} → {', '.join(plan.after)}"
        + (f"; addresses redirected to the source language: {moved}" if moved else ""),
    }
    effects = (
        (
            Effect(
                kind="updated",
                resource=PUBLIC_LOCALES_GROUP,
                resource_id=str(call.context.organization_id),
                summary=summary,
            ),
        )
        if plan.after != plan.before
        else ()
    )
    return Preview(
        effects=effects,
        observed_versions={_locales_resource(call): current.version},
        # Removing a language takes its pages off the site at once.
        escalate_to="publish" if plan.removed else None,
        person_gates=plan.person_gates,
    )


def _update_locales(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    change_public_locales(
        locales=arguments["public_locales"],
        expected_version=int(call.preview.observed_versions[_locales_resource(call)]),
        idempotency_key=f"command:{call.idempotency_key}",
    )
    return _locales()


PUBLIC_LOCALES_READ_COMMAND = CommandSpec(
    name="organization.public_locales.read",
    version=1,
    module="core.organizations",
    title={"pl": "Odczytaj języki firmy", "en": "Read the company's languages"},
    summary={
        "pl": "Języki, w których firma mówi do klientów, i co można dodać.",
        "en": "The languages the company speaks to customers in, and what can be added.",
    },
    model_description=(
        "Returns the company's content languages in order (the first is its customers' "
        "language), their version, the languages this product offers, how many languages "
        "beyond the first the plan allows (null: no limit), whether adding is allowed now, "
        "and the languages that cannot be removed (a site's source language). Use it before "
        "proposing a change of languages. It does not translate anything."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema=_LOCALES_OUTPUT,
    permission=ORGANIZATION_READ,
    risk="read",
    run=_read_locales,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

PUBLIC_LOCALES_UPDATE_COMMAND = CommandSpec(
    name="organization.public_locales.update",
    version=1,
    module="core.organizations",
    title={"pl": "Zmień języki firmy", "en": "Change the company's languages"},
    summary={
        "pl": "Dodaje, usuwa albo porządkuje języki, w których firma mówi do klientów.",
        "en": "Adds, removes or reorders the languages the company speaks to customers in.",
    },
    model_description=(
        "Replaces the company's content languages with the given ordered list; the first "
        "becomes its customers' language. Read them first with "
        "organization.public_locales.read@1 and pass the whole new list. Adding a language "
        "only enables it — nothing is translated and no credits are spent; the plan may "
        "limit how many languages are added. Removing a language takes its pages off the "
        "site at once and needs the person's confirmation; a site's source language cannot "
        "be removed. Do not use it for the panel's language (organization.update@1)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["public_locales"],
        "properties": {
            "public_locales": {
                "type": "array",
                "items": {"type": "string", "enum": list(offered_locales())},
                "description": "The company's languages after the change, in order; the "
                "first is its customers' language.",
            },
        },
    },
    output_schema=_LOCALES_OUTPUT,
    permission=SETTINGS_MANAGE,
    risk="apply",
    run=_update_locales,
    undo="command:organization.public_locales.update@1",
    preview=_preview_locales,
    version_field="version",
    person_gates=frozenset({REMOVAL_GATE}),
)


def register_organization_commands() -> None:
    register_command(ORGANIZATION_READ_COMMAND)
    register_command(ORGANIZATION_UPDATE_COMMAND)
    register_command(PUBLIC_LOCALES_READ_COMMAND)
    register_command(PUBLIC_LOCALES_UPDATE_COMMAND)
