"""The platform's values of the settings registry, until the „Platforma"
panel (platform settings plan, phase 1): read, change, give back, history.

    manage.py platform_setting list
    manage.py platform_setting get <key>
    manage.py platform_setting set <key> <value> --operator <email> --reason "…"
    manage.py platform_setting reset <key> --operator <email> --reason "…"
    manage.py platform_setting history <key>

A value is JSON (`48`, `true`, `"text"`) or, when it is not, the text as typed.
A key changes only by an operator of its level (`operator_level`).
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.operators import operator_for_command, reason_of
from saas_core.modules.core.organizations.platform_settings import (
    change_platform_setting,
    platform_history,
    read_platform_setting,
)
from saas_core.modules.core.organizations.settings_registry import registered_groups


class Command(BaseCommand):
    help = "Ustawienia platformy: list, get, set, reset, history."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["list", "get", "set", "reset", "history"])
        parser.add_argument("key", nargs="?")
        parser.add_argument("value", nargs="?")
        parser.add_argument("--operator", help="Kto zmienia (is_staff i MFA).")
        parser.add_argument("--reason", help="Dlaczego; trafia do historii.")

    def handle(self, *args: Any, **options: Any) -> None:
        action, key = options["action"], options["key"]
        if action == "list":
            for group in registered_groups():
                for spec in group.settings:
                    if "platform" in spec.scopes:
                        self._show(spec.key)
            return
        if not key:
            raise CommandError("Podaj klucz ustawienia.")
        try:
            if action == "get":
                self._show(key)
            elif action == "history":
                for entry in platform_history(key):
                    self.stdout.write(
                        f"{entry.created_at:%Y-%m-%d %H:%M}\t{json.dumps(entry.value)}\t"
                        f"{entry.operator.email}\t{entry.reason}"
                    )
            else:
                if action == "set" and options["value"] is None:
                    raise CommandError("Podaj wartość.")
                read_platform_setting(key)  # an unknown key before anything else
                operator = operator_for_command(options["operator"])
                value = _parsed(options["value"]) if action == "set" else None
                change_platform_setting(
                    key, value, operator=operator, reason=reason_of(options["reason"])
                )
                self._show(key)
        except ValidationError as error:
            raise CommandError(json.dumps(error.detail, ensure_ascii=False)) from error

    def _show(self, key: str) -> None:
        current = read_platform_setting(key)
        self.stdout.write(
            f"{key}\t{json.dumps(current.value, ensure_ascii=False)}\t"
            f"{current.source}\tpoziom {current.operator_level}"
        )


def _parsed(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
