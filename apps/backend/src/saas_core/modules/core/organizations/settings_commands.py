"""A settings group's assistant commands and the executor's `settings` gate
(ADR-078 pkt 1, 12; ADR-076 pkt 1).

The module names its commands in the group's declaration and registers what
`group_commands` builds: a read and an update over the same service as the
panel, with the strict schema, the preview, the version and the undo taken from
the declaration. The set of fields is frozen in the command's version — a new
key in the group needs a new version (`pnpm commands:check` sees the drift).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .command_registry import CommandSpec, Effect, Preview
from .context import TenantContext, require_tenant_context
from .permissions import ORGANIZATION_READ
from .settings_registry import (
    SettingGroup,
    SettingSpec,
    group_for_command,
    setting_group,
    typed_text,
    words_type,
)
from .settings_service import change_settings, group_locked, read_group


def settings_gate(
    spec: CommandSpec,
    context: TenantContext,
    arguments: Mapping[str, Any],
    preview: Preview | None,
) -> str | None:
    """The plan's word on a settings group, before any of its commands runs;
    other commands pass."""
    group = group_for_command(spec.key)
    if group is None:
        return None
    return group_locked(group, write=spec.risk != "read") or None


def group_commands(group: SettingGroup) -> tuple[CommandSpec, CommandSpec]:
    if group.commands is None:
        raise ValueError(f"Grupa {group.key} nie nazywa swoich poleceń.")
    read_name, update_name = (_split(name) for name in group.commands)
    resource = f"settings:{group.key}"

    def read(_arguments: Mapping[str, Any], _call: Any) -> dict[str, Any]:
        return _output(group)

    def preview(arguments: Mapping[str, Any], _call: Any) -> Preview:
        current = read_group(group.key)
        result = change_settings(
            group.key,
            changes=_changes(group, arguments),
            reset=arguments.get("reset") or (),
            expected_version=current.version,
            preview=True,
        )
        # The labels as this organization reads them: the registry's now, and
        # its type's own words when its product gave some (UX-082).
        current_group = setting_group(group.key)
        kind = words_type(require_tenant_context().organization_id)

        def label(field: str, language: str) -> str:
            spec = current_group.spec(field)
            return (typed_text(f"setting:{spec.key}.label", spec.label, kind) or spec.label)[
                language
            ]

        summary = {
            language: "; ".join(
                f"{label(field, language)}: {change['from']} → {change['to']}"
                for field, change in result.changes.items()
            )
            for language in ("pl", "en")
        }
        effects = (
            (
                Effect(kind="updated", resource=group.key, resource_id="", summary=summary),
                *result.effects,
            )
            if result.changes
            else ()
        )
        return Preview(effects=effects, observed_versions={resource: current.version})

    def update(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
        change_settings(
            group.key,
            changes=_changes(group, arguments),
            reset=arguments.get("reset") or (),
            expected_version=str(call.preview.observed_versions[resource]),
            idempotency_key=f"command:{call.idempotency_key}",
        )
        return _output(group)

    fields = ", ".join(spec.field for spec in group.settings)
    read_command = CommandSpec(
        name=read_name[0],
        version=read_name[1],
        module=group.module,
        title={
            "pl": f"Odczytaj ustawienia: {group.title['pl']}",
            "en": f"Read settings: {group.title['en']}",
        },
        summary=dict(group.description),
        model_description=(
            f"Returns the company's settings '{group.title['en']}' ({fields}): the value "
            "that applies to each, where it comes from (code, platform or the company) and "
            f"the version. Use it before proposing a change. {group.description['en']}"
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [],
            "properties": {},
        },
        output_schema=_output_schema(group),
        permission=ORGANIZATION_READ,
        risk="read",
        run=read,
        undo="none:a read changes nothing",
        no_preview_reason="A read changes nothing, so there is nothing to show first.",
        no_version_reason="A read checks no version.",
        entitlement=group.entitlement,
    )
    update_command = CommandSpec(
        name=update_name[0],
        version=update_name[1],
        module=group.module,
        title={
            "pl": f"Zmień ustawienia: {group.title['pl']}",
            "en": f"Change settings: {group.title['en']}",
        },
        summary=dict(group.description),
        model_description=(
            f"Changes the company's settings '{group.title['en']}'. Pass null for every field "
            "that should stay as it is; list in `reset` the fields to give back to the default "
            f"(the platform's or the code's). {group.description['en']}"
        ),
        input_schema=_input_schema(group),
        output_schema=_output_schema(group),
        permission=group.permission,
        risk=group.risk,
        run=update,
        undo=f"command:{group.commands[1]}",
        preview=preview,
        version_field="expected_version",
        entitlement=group.entitlement,
    )
    return read_command, update_command


def _changes(group: SettingGroup, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {field: arguments[field] for field in group.fields if arguments.get(field) is not None}


def _output(group: SettingGroup) -> dict[str, Any]:
    state = read_group(group.key)
    return {
        "values": {field: resolved.value for field, resolved in state.values.items()},
        "sources": {field: resolved.source for field, resolved in state.values.items()},
        "version": state.version,
    }


def _split(name: str) -> tuple[str, int]:
    base, version = name.rsplit("@", 1)
    return base, int(version)


def _input_schema(group: SettingGroup) -> dict[str, Any]:
    properties: dict[str, Any] = {
        spec.field: {
            **_json_type(spec, nullable=True),
            "description": f"{spec.model_description} Null keeps it as it is.",
        }
        for spec in group.settings
    }
    properties["reset"] = {
        "type": ["array", "null"],
        "items": {"type": "string", "enum": list(group.fields)},
        "description": "Fields to give back to the default (the platform's or the code's); "
        "null or an empty list resets nothing.",
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [*group.fields, "reset"],
        "properties": properties,
    }


def _output_schema(group: SettingGroup) -> dict[str, Any]:
    return {
        "type": "object",
        "x-data-class": "public",
        "properties": {
            "values": {
                "type": "object",
                "properties": {
                    spec.field: {
                        **_json_type(spec, nullable=spec.default is None),
                        "x-data-class": spec.data_class,
                    }
                    for spec in group.settings
                },
            },
            "sources": {
                "type": "object",
                "properties": {spec.field: {"type": "string"} for spec in group.settings},
            },
            "version": {"type": "string"},
        },
    }


def _json_type(spec: SettingSpec, *, nullable: bool = False) -> dict[str, Any]:
    kind: dict[str, Any]
    if spec.type == "bool":
        kind = {"type": "boolean"}
    elif spec.type == "int":
        kind = {"type": "integer"}
        if spec.minimum is not None:
            kind["minimum"] = spec.minimum
        if spec.maximum is not None:
            kind["maximum"] = spec.maximum
    elif spec.type == "date":
        kind = {"type": "string", "format": "date"}
    elif spec.type == "enum":
        kind = {"type": "string", "enum": [value for value, _ in spec.values]}
    else:
        kind = {"type": "string"}
        if spec.max_length is not None:
            kind["maxLength"] = spec.max_length
    if nullable:
        kind["type"] = [kind["type"], "null"]
        if "enum" in kind:
            kind["enum"] = [*kind["enum"], None]
    return kind
