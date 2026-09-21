"""What a deployment is made of, read from the catalog that describes it.

Until now the profile decided a handful of flags and every image installed
every module anyway, so "two products from one repository" was true on paper
and false at boot: `core-only` shipped Billing's tables, Sites' URLs and
Booking's scheduled tasks. This is the composition the profile was always
meant to drive — the same rules the Node validator applies in CI
(`packages/contracts/scripts/deployment-check.mjs`), applied again where they
decide something: at startup.

Deliberately without Django imports, so settings can call it while the app
registry is still empty, and so the rules can be tested as ordinary functions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: A module may depend on its own layer or one nearer the core, never further
#: out. The same ranking the import contract enforces between packages.
LAYER_RANK = {"core": 0, "shared": 1, "vertical": 2, "config": 3}


class CompositionError(Exception):
    """The profile and the catalog disagree about what this deployment is."""


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    id: str
    layer: str
    depends_on: tuple[str, ...]
    django_app: str | None
    url_prefix: str | None = None
    permissions: tuple[str, ...] = ()
    entitlements: tuple[str, ...] = ()
    #: What a module adds to the system roles and to the kinds of visit a
    #: service can sell. Declared here rather than in core, so a product adds a
    #: module without editing a file it received from Saas-Core (ADR-049).
    role_grants: dict[str, tuple[str, ...]] | None = None
    appointment_kinds: dict[str, str] | None = None
    #: Middleware and scheduled work of a module core does not name, so a
    #: product's vertical mounts them without editing `base.py` (ADR-049).
    middleware: tuple[str, ...] = ()
    beat_schedule: dict[str, dict[str, Any]] | None = None


def load_catalog(directory: Path) -> dict[str, ModuleDescriptor]:
    descriptors: dict[str, ModuleDescriptor] = {}
    for path in sorted(Path(directory).glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        descriptor = ModuleDescriptor(
            id=str(raw["id"]),
            layer=str(raw["layer"]),
            depends_on=tuple(raw.get("dependsOn") or ()),
            django_app=raw["backend"]["djangoApp"],
            url_prefix=raw["backend"].get("urlPrefix"),
            permissions=tuple(raw["backend"].get("permissions") or ()),
            entitlements=tuple(raw["backend"].get("entitlements") or ()),
            role_grants={
                role: tuple(grants)
                for role, grants in (raw["backend"].get("roleGrants") or {}).items()
            },
            appointment_kinds=dict(raw["backend"].get("appointmentKinds") or {}),
            middleware=tuple(raw["backend"].get("middleware") or ()),
            beat_schedule={
                name: dict(entry)
                for name, entry in (raw["backend"].get("beatSchedule") or {}).items()
            },
        )
        if descriptor.id in descriptors:
            raise CompositionError(f"Powielony deskryptor modułu {descriptor.id}")
        descriptors[descriptor.id] = descriptor
    if not descriptors:
        raise CompositionError(f"Katalog modułów jest pusty: {directory}")
    return descriptors


@dataclass(frozen=True, slots=True)
class RoleTemplate:
    """A system role a type declares (ADR-050); `limited` roles may be handed
    out by someone with only limited member management."""

    key: str
    label: dict[str, str]
    permissions: tuple[str, ...]
    limited: bool


@dataclass(frozen=True, slots=True)
class ServiceTemplate:
    """A ready-made bookable service for organizations of one type."""

    key: str
    label: dict[str, str]
    duration_minutes: int
    appointment_kind: str | None


@dataclass(frozen=True, slots=True)
class CatalogCategory:
    """A product-owned public catalogue category for one organization type."""

    key: str
    label: dict[str, str]


@dataclass(frozen=True, slots=True)
class OrganizationType:
    """A kind of organization the product composes (ADR-050).

    `modules` are the shared and vertical modules an organization of this type
    may use; core modules belong to every organization.
    """

    key: str
    label: dict[str, str]
    modules: frozenset[str]
    plan_keys: tuple[str, ...]
    self_signup: bool
    #: Empty: the organization uses core's global system roles.
    roles: tuple[RoleTemplate, ...] = ()
    service_templates: tuple[ServiceTemplate, ...] = ()
    #: None uses the core dictionary; an explicit empty tuple disables categories.
    catalog_categories: tuple[CatalogCategory, ...] | None = None


def organization_types_from(
    artifact: dict[str, Any],
    modules: tuple[str, ...],
) -> tuple[OrganizationType, ...]:
    """The product's organization types as the artifact generator resolved them.

    The generator applies the default once (`business`, everything); reading
    its result keeps backend and frontend on one list. The first type is the
    default for organizations that do not name one.
    """
    raw_types = artifact.get("organizationTypes")
    if not isinstance(raw_types, list) or not raw_types:
        raise CompositionError(
            "Artefakt nie niesie typów organizacji — uruchom deployment:artifact"
        )
    composed = set(modules)
    types: list[OrganizationType] = []
    for raw in raw_types:
        type_modules = frozenset(str(module) for module in raw["modules"])
        foreign = sorted(type_modules - composed)
        if foreign:
            raise CompositionError(
                f"Typ organizacji {raw['key']} używa modułów spoza profilu: {', '.join(foreign)}"
            )
        types.append(
            OrganizationType(
                key=str(raw["key"]),
                label={str(k): str(v) for k, v in raw["label"].items()},
                modules=type_modules,
                plan_keys=tuple(str(plan) for plan in raw.get("planKeys") or ()),
                self_signup=bool(raw["selfSignup"]),
                roles=tuple(
                    RoleTemplate(
                        key=str(role["key"]),
                        label={str(k): str(v) for k, v in role["label"].items()},
                        permissions=tuple(str(p) for p in role["permissions"]),
                        limited=bool(role.get("limited", False)),
                    )
                    for role in raw.get("roles") or ()
                ),
                service_templates=tuple(
                    ServiceTemplate(
                        key=str(template["key"]),
                        label={str(k): str(v) for k, v in template["label"].items()},
                        duration_minutes=int(template["durationMinutes"]),
                        appointment_kind=template.get("appointmentKind"),
                    )
                    for template in raw.get("serviceTemplates") or ()
                ),
                catalog_categories=(
                    tuple(
                        CatalogCategory(
                            key=str(category["key"]),
                            label={str(k): str(v) for k, v in category["label"].items()},
                        )
                        for category in raw["catalogCategories"]
                    )
                    if "catalogCategories" in raw
                    else None
                ),
            )
        )
    return tuple(types)


def product_profile(repository_root: Path) -> str:
    """This repository's main profile, from its `product.json` slot (ADR-049).

    `business` in Saas-Core, the product's own profile in a product repository —
    so tests, static checks and the OpenAPI contract describe the product the
    repository ships without anybody editing a settings file to say which.
    """
    raw: dict[str, Any] = json.loads((repository_root / "product.json").read_text(encoding="utf-8"))
    return str(raw["profiles"][0])


def compose(
    selected: list[str] | tuple[str, ...],
    catalog: dict[str, ModuleDescriptor],
) -> tuple[str, ...]:
    """The profile's modules in an order every dependency precedes its user.

    Dependencies are **not** pulled in silently. A profile that uses Billing
    without naming `core.organizations` is rejected rather than quietly
    extended: the list of modules in a deployment is a decision somebody makes,
    and a composition that grows on its own is one nobody reviewed.
    """
    chosen = list(dict.fromkeys(selected))
    for module_id in chosen:
        if module_id not in catalog:
            raise CompositionError(f"Nieznany moduł {module_id}")

    ordered: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(module_id: str) -> None:
        if module_id in visited:
            return
        if module_id in visiting:
            raise CompositionError(f"Wykryto cykl zależności przy module {module_id}")
        visiting.add(module_id)
        descriptor = catalog[module_id]
        for dependency in descriptor.depends_on:
            if dependency not in catalog:
                raise CompositionError(
                    f"Moduł {module_id} zależy od nieznanego modułu {dependency}"
                )
            if dependency not in chosen:
                raise CompositionError(f"Moduł {module_id} wymaga modułu {dependency}")
            if LAYER_RANK[catalog[dependency].layer] > LAYER_RANK[descriptor.layer]:
                raise CompositionError(
                    f"Niedozwolony kierunek zależności {module_id} -> {dependency}"
                )
            visit(dependency)
        visiting.discard(module_id)
        visited.add(module_id)
        ordered.append(module_id)

    for module_id in chosen:
        visit(module_id)
    return tuple(ordered)


def django_apps_for(
    modules: tuple[str, ...],
    catalog: dict[str, ModuleDescriptor],
) -> tuple[str, ...]:
    apps: list[str] = []
    for module_id in modules:
        django_app = catalog[module_id].django_app
        # A module may be pure contract — a descriptor without backend code —
        # and installing nothing for it is the correct composition.
        if django_app is not None:
            apps.append(django_app)
    return tuple(apps)


def select_by_module(
    entries: dict[str, dict[str, Any]],
    active_modules: tuple[str, ...] | frozenset[str],
    known_modules: frozenset[str] | set[str],
) -> dict[str, Any]:
    """Flattens a per-module mapping down to the modules this deployment has.

    Used for the beat schedule: a task belongs to the module whose code it
    calls, so a deployment without that module must not schedule it. A key that
    names no catalogued module at all is a typo, and a typo here is a job that
    silently never runs — so it raises instead.
    """
    unknown = sorted(set(entries) - set(known_modules))
    if unknown:
        raise CompositionError(f"Wpisy przypisane do nieznanych modułów: {', '.join(unknown)}")
    active = set(active_modules)
    flattened: dict[str, Any] = {}
    for module_id, module_entries in entries.items():
        if module_id in active:
            flattened.update(module_entries)
    return flattened


def role_grants_for(
    modules: tuple[str, ...] | frozenset[str],
    catalog: dict[str, ModuleDescriptor],
) -> dict[str, tuple[str, ...]]:
    """Permissions the composed modules add to each system role."""
    grants: dict[str, list[str]] = {}
    for module_id in modules:
        for role, permissions in (catalog[module_id].role_grants or {}).items():
            grants.setdefault(role, []).extend(permissions)
    return {role: tuple(dict.fromkeys(values)) for role, values in grants.items()}


def appointment_kinds_for(
    modules: tuple[str, ...] | frozenset[str],
    catalog: dict[str, ModuleDescriptor],
) -> dict[str, str]:
    """{key: label} of the visit kinds the composed modules contribute."""
    kinds: dict[str, str] = {}
    for module_id in modules:
        for key, label in (catalog[module_id].appointment_kinds or {}).items():
            if key in kinds:
                raise CompositionError(f"Typ wizyty {key} zgłoszony przez więcej niż jeden moduł")
            kinds[key] = label
    return kinds


def middleware_for(
    modules: tuple[str, ...] | frozenset[str],
    catalog: dict[str, ModuleDescriptor],
) -> tuple[str, ...]:
    """Middleware the composed modules declare, in composition order."""
    return tuple(path for module_id in modules for path in catalog[module_id].middleware)


def beat_schedule_for(
    modules: tuple[str, ...] | frozenset[str],
    catalog: dict[str, ModuleDescriptor],
) -> dict[str, dict[str, Any]]:
    """Scheduled work the composed modules declare, under one name each."""
    schedule: dict[str, dict[str, Any]] = {}
    for module_id in modules:
        for name, entry in (catalog[module_id].beat_schedule or {}).items():
            if name in schedule:
                raise CompositionError(f"Zadanie {name} zgłoszone przez więcej niż jeden moduł")
            schedule[name] = entry
    return schedule


def verify_artifact(
    artifact: dict[str, Any],
    *,
    deployment: str,
    modules: tuple[str, ...],
    catalog: dict[str, ModuleDescriptor],
) -> str:
    """Checks the image's artifact describes the product it actually composed.

    The hash itself is produced once, by the generator, and only carried from
    there — recomputing it in a second language would mean two canonical
    serializations that have to agree forever. What is checked here is the thing
    a wrong hash would stand for: that this image's profile, catalog and
    artifact are three views of one composition. Two images whose hashes differ
    were built from different trees, and that is what the frontend compares.
    """
    stated = str(artifact.get("deployment", ""))
    if stated != deployment:
        raise CompositionError(
            f"Artefakt opisuje deployment {stated!r}, a proces startuje jako {deployment!r}"
        )

    artifact_modules = tuple(str(entry["id"]) for entry in artifact.get("modules", ()))
    if artifact_modules != modules:
        raise CompositionError(
            "Artefakt wymienia inne moduły niż profil: "
            f"{', '.join(artifact_modules)} vs {', '.join(modules)}"
        )

    artifact_apps = tuple(
        app
        for app in (entry["backend"].get("djangoApp") for entry in artifact.get("modules", ()))
        if app is not None
    )
    if artifact_apps != django_apps_for(modules, catalog):
        raise CompositionError("Artefakt wskazuje inne aplikacje Django niż katalog modułów")

    profile_hash = str(artifact.get("profileHash", ""))
    if not profile_hash.startswith("sha256:"):
        raise CompositionError("Artefakt nie niesie profileHash")
    return profile_hash
