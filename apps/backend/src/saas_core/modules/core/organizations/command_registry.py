"""Commands: what the assistant, and later MCP, may do — declared once
(ADR-076 §1, §4).

A command is a versioned, thin adapter over the same service the panel's view
calls; audit, outbox and the transaction stay in that service. Modules register
their commands in `AppConfig.ready()`, and a declaration that breaks the
contract stops the process at start rather than the first conversation that
reaches it.

The registry knows no models, providers or conversations: the model port gets
its tools from `command_tools`, and the executor runs what a person consented
to. The filter in `command_tools` only decides what a model is offered — the
executor checks permission, exposure and module again on every call.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .context import TenantContext
from .models import Organization

#: Ordered from least to most consequential: an escalation found by the
#: preview may only move a command to the right (ADR-076 §2).
RISKS = ("read", "draft", "apply", "publish", "irreversible")
MODIFIERS = frozenset({"spends_credits", "bulk", "legal_document", "changes_billing"})
#: The model port's data classes (ADR-068): what an output field may be shown
#: to a model as. `health` never is, so no command may return it.
DATA_CLASSES = frozenset({"public", "public_personal", "personal", "health"})
EXPOSURES = frozenset({"assistant", "mcp"})
#: Features a command may require on top of its channel's own (ADR-076 §1, §8);
#: the channel's features are the executor's to ask for.
EXTRA_FEATURES = frozenset({"assistant.site_generation.enabled"})

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_UNDO_PATTERN = re.compile(
    r"^(?:restore_version|discard_run"
    r"|command:[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+@[1-9][0-9]*"
    r"|compensation:\S.*|none:\S.*)$"
)
_LOCALES = frozenset({"pl", "en"})
_SUBSCHEMA_LISTS = ("anyOf", "oneOf", "allOf")


class UnknownCommand(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Effect:
    """One change a command would make, typed so the consent screen shows it
    from the server's preview, never from the model's description of it."""

    kind: str
    resource: str
    resource_id: str
    summary: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Preview:
    effects: tuple[Effect, ...]
    #: `<resource>:<id>` → the version the preview read; the consent binds them.
    observed_versions: Mapping[str, int | str]
    quote: Mapping[str, Any] | None = None
    escalate_to: str | None = None
    person_gates: frozenset[str] = frozenset()
    step_up_required: bool = False


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    version: int
    #: The module that owns the service; the command exists only where the
    #: profile composes it and the organization's type reaches it.
    module: str
    title: Mapping[str, str]
    summary: Mapping[str, str]
    #: English, for the model: what it does, when to use it, when not to.
    model_description: str
    #: JSON Schema 2020-12 in the tool-calling strict subset, without the
    #: tenant and the idempotency key.
    input_schema: Mapping[str, Any]
    #: Every field carries `x-data-class`; text from outside sources `x-untrusted`.
    output_schema: Mapping[str, Any]
    permission: str
    risk: str
    run: Callable[..., Any]
    #: `command:<name@v>`, `restore_version`, `discard_run`, `compensation:<how>`
    #: or `none:<why>`.
    undo: str
    entitlement: str | None = None
    extra_features: frozenset[str] = frozenset()
    modifiers: frozenset[str] = frozenset()
    #: A pure function — no writes, no outside calls, no credit holds — or the
    #: reason there is none.
    preview: Callable[..., Preview] | None = None
    no_preview_reason: str = ""
    version_field: str | None = None
    no_version_reason: str = ""
    person_gates: frozenset[str] = frozenset()
    exposure: frozenset[str] = frozenset({"assistant"})
    #: Why the output may carry `personal` fields; without it they are refused
    #: here, and with it every read of them is audited.
    personal_purpose: str = ""

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def tool_name(self) -> str:
        """`booking.offer.create@1` → `booking_offer_create_v1` (ADR-076 §4)."""
        return f"{self.name.replace('.', '_')}_v{self.version}"


_commands: dict[str, CommandSpec] = {}
_tools: dict[str, str] = {}


def register_command(spec: CommandSpec) -> None:
    problems = _declaration_problems(spec)
    if problems:
        raise ImproperlyConfigured(f"Polecenie {spec.key}: " + "; ".join(problems))
    existing = _commands.get(spec.key)
    if existing is not None:
        if existing == spec:
            return
        raise ImproperlyConfigured(f"Polecenie {spec.key} jest już zarejestrowane inaczej.")
    owner = _tools.get(spec.tool_name)
    if owner is not None:
        raise ImproperlyConfigured(
            f"Polecenie {spec.key}: nazwa narzędzia {spec.tool_name} należy już do {owner}."
        )
    _commands[spec.key] = spec
    _tools[spec.tool_name] = spec.key


def registered_commands() -> tuple[CommandSpec, ...]:
    return tuple(_commands[key] for key in sorted(_commands))


def command(key: str) -> CommandSpec:
    try:
        return _commands[key]
    except KeyError:
        raise UnknownCommand(key) from None


def command_for_tool(tool_name: str) -> CommandSpec:
    """The command behind a tool name a model called; the port does not
    translate names back."""
    key = _tools.get(tool_name)
    if key is None:
        raise UnknownCommand(tool_name)
    return _commands[key]


def command_tools(context: TenantContext, *, exposure: str = "assistant") -> list[dict[str, Any]]:
    """What a model may be offered for this membership, as the port's
    `ToolSpec` fields (`docs/architecture/model-port.md`)."""
    reachable = organization_modules(context.organization_id)
    return [
        {
            "name": spec.tool_name,
            "description": spec.model_description,
            "input_schema": spec.input_schema,
        }
        for spec in registered_commands()
        if exposure in spec.exposure
        and context.has_permission(spec.permission)
        and spec.module in reachable
    ]


def organization_modules(organization_id: UUID) -> frozenset[str]:
    """Core modules, and the rest as the organization's type composes them.

    The same answer `ModuleGateMiddleware` gives the API by URL prefix; a
    command calls its service directly, past that middleware (ADR-050).
    """
    organization_type = (
        Organization.objects.filter(pk=organization_id)
        .values_list("organization_type", flat=True)
        .first()
    )
    known = settings.ORGANIZATION_TYPES.get(organization_type or "")
    core = frozenset(
        module
        for module in settings.ACTIVE_MODULES
        if settings.MODULE_CATALOG[module].layer == "core"
    )
    return core | (known.modules if known is not None else frozenset())


def _declaration_problems(spec: CommandSpec) -> list[str]:
    problems: list[str] = []
    if not _NAME_PATTERN.fullmatch(spec.name):
        problems.append("nazwa musi mieć postać moduł.zasób.czynność")
    if isinstance(spec.version, bool) or not isinstance(spec.version, int) or spec.version < 1:
        problems.append("wersja to liczba całkowita od 1")
    elif not _TOOL_NAME_PATTERN.fullmatch(spec.tool_name):
        problems.append(f"nazwa narzędzia {spec.tool_name} przekracza 64 znaki")
    problems += _composition_problems(spec)
    for label, texts in (("title", spec.title), ("summary", spec.summary)):
        if set(texts) != _LOCALES or not all(_text(value) for value in texts.values()):
            problems.append(f"{label} wymaga niepustego tekstu pl i en")
    if not _text(spec.model_description):
        problems.append("model_description jest wymagany")
    if spec.risk not in RISKS:
        problems.append(f"nieznana klasa ryzyka {spec.risk!r}")
    if unknown := spec.modifiers - MODIFIERS:
        problems.append(f"nieznane modyfikatory {sorted(unknown)}")
    if spec.risk == "read" and (spec.modifiers or spec.person_gates):
        problems.append("odczyt nie ma modyfikatorów ani bramek osoby")
    if (spec.preview is None) == (not _text(spec.no_preview_reason)):
        problems.append("podgląd albo powód jego braku — dokładnie jedno")
    if (spec.version_field is None) == (not _text(spec.no_version_reason)):
        problems.append("pole wersji albo powód jego braku — dokładnie jedno")
    if not _UNDO_PATTERN.fullmatch(spec.undo):
        problems.append(
            "undo: command:<nazwa@v>, restore_version, discard_run, compensation:… albo none:…"
        )
    if not spec.exposure or spec.exposure - EXPOSURES:
        problems.append(f"ekspozycja to niepusty podzbiór {sorted(EXPOSURES)}")
    if not all(_text(label) for label in spec.person_gates):
        problems.append("etykieta bramki osoby nie może być pusta")
    problems += _input_schema_problems(spec.input_schema)
    problems += _output_schema_problems(spec)
    return problems


def _composition_problems(spec: CommandSpec) -> list[str]:
    if spec.module not in settings.ACTIVE_MODULES:
        return [f"moduł {spec.module} nie jest złożony w tym profilu"]
    descriptors = [settings.MODULE_CATALOG[module] for module in settings.ACTIVE_MODULES]
    problems: list[str] = []
    if not any(spec.permission in descriptor.permissions for descriptor in descriptors):
        problems.append(f"uprawnienia {spec.permission} nie deklaruje żaden moduł")
    if spec.entitlement is not None and not any(
        spec.entitlement in descriptor.entitlements for descriptor in descriptors
    ):
        problems.append(f"entitlementu {spec.entitlement} nie deklaruje żaden moduł")
    if unknown := spec.extra_features - EXTRA_FEATURES:
        problems.append(f"nieznane cechy {sorted(unknown)}")
    return problems


def _input_schema_problems(schema: Mapping[str, Any]) -> list[str]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"input_schema nie jest JSON Schema 2020-12: {error.message}"]
    problems: list[str] = []
    if not _is_object(schema):
        problems.append("input_schema: korzeniem jest obiekt")
    _walk_input(schema, "input_schema", problems)
    return problems


def _walk_input(node: Any, path: str, problems: list[str]) -> None:
    """The strict subset (ADR-076 §1): closed objects, every field required and
    described, an optional field as a union with null, no `x-*` words."""
    if not isinstance(node, Mapping):
        return
    problems.extend(
        f"{path}: słowo {word} nie należy do wejścia"
        for word in node
        if isinstance(word, str) and word.startswith("x-")
    )
    properties = node.get("properties") or {}
    if _is_object(node):
        if node.get("additionalProperties") is not False:
            problems.append(f"{path}: obiekt wymaga additionalProperties: false")
        if set(node.get("required") or ()) != set(properties):
            problems.append(f"{path}: required wymienia każde pole (opcjonalne to unia z null)")
    for name, child in properties.items():
        if not (isinstance(child, Mapping) and _text(child.get("description"))):
            problems.append(f"{path}.{name}: pole wymaga description")
        _walk_input(child, f"{path}.{name}", problems)
    for child, child_path in _subschemas(node, path):
        _walk_input(child, child_path, problems)


def _output_schema_problems(spec: CommandSpec) -> list[str]:
    schema = spec.output_schema
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"output_schema nie jest JSON Schema 2020-12: {error.message}"]
    problems: list[str] = []
    if not _is_object(schema):
        problems.append("output_schema: korzeniem jest obiekt")
    classes: set[str] = set()
    _walk_output(schema, "output_schema", None, problems, classes)
    if "health" in classes:
        problems.append("output_schema: dane klasy health nie trafiają do modelu")
    if "personal" in classes and not _text(spec.personal_purpose):
        problems.append("output_schema: pola personal wymagają personal_purpose")
    return problems


def _walk_output(
    node: Any, path: str, inherited: str | None, problems: list[str], classes: set[str]
) -> None:
    if not isinstance(node, Mapping):
        return
    own = node.get("x-data-class")
    if own is not None and own not in DATA_CLASSES:
        problems.append(f"{path}: nieznana klasa danych {own!r}")
    elif own is not None:
        classes.add(own)
    if "x-untrusted" in node and not isinstance(node["x-untrusted"], bool):
        problems.append(f"{path}: x-untrusted to true albo false")
    data_class = own if own in DATA_CLASSES else inherited
    for name, child in (node.get("properties") or {}).items():
        if data_class is None and not (isinstance(child, Mapping) and "x-data-class" in child):
            problems.append(f"{path}.{name}: pole wymaga x-data-class")
        _walk_output(child, f"{path}.{name}", data_class, problems, classes)
    for child, child_path in _subschemas(node, path):
        _walk_output(child, child_path, data_class, problems, classes)


def _subschemas(node: Mapping[str, Any], path: str) -> list[tuple[Any, str]]:
    found: list[tuple[Any, str]] = []
    if isinstance(node.get("items"), Mapping):
        found.append((node["items"], f"{path}[]"))
    for keyword in _SUBSCHEMA_LISTS:
        found.extend(
            (child, f"{path}.{keyword}.{index}")
            for index, child in enumerate(node.get(keyword) or ())
        )
    for name, child in (node.get("$defs") or {}).items():
        found.append((child, f"{path}.$defs.{name}"))
    return found


def _is_object(node: Mapping[str, Any]) -> bool:
    kind = node.get("type")
    return kind == "object" or (isinstance(kind, list) and "object" in kind) or "properties" in node


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
