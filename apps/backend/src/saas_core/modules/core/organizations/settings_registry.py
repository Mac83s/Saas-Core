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
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import date
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .command_registry import RISKS, Effect, UnknownCommand, organization_modules
from .options import SETTING_INHERITANCE, SETTING_STRATEGIES, SETTING_TYPES, SETTING_UNITS

#: Where a value comes from, most general first (ADR-078 pkt 3): the code, the
#: platform, the product's starting value (`settingsDefaults`), the company.
SOURCES = ("code", "platform", "product", "organization")
SCOPES = ("platform", "organization", "location", "offer", "staff")
STRATEGIES = SETTING_STRATEGIES
DATA_CLASSES = frozenset({"public", "public_personal", "personal"})

#: `organization` (core's own basic settings) or `<namespace>.<group>`.
_GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?$")
#: An address of a page or a mailbox: a scheme, `www.`, or a dot followed by a
#: lowercase domain ending (`firma.pl`, `kontakt@firma.pl`).
_LINK = re.compile(r"(?i:https?://|www\.)|[\w-]{2,}\.[a-z]{2,}\b")
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
    #: A `text` that goes out to customers in the company's name: no link and
    #: no address in it (a link from a company in a platform's mail is the
    #: shape of phishing; answer 36a).
    no_links: bool = False
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
    #: Who may change the platform's value (S-T7): 1 — any operator; 2 — a
    #: platform administrator, for whatever changes what a company pays or gets,
    #: or has a legal effect. The stricter one unless the module says otherwise.
    operator_level: int = 2
    #: `copy_at_creation`: the product's value becomes a new company's own when
    #: it is created, and is never read live — a company older than the value
    #: keeps what it had (e.g. a 2FA requirement that would lock out people
    #: mid-work, 35a). `live`: read while the company has none of its own.
    inheritance: str = "live"

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
    #: What the module refuses that the declaration cannot state — a change
    #: that would lock out the person making it: `check(before, after)` →
    #: {field: (message, code)}; no writes, run by the preview and the save.
    check: (
        Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, tuple[str, str]]] | None
    ) = None
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
_areas: dict[str, SettingArea] = {}
_AREA_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True, slots=True)
class SettingArea:
    """A place in the panel's one „Ustawienia” (owner answer 33a): an entry
    in its menu holding one or more groups. `page`: the module's own page,
    when the area holds more than the registry draws (a form of an entity, a
    list); None: the panel's generic page `/panel/settings/<key>` draws it."""

    key: str
    title: Mapping[str, str]
    description: Mapping[str, str]
    #: Where it stands among the areas, lowest first.
    order: int
    page: str | None = None


def register_setting_area(area: SettingArea) -> None:
    """Declares an area from the owner module's `AppConfig.ready`; a broken
    one stops the start."""
    problems = []
    if not _AREA_PATTERN.fullmatch(area.key):
        problems.append("klucz obszaru to małe litery, cyfry i myślniki (adres strony)")
    if not (_localized(area.title) and _localized(area.description)):
        problems.append("tytuł i opis obszaru wymagają tekstu pl i en")
    if area.page is not None and not area.page.startswith("/panel/"):
        problems.append("strona obszaru to adres panelu")
    if area.key in _areas and _areas[area.key] != area:
        problems.append("obszar już zadeklarowany inaczej")
    if problems:
        raise ImproperlyConfigured(f"Obszar ustawień {area.key}: " + "; ".join(problems))
    _areas[area.key] = area


def registered_areas() -> tuple[SettingArea, ...]:
    return tuple(sorted(_areas.values(), key=lambda area: (area.order, area.key)))


def area_problems() -> list[str]:
    """Groups standing in an area nobody declared — checked once every module
    has registered (`organizations.E102`)."""
    return sorted(
        f"{group.key}: {group.area or '(brak)'}"
        for group in _groups.values()
        if group.area not in _areas
    )


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


def live_product_value(spec: SettingSpec) -> Any:
    """The product's value as `resolve()` reads it: None for a key copied at
    a company's creation instead."""
    return product_value(spec) if spec.inheritance == "live" else None


def platform_value(spec: SettingSpec) -> Any:
    """The platform's value, or None when the platform has not set one: what
    an operator set (S-T1), else the deployment's `.env` (`platform_env`)."""
    if "platform" not in spec.scopes:
        return None
    from .platform_settings import platform_overrides  # noqa: PLC0415

    chosen = platform_overrides().get(spec.key)
    if chosen is not None:
        return chosen
    if spec.platform_env is None:
        return None
    return getattr(settings, spec.platform_env, None)


def platform_group(group: SettingGroup) -> bool:
    """A group only the platform sets: every key of it platform-only. It is
    not a company's — not in its schema, not its to change."""
    return all(spec.scopes == ("platform",) for spec in group.settings)


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
        if spec.no_links and _LINK.search(text):
            return None, "Bez linków i adresów stron ani e-maili.", "links"
        return text, "", ""
    return None, "Nieznany typ ustawienia.", "invalid"


def schema_entry(spec: SettingSpec, organization_type: str = "") -> dict[str, Any]:
    """The setting as `GET …/settings/schema/` and the options endpoints show it,
    in the words of the organization's type when its product gave some.

    The registry's own entry, not the caller's: options endpoints pass their
    module's constants, and a product's words live in the registry."""
    spec = _keys.get(spec.key, spec)
    help_text = typed_text(f"setting:{spec.key}.help", spec.help, organization_type)
    return {
        "key": spec.key,
        "type": spec.type,
        "minimum": spec.minimum,
        "maximum": spec.maximum,
        "unit": spec.unit,
        "values": (
            [
                {
                    "value": value,
                    "label": dict(
                        typed_text(f"setting:{spec.key}.value:{value}", labels, organization_type)
                        or labels
                    ),
                }
                for value, labels in spec.values
            ]
            if spec.type == "enum"
            else None
        ),
        "default": spec.default,
        "label": dict(
            typed_text(f"setting:{spec.key}.label", spec.label, organization_type) or spec.label
        ),
        "help": dict(help_text) if help_text else None,
        "description": spec.model_description,
        "scopes": list(spec.scopes),
        "strategy": spec.strategy,
        "max_length": spec.max_length,
        "depends_on": f"{spec.group}.{spec.depends_on}" if spec.depends_on else None,
    }


#: As each module registered them, before a product's words.
_base_groups: dict[str, SettingGroup] = {}
_base_areas: dict[str, SettingArea] = {}
#: Words for one organization type, laid over what its organizations read.
_type_words: dict[str, dict[str, Mapping[str, str]]] = {}
_TEXT_FIELDS = {"area": ("title", "description"), "group": ("title", "description")}


def relabel_settings(
    words: Mapping[str, Mapping[str, str]], *, organization_type: str | None = None
) -> None:
    """A product's words for registry texts a company reads in its panel and the
    assistant reads in its commands — a practice's „E-maile do pacjentów” where
    core says „E-maile do klientów” (UX-082). Called from the product's
    vertical `AppConfig.ready`, after every module registered its groups.

    Addresses: `area:<key>.title|description`, `group:<key>.title|description`,
    `setting:<key>.label|help`, `setting:<key>.value:<value>`; each text in pl
    and en. Only words: keys, types, values and everything else stay. An
    address nobody registered stops the start, like a broken declaration.

    Without `organization_type` the registry itself takes the words, so the
    schema, the options, the commands and the deployment's manifest all say
    them (`unrelabeled_group` keeps core's for the core manifest). With one,
    only that type's organizations read them, through the schema API.
    """
    problems = [
        f"{address}: {problem}"
        for address, texts in words.items()
        for problem in _relabel_problems(address, texts)
    ]
    if problems:
        raise ImproperlyConfigured("Słowa produktu w ustawieniach: " + "; ".join(problems))
    if organization_type is not None:
        _type_words.setdefault(organization_type, {}).update({
            address: dict(texts) for address, texts in words.items()
        })
        return
    changed: set[str] = set()
    for address, texts in words.items():
        kind, key, attribute, value = _address(address)
        text = dict(texts)
        if kind == "area":
            area = _areas[key]
            _base_areas.setdefault(key, area)
            _areas[key] = (
                replace(area, title=text)
                if attribute == "title"
                else replace(area, description=text)
            )
        elif kind == "group":
            group = _groups[key]
            _replace_group(
                replace(group, title=text)
                if attribute == "title"
                else replace(group, description=text)
            )
            changed.add(key)
        else:
            _replace_spec(_keys[key], attribute, value, text)
            changed.add(_keys[key].group)
    _retitle_commands(changed)


def unrelabeled_group(key: str) -> SettingGroup:
    """The group as its module registered it: core's words, for core's manifest."""
    return _base_groups.get(key, _groups[key])


def relabeled_group_keys() -> frozenset[str]:
    """The groups whose words the product changed for every organization."""
    return frozenset(key for key, base in _base_groups.items() if _groups[key] != base)


def words_type(organization_id: Any) -> str:
    """The organization's type when some type has words of its own; "" — and no
    query — when none has."""
    if not _type_words:
        return ""
    from .models import Organization  # noqa: PLC0415

    return (
        Organization.objects.filter(pk=organization_id)
        .values_list("organization_type", flat=True)
        .first()
        or ""
    )


def typed_text(
    address: str, texts: Mapping[str, str] | None, organization_type: str = ""
) -> Mapping[str, str] | None:
    """`texts`, or the organization type's words for that address."""
    return _type_words.get(organization_type, {}).get(address, texts)


def _replace_group(changed: SettingGroup) -> None:
    _base_groups.setdefault(changed.key, _groups[changed.key])
    _groups[changed.key] = changed
    for spec in changed.settings:
        _keys[spec.key] = spec


def _replace_spec(spec: SettingSpec, attribute: str, value: str, text: dict[str, str]) -> None:
    if attribute == "value":
        relabelled = replace(
            spec,
            values=tuple((one, text if one == value else labels) for one, labels in spec.values),
        )
    elif attribute == "label":
        relabelled = replace(spec, label=text)
    else:
        relabelled = replace(spec, help=text)
    group = _groups[spec.group]
    _replace_group(
        replace(
            group,
            settings=tuple(
                relabelled if one.key == relabelled.key else one for one in group.settings
            ),
        )
    )


def _retitle_commands(group_keys: set[str]) -> None:
    """A group's commands quote its title and description: they take the new
    words too, and only the words (`retitle_command`)."""
    from .command_registry import command, retitle_command  # noqa: PLC0415
    from .settings_commands import group_commands  # noqa: PLC0415

    for key in sorted(group_keys):
        group = _groups[key]
        if group.commands is None:
            continue
        for spec in group_commands(group):
            try:
                command(spec.key)
            except UnknownCommand:
                continue  # Declared but served by its module's own commands.
            retitle_command(
                spec.key,
                title=spec.title,
                summary=spec.summary,
                model_description=spec.model_description,
            )


def _address(address: str) -> tuple[str, str, str, str]:
    """`kind:key.attribute` → (kind, key, attribute, value)."""
    kind, _, rest = address.partition(":")
    if kind == "setting" and ".value:" in rest:
        key, _, value = rest.rpartition(".value:")
        return kind, key, "value", value
    key, _, attribute = rest.rpartition(".")
    return kind, key, attribute, ""


def _relabel_problems(address: str, texts: Mapping[str, str]) -> list[str]:
    kind, key, attribute, value = _address(address)
    problems = [] if _localized(texts) else ["tekst wymaga pl i en"]
    if kind in _TEXT_FIELDS:
        registry: Mapping[str, Any] = _areas if kind == "area" else _groups
        if key not in registry or attribute not in _TEXT_FIELDS[kind]:
            problems.append("nie ma takiego tekstu w rejestrze")
    elif kind == "setting":
        spec = _keys.get(key)
        if spec is None or attribute not in ("label", "help", "value"):
            problems.append("nie ma takiego tekstu w rejestrze")
        elif attribute == "value" and value not in {one for one, _ in spec.values}:
            problems.append("nie ma takiej wartości")
    else:
        problems.append("adres to area:, group: albo setting:")
    return problems


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
    if group.api is not None and any(
        spec.inheritance == "copy_at_creation" for spec in group.settings
    ):
        problems.append("grupa encji kopiuje wartości przy tworzeniu sama")
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
    elif group.api is None and "organization" not in spec.scopes and not platform_group(group):
        problems.append("grupa rdzenia ma zasięg firmy — albo wszystkie klucze tylko platformy")
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
    if spec.operator_level not in (1, 2):
        problems.append("poziom operatora 1 albo 2")
    if spec.no_links and spec.type != "text":
        problems.append("no_links tylko dla typu text")
    if spec.inheritance not in SETTING_INHERITANCE or (
        spec.inheritance == "copy_at_creation" and "organization" not in spec.scopes
    ):
        problems.append("dziedziczenie live albo copy_at_creation (to drugie z zasięgiem firmy)")
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
