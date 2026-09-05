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


def load_catalog(directory: Path) -> dict[str, ModuleDescriptor]:
    descriptors: dict[str, ModuleDescriptor] = {}
    for path in sorted(Path(directory).glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        descriptor = ModuleDescriptor(
            id=str(raw["id"]),
            layer=str(raw["layer"]),
            depends_on=tuple(raw.get("dependsOn") or ()),
            django_app=raw["backend"]["djangoApp"],
        )
        if descriptor.id in descriptors:
            raise CompositionError(f"Powielony deskryptor modułu {descriptor.id}")
        descriptors[descriptor.id] = descriptor
    if not descriptors:
        raise CompositionError(f"Katalog modułów jest pusty: {directory}")
    return descriptors


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
