"""Settings: what the platform and a company may set, declared once (ADR-078).

A module declares its company settings in `AppConfig.ready()`: one
`SettingGroup` (a form, a version token, a pair of assistant commands, one
owner of the write) and its `SettingSpec`s. A declaration that breaks the
contract stops the process at start, like a command's (ADR-076 §4).

The code default is today's behaviour; above it the platform's value — until
the platform settings exist, the Django setting named in `platform_env`, read
from `.env` — and above that the company's own choice, stored in
`organization_setting`. `settings_service.resolve()` says which one applies and
why. This first increment (R1) knows the company scope stored by core; values
of a narrower scope (a place, an offer, a person) live in their module's tables
and join with their first key.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .command_registry import RISKS, Effect, organization_modules
from .options import SETTING_TYPES, SETTING_UNITS

#: Where a value comes from, most general first (ADR-078 pkt 3).
SOURCES = ("code", "platform", "organization")
SCOPES = ("platform", "organization")
DATA_CLASSES = frozenset({"public", "public_personal", "personal"})

_GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_LOCALES = frozenset({"pl", "en"})


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """One setting. Its key is `<group>.<field>`; the field is its name in the
    group's API, its command and its errors."""

    key: str
    type: str
    #: Today's behaviour: what applies when nobody chose otherwise.
    default: Any
    label: Mapping[str, str]
    #: English, for the model: what the value does and what it does not.
    model_description: str
    help: Mapping[str, str] | None = None
    minimum: int | None = None
    maximum: int | None = None
    unit: str | None = None
    #: An `enum`'s values in order, each with its labels.
    values: tuple[tuple[str, Mapping[str, str]], ...] = ()
    max_length: int | None = None
    #: Another field of the group, a `bool`: this one matters only while it is on.
    depends_on: str | None = None
    #: The Django setting (named like its `.env` variable) that holds the
    #: platform's value until the platform settings have a table (UF-T16).
    platform_env: str | None = None
    data_class: str = "public"
    scopes: tuple[str, ...] = ("platform", "organization")

    @property
    def field(self) -> str:
        return self.key.rsplit(".", 1)[1]

    @property
    def group(self) -> str:
        return self.key.rsplit(".", 1)[0]


@dataclass(frozen=True, slots=True)
class SettingGroup:
    """A form of settings with one owner of the write and one version token."""

    key: str
    module: str
    title: Mapping[str, str]
    description: Mapping[str, str]
    #: Who changes the company's values; anyone in the company reads them.
    permission: str
    settings: tuple[SettingSpec, ...]
    #: A plan feature the group needs; None: none beyond the module's own.
    entitlement: str | None = None
    #: The assistant's class for a change (ADR-076 §2).
    risk: str = "apply"
    #: The panel's area the group belongs to.
    area: str = ""
    #: What a change would do beyond the values, for the preview — pure, no
    #: writes: `effects(before, after)`; values by field.
    effects: Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[Effect, ...]] | None = None
    #: Called in the change's transaction, after the values are saved.
    on_changed: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None
    #: The assistant's `read` and `update` commands, `name@version`.
    commands: tuple[str, str] | None = None
    fields: tuple[str, ...] = dataclass_field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(spec.field for spec in self.settings))

    def spec(self, field_name: str) -> SettingSpec:
        return next(spec for spec in self.settings if spec.field == field_name)


_groups: dict[str, SettingGroup] = {}
_keys: dict[str, SettingSpec] = {}
#: `name@version` → group: how the `settings` gate knows a command's group.
_command_groups: dict[str, str] = {}


def register_setting_group(group: SettingGroup) -> None:
    problems = _group_problems(group)
    if problems:
        raise ImproperlyConfigured(f"Ustawienia {group.key}: " + "; ".join(problems))
    existing = _groups.get(group.key)
    if existing is not None:
        if existing == group:
            return
        raise ImproperlyConfigured(f"Grupa ustawień {group.key} jest już zarejestrowana inaczej.")
    _groups[group.key] = group
    for spec in group.settings:
        _keys[spec.key] = spec
    if group.commands:
        for name in group.commands:
            _command_groups[name] = group.key


def registered_groups() -> tuple[SettingGroup, ...]:
    return tuple(_groups[key] for key in sorted(_groups))


def setting_group(key: str) -> SettingGroup:
    return _groups[key]


def setting_spec(key: str) -> SettingSpec:
    return _keys[key]


def group_for_command(command_key: str) -> SettingGroup | None:
    name = _command_groups.get(command_key)
    return _groups[name] if name else None


def organization_groups(organization_id: Any) -> tuple[SettingGroup, ...]:
    """The groups whose module the organization's type composes (ADR-050)."""
    reachable = organization_modules(organization_id)
    return tuple(group for group in registered_groups() if group.module in reachable)


def platform_value(spec: SettingSpec) -> Any:
    """The platform's value, or None when the platform has not set one."""
    if spec.platform_env is None or "platform" not in spec.scopes:
        return None
    return getattr(settings, spec.platform_env, None)


def check_value(spec: SettingSpec, value: Any) -> tuple[Any, str, str] | None:
    """The value as stored, or None; a problem as (None, message, code)."""
    kind = spec.type
    if kind == "bool":
        if not isinstance(value, bool):
            return None, "Podaj tak albo nie.", "invalid"
        return value, "", ""
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "Podaj liczbę całkowitą.", "invalid"
        if spec.minimum is not None and value < spec.minimum:
            return None, f"Najmniej {spec.minimum}.", "min_value"
        if spec.maximum is not None and value > spec.maximum:
            return None, f"Najwięcej {spec.maximum}.", "max_value"
        return value, "", ""
    if kind == "enum":
        allowed = [option for option, _ in spec.values]
        if value not in allowed:
            return None, f"Wybierz jedną z wartości: {', '.join(allowed)}.", "invalid_choice"
        return value, "", ""
    if kind == "date":
        try:
            parsed = (
                value
                if isinstance(value, date)
                else date.fromisoformat(value)
                if isinstance(value, str)
                else None
            )
        except ValueError:
            parsed = None
        if parsed is None:
            return None, "Podaj datę w formacie RRRR-MM-DD.", "invalid"
        return parsed.isoformat(), "", ""
    if kind == "text":
        if not isinstance(value, str):
            return None, "Podaj tekst.", "invalid"
        text = value.strip()
        if spec.max_length is not None and len(text) > spec.max_length:
            return None, f"Najwyżej {spec.max_length} znaków.", "max_length"
        return text, "", ""
    return None, "Nieznany typ ustawienia.", "invalid"


def schema_entry(spec: SettingSpec) -> dict[str, Any]:
    """The setting as `GET …/settings/schema/` and the options endpoints show it."""
    return {
        "key": spec.key,
        "type": spec.type,
        "minimum": spec.minimum,
        "maximum": spec.maximum,
        "unit": spec.unit,
        "values": (
            [{"value": value, "label": dict(labels)} for value, labels in spec.values]
            if spec.type == "enum"
            else None
        ),
        "default": spec.default,
        "label": dict(spec.label),
        "help": dict(spec.help) if spec.help else None,
        "description": spec.model_description,
        "scopes": list(spec.scopes),
        "depends_on": f"{spec.group}.{spec.depends_on}" if spec.depends_on else None,
    }


def _group_problems(group: SettingGroup) -> list[str]:
    problems: list[str] = []
    if not _GROUP_PATTERN.fullmatch(group.key):
        problems.append("klucz grupy ma postać przestrzeń.grupa")
    if group.module not in settings.ACTIVE_MODULES:
        problems.append(f"moduł {group.module} nie jest złożony w tym profilu")
    else:
        space = group.key.split(".")[0]
        owner = next((g for g in _groups.values() if g.key.split(".")[0] == space), None)
        if owner is not None and owner.module != group.module:
            problems.append(f"przestrzeń {space} należy do {owner.module}")
    descriptors = [settings.MODULE_CATALOG[module] for module in settings.ACTIVE_MODULES]
    if not any(group.permission in descriptor.permissions for descriptor in descriptors):
        problems.append(f"uprawnienia {group.permission} nie deklaruje żaden moduł")
    if group.entitlement is not None and not any(
        group.entitlement in descriptor.entitlements for descriptor in descriptors
    ):
        problems.append(f"cechy {group.entitlement} nie deklaruje żaden moduł")
    if group.risk not in RISKS or group.risk == "read":
        problems.append(f"klasa ryzyka zmiany {group.risk!r}")
    for label, texts in (("title", group.title), ("description", group.description)):
        if not _localized(texts):
            problems.append(f"{label} wymaga niepustego tekstu pl i en")
    if not group.settings:
        problems.append("grupa bez ustawień")
    if len(set(group.fields)) != len(group.fields):
        problems.append("pola grupy powtarzają się")
    for spec in group.settings:
        problems.extend(f"{spec.key}: {problem}" for problem in _spec_problems(group, spec))
    return problems


def _spec_problems(group: SettingGroup, spec: SettingSpec) -> list[str]:
    problems: list[str] = []
    if spec.group != group.key or not _FIELD_PATTERN.fullmatch(spec.field):
        problems.append(f"klucz ma postać {group.key}.<pole>")
    if spec.type not in SETTING_TYPES:
        problems.append(f"nieznany typ {spec.type!r}")
    if spec.unit is not None and spec.unit not in SETTING_UNITS:
        problems.append(f"nieznana jednostka {spec.unit!r}")
    if not _localized(spec.label) or (spec.help is not None and not _localized(spec.help)):
        problems.append("etykieta i pomoc wymagają tekstu pl i en")
    if not spec.model_description.strip():
        problems.append("model_description jest wymagany")
    if spec.data_class not in DATA_CLASSES:
        problems.append(f"klasa danych {spec.data_class!r} (health nigdy)")
    if not spec.scopes or set(spec.scopes) - set(SCOPES) or "organization" not in spec.scopes:
        problems.append(f"zasięgi to {list(SCOPES)} z firmą")
    if spec.type == "enum" and (
        not spec.values or not all(_localized(labels) for _, labels in spec.values)
    ):
        problems.append("enum wymaga wartości z etykietami pl i en")
    if spec.default is not None:
        checked = check_value(spec, spec.default)
        if checked is None or checked[1]:
            problems.append("wartość domyślna poza typem albo granicami")
    if spec.depends_on is not None and (
        spec.depends_on not in group.fields or group.spec(spec.depends_on).type != "bool"
    ):
        problems.append("depends_on wskazuje pole bool tej grupy")
    if spec.platform_env is not None:
        if not hasattr(settings, spec.platform_env):
            problems.append(f"brak ustawienia {spec.platform_env}")
        else:
            checked = check_value(spec, getattr(settings, spec.platform_env))
            if checked is None or checked[1]:
                problems.append(f"{spec.platform_env} poza typem albo granicami")
    return problems


def _localized(texts: Mapping[str, str] | None) -> bool:
    return (
        texts is not None
        and set(texts) == _LOCALES
        and all(isinstance(text, str) and text.strip() for text in texts.values())
    )
