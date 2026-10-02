"""The profile's starting values for translation settings are checked at start
(ADR-078 pkt 14): a bad value fails the deployment, not a customer's job."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, register

from .settings_spec import AUTO_CHANGES, DECLARATIONS, SettingDeclaration

PREFIX = "translation."


def _problem(declaration: SettingDeclaration, value: Any) -> str | None:
    if declaration.scope != "organization":
        return "a platform value is not a product's starting value"
    if declaration.kind == "enum" and value not in declaration.variants:
        return f"one of {', '.join(declaration.variants)}"
    if declaration.kind == "bool" and not isinstance(value, bool):
        return "true or false"
    if declaration.kind == "int" and (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not (declaration.minimum or 0) <= value <= (declaration.maximum or 0)
    ):
        return f"a number from {declaration.minimum} to {declaration.maximum}"
    return None


@register()
def check_translation_settings_defaults(**_kwargs: Any) -> list[Error]:
    errors: list[Error] = []
    for key, value in settings.SETTINGS_DEFAULTS.items():
        if not key.startswith(PREFIX):
            continue
        declaration = DECLARATIONS.get(key)
        if key == AUTO_CHANGES.key:
            # Turning the automation on is one person's consent, stored with
            # who gave it (ADR-069 pkt 14): a product cannot give it for them.
            errors.append(
                Error(
                    f"settingsDefaults[{key!r}]: the automation is a person's consent, "
                    "never a product's starting value.",
                    id="translation.E003",
                )
            )
            continue
        if declaration is None:
            errors.append(
                Error(
                    f"settingsDefaults: unknown translation setting {key!r}.", id="translation.E001"
                )
            )
            continue
        problem = _problem(declaration, value)
        if problem:
            errors.append(
                Error(f"settingsDefaults[{key!r}] must be {problem}.", id="translation.E002")
            )
    return errors
