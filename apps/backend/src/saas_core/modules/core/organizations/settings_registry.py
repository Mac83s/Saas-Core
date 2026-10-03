"""Settings: what the platform and a company may set, declared once (ADR-078).

A module declares its company settings in `AppConfig.ready()`: one
`SettingGroup` (a form, a version token, a pair of assistant commands, one
owner of the write) and its `SettingSpec`s. A declaration that breaks the
contract stops the process at start, like a command's (ADR-076 §4).

The code default is today's behaviour; above it the platform's value — until
the platform settings exist, the Django setting named in `platform_env`, read
from `.env` — and above that the company's own choice, stored in
`organization_setting`. `settings_service.resolve()` says which one applies and
why.

A group either lives in core's `organization_setting` (company scope; core
serves its API and commands) or — with `api` — in its module's own table: an
"entity" group (ADR-078 pkt 7). Its module keeps the table, the endpoints, the
receipts, the preview and the commands; the registry declares and checks its
keys, lists them in the schema with `api`, and resolves a company-level one
through `read_explicit`. Values of a narrower scope (an offer, a person) are
read by their module.
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
from .options import SETTING_STRATEGIES, SETTING_TYPES, SETTING_UNITS

#: Where a value comes from, most general first (ADR-078 pkt 3): the code, the
#: platform, the product's starting value (`settingsDefaults`), the company.
SOURCES = ("code", "platform", "product", "organization")
SCOPES = ("platform", "organization", "location", "offer", "staff")
STRATEGIES = SETTING_STRATEGIES
DATA_CLASSES = frozenset({"public", "public_personal", "personal"})

#: `organization` (core's own basic settings) or `<namespace>.<group>`.
_GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?$")
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
    #: When this one matters: `<field>` (a bool of the group that is on) or
    #: `<field> == '<value>'` — e.g. `time_model == 'range'`.
    depends_on: str | None = None
    #: The Django setting (named like its `.env` variable) that holds the
    #: platform's value until the platform settings have a table (UF-T16).
    platform_env: str | None = None
    data_class: str = "public"
    scopes: tuple[str, ...] = ("platform", "organization")
    #: `restrict`: the value in force is the strictest of this one and the
    #: module's ceilings (operator, deployment), which only the module knows —
    #: so `resolve()` is the company's choice, not necessarily what applies.
    strategy: str = "override"
    #: False: no product may set a starting value (`settingsDefaults`) — e.g. a
    #: switch whose turning on is one person's consent (ADR-069 pkt 14).
    product_default: bool = True

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
    #: Only the company's owner changes it (the permission alone is not enough).
    owner_only: bool = False
    #: A change asks for a fresh code from the authenticator app first
    #: (ADR-076, 30a/31b); the reason names it in the security log.
    step_up_reason: str = ""
    #: An entity group: the module's endpoint that reads and changes it.
    api: str | None = None
    #: An entity group at company scope: the company's own values by field in
    #: the current tenant, None where it has none (`resolve()` reads it).
    read_explicit: Callable[[], Mapping[str, Any]] | None = None
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


def product_value(spec: SettingSpec) -> Any:
    """The product's starting value (`settingsDefaults` of the profile), or None."""
    return getattr(settings, "SETTINGS_DEFAULTS", {}).get(spec.key)


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
        "strategy": spec.strategy,
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
    if group.api is None and group.read_explicit is not None:
        problems.append("read_explicit ma tylko grupa encji (z api)")
    if group.api is not None and group.commands is not None:
        problems.append("polecenia grupy encji pisze jej moduł")
    if group.step_up_reason and group.commands is not None:
        problems.append("grupa ze step-upem nie ma jeszcze poleceń asystenta")
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
    if not spec.scopes or set(spec.scopes) - set(SCOPES):
        problems.append(f"zasięgi spoza {list(SCOPES)}")
    elif group.api is None and "organization" not in spec.scopes:
        problems.append("grupa rdzenia ma zasięg firmy")
    elif set(spec.scopes) - {"platform", "organization"} and group.read_explicit is not None:
        problems.append("read_explicit czyta tylko wartości firmy")
    if spec.type == "enum" and (
        not spec.values or not all(_localized(labels) for _, labels in spec.values)
    ):
        problems.append("enum wymaga wartości z etykietami pl i en")
    if spec.default is not None:
        checked = check_value(spec, spec.default)
        if checked is None or checked[1]:
            problems.append("wartość domyślna poza typem albo granicami")
    if spec.depends_on is not None and not _depends_on_ok(group, spec.depends_on):
        problems.append("depends_on: pole bool tej grupy albo <pole> == '<wartość>'")
    if spec.strategy not in STRATEGIES or (
        spec.strategy == "restrict" and spec.type not in {"enum", "int"}
    ):
        problems.append("strategia override albo restrict (restrict dla enum i int)")
    product = product_value(spec)
    if product is not None:
        if not spec.product_default or "organization" not in spec.scopes:
            problems.append("settingsDefaults profilu nie może ustawiać tego klucza")
        else:
            checked = check_value(spec, product)
            if checked is None or checked[1]:
                problems.append("settingsDefaults profilu poza typem albo granicami")
    if spec.platform_env is not None:
        if not hasattr(settings, spec.platform_env):
            problems.append(f"brak ustawienia {spec.platform_env}")
        else:
            checked = check_value(spec, getattr(settings, spec.platform_env))
            if checked is None or checked[1]:
                problems.append(f"{spec.platform_env} poza typem albo granicami")
    return problems


_DEPENDS_ON = re.compile(r"^([a-z][a-z0-9_]*)(?: == '([^']*)')?$")


def _depends_on_ok(group: SettingGroup, condition: str) -> bool:
    """`<field>` (a bool that must be on) or `<field> == '<value>'` (an enum's
    value, or a text)."""
    match = _DEPENDS_ON.fullmatch(condition)
    if match is None or match.group(1) not in group.fields:
        return False
    other, value = group.spec(match.group(1)), match.group(2)
    if value is None:
        return other.type == "bool"
    if other.type == "enum":
        return value in {option for option, _ in other.values}
    return other.type == "text"


def _localized(texts: Mapping[str, str] | None) -> bool:
    return (
        texts is not None
        and set(texts) == _LOCALES
        and all(isinstance(text, str) and text.strip() for text in texts.values())
    )


def settings_defaults_problems() -> list[str]:
    """Keys of the profile's `settingsDefaults` that no module declares — only in
    namespaces that already have a registered group: a module still on its own
    constants checks its keys itself until it moves (ADR-078 pkt 14)."""
    spaces = {group.key.split(".")[0] for group in _groups.values()}
    return [
        key
        for key in getattr(settings, "SETTINGS_DEFAULTS", {})
        if key.split(".")[0] in spaces and key not in _keys
    ]
