"""Every action the company's history can show has its words in Polish and
English (UX-055, R13): the panel must never fall back to a raw key such as
„booking appointment place changed”.

Two sources: the enum of core's audit actions, and every action a core or
shared module passes straight to an audit call. An action handed over through
a variable (a function's return, a mapping) is not seen here — name it in
`INDIRECT`. A product's own actions are named in the product's messages and
checked there.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from saas_core.modules.core.organizations.models import OrganizationAuditAction

BACKEND = Path(__file__).resolve().parents[1]
MESSAGES = BACKEND.parent / "frontend" / "messages"
MODULES = BACKEND / "src" / "saas_core" / "modules"
ACTION = re.compile(r"^[a-z_]+(\.[a-z_]+){1,3}$")
#: Actions that reach `record_audit` through a variable.
INDIRECT = frozenset({
    "sites.domain.disabled",
    "sites.domain.enabled",
    "sites.domain.released",
    "sites.domain.canonical_changed",
    "sites.domain.verification_requested",
    "translation.settings.processing_acknowledged",
})


def _constant(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def audited_in_code() -> set[str]:
    """Actions passed to a function with „audit” in its name in a module that
    writes the company's history."""
    found: set[str] = set()
    for part in ("core", "shared"):
        for path in sorted((MODULES / part).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "migrations" in path.parts or "record_audit" not in source:
                continue
            tree = ast.parse(source)
            constants = {
                target.id: node.value.value
                for node in tree.body
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", "")
                )
                if "audit" not in name.lower():
                    continue
                values = [*node.args, *(k.value for k in node.keywords if k.arg == "action")]
                for value in values:
                    text = _constant(value, constants)
                    if text and ACTION.match(text):
                        found.add(text)
    return found


def test_every_action_of_the_history_has_words_in_both_languages() -> None:
    actions = {action.value for action in OrganizationAuditAction} | audited_in_code() | INDIRECT
    for locale in ("pl", "en"):
        labels = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))["History"][
            "actions"
        ]
        missing = sorted(action for action in actions if action.replace(".", "_") not in labels)
        assert not missing, f"History.actions ({locale}) nie nazywa: {', '.join(missing)}"
