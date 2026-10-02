"""The profile's starting values (`settingsDefaults`) are checked at start
(ADR-078 pkt 14): a key no module declares fails the deployment, not a
customer's request. Each declared key's own value is checked by the registry
when its group registers."""

from __future__ import annotations

from typing import Any

from django.core.checks import Error, register

from .settings_registry import settings_defaults_problems


@register()
def check_settings_defaults(**_kwargs: Any) -> list[Error]:
    return [
        Error(f"settingsDefaults: no module declares the setting {key!r}.", id="organizations.E101")
        for key in settings_defaults_problems()
    ]
