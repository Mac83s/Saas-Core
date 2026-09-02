"""The module catalog describes code that exists (P1 of the post-audit plan).

Descriptors used to declare Django apps that had never been written, and one
installed app had no descriptor. ``pnpm deployment:check`` validates the
schema and the dependency graph, not existence, so a profile could be "valid"
and still unable to boot from a real composition. This holds both directions:
every declared app imports, every installed module app is declared.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings

MODULES_PATH = Path(settings.SITE_BLOCK_CONTRACTS_PATH).parent / "modules"
MODULE_APP_PREFIX = "saas_core.modules."


def _descriptors() -> dict[str, dict[str, Any]]:
    descriptors = {}
    for path in sorted(MODULES_PATH.glob("*.json")):
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        descriptors[descriptor["id"]] = descriptor
    assert descriptors, f"brak deskryptorów w {MODULES_PATH}"
    return descriptors


def test_every_declared_django_app_is_importable() -> None:
    for module_id, descriptor in _descriptors().items():
        django_app = descriptor["backend"]["djangoApp"]
        if django_app is None:
            continue
        try:
            importlib.import_module(django_app)
        except ModuleNotFoundError as error:
            raise AssertionError(
                f"deskryptor {module_id} deklaruje {django_app}, którego nie ma w kodzie"
            ) from error


def test_every_installed_module_app_has_a_descriptor() -> None:
    declared = {
        descriptor["backend"]["djangoApp"]
        for descriptor in _descriptors().values()
        if descriptor["backend"]["djangoApp"] is not None
    }
    installed = {app for app in settings.INSTALLED_APPS if app.startswith(MODULE_APP_PREFIX)}

    assert sorted(installed - declared) == []


def test_active_profile_names_only_catalogued_modules() -> None:
    profile = json.loads(Path(settings.DEPLOYMENT_PROFILE_PATH).read_text(encoding="utf-8"))

    assert sorted(set(profile["modules"]) - set(_descriptors())) == []
