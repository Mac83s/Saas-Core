"""The profile's starting values (`settingsDefaults`) are checked at start
(ADR-078 pkt 14): a key no module declares fails the deployment, not a
customer's request. Each declared key's own value is checked by the registry
when its group registers."""

from __future__ import annotations

from typing import Any

from django.core.checks import Error, register

from .settings_registry import area_problems, settings_defaults_problems


@register()
def check_settings_defaults(**_kwargs: Any) -> list[Error]:
    return [
        Error(f"settingsDefaults: no module declares the setting {key!r}.", id="organizations.E101")
        for key in settings_defaults_problems()
    ]


@register()
def check_setting_areas(**_kwargs: Any) -> list[Error]:
    """Every group stands in a declared area (answer 33a): one the panel's
    menu and search know."""
    return [
        Error(f"Settings group in an undeclared area: {problem}.", id="organizations.E102")
        for problem in area_problems()
    ]
