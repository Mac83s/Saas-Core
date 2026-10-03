"""Three doors past a person's own decision, each counted (ADR-076 §3, §6).

`mint_consent` is a person's click turned into a token; `acting_opened=` lets
one run pass a person-only gate; `acting_context(` makes a membership act for
its person. Each is a plain function or field any module could reach, so
"only the consent endpoint", "only the executor" and "only server rows" hold
because the places are listed here, with a reason, and a new one fails the
test until someone adds it on purpose — the way `test_registry_door` counts
the farm register's door. Calls are counted, not mentions: a definition, an
import or a docstring passes through nothing.

The labels the gates may open are counted too: a typo in the ceiling or in a
command's `person_gates` would keep a gate shut without anyone noticing.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings

from saas_core.modules.core.organizations.command_registry import registered_commands
from saas_core.modules.core.organizations.context import ACTING_PERSON_GATE_ALLOWED

SOURCE = Path(settings.BASE_DIR) / "src" / "saas_core"

#: Where each door may be passed, how many times, and why.
DECLARED: dict[str, dict[str, tuple[int, str]]] = {
    "mint_consent": {
        "modules/core/organizations/views.py::post": (
            1,
            "the panel's consent endpoint, for the person signed in with session and CSRF",
        ),
    },
    "acting_opened=": {
        "modules/core/organizations/context.py::acting_context": (
            1,
            "a context that starts acting for its person starts with no label open",
        ),
        "modules/core/organizations/command_executor.py::_run_write": (
            1,
            "the labels one consented call reported in its preview, for that run only",
        ),
    },
    "acting_context(": {
        "modules/core/organizations/tasks.py::deferred_tenant_context": (
            1,
            "deferred work re-applies the acting its producer stored on the server row",
        ),
        "modules/core/organizations/tasks.py::tenant_task_context": (
            1,
            "a task queued while acting runs acting (contract version 3, ADR-076 §6)",
        ),
        "modules/shared/translation/worker.py::job_context": (
            1,
            "a translation job acts for the person who ordered it or consented, rebuilt from "
            "the job's row and checked at every claim (ADR-069 pkt 13)",
        ),
    },
}


class _Doors(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: dict[str, dict[str, int]] = {door: {} for door in DECLARED}
        self.where = "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        outer, self.where = self.where, node.name
        self.generic_visit(node)
        self.where = outer

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        doors = [f"{name}(" if name == "acting_context" else name]
        doors += [f"{keyword.arg}=" for keyword in node.keywords if keyword.arg]
        for door in doors:
            if door in self.found:
                self.found[door][self.where] = self.found[door].get(self.where, 0) + 1
        self.generic_visit(node)


def _usage() -> dict[str, dict[str, int]]:
    found: dict[str, dict[str, int]] = {door: {} for door in DECLARED}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        visitor = _Doors()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        for door, places in visitor.found.items():
            for where, count in places.items():
                found[door][f"{relative}::{where}"] = count
    return found


def test_only_the_declared_places_pass_the_doors() -> None:
    actual = _usage()
    expected = {
        door: {place: count for place, (count, _why) in places.items()}
        for door, places in DECLARED.items()
    }
    assert actual == expected, (
        "Miejsca, które wybijają zgodę, otwierają bramkę osoby albo każą działać "
        "w imieniu osoby, rozjechały się z deklaracją (ADR-076 §3, §6). Dopisz nowe "
        f"miejsce do DECLARED razem z powodem albo usuń to, którego już nie ma: {actual}"
    )


def test_every_declared_place_says_why() -> None:
    for door, places in DECLARED.items():
        for place, (count, reason) in places.items():
            assert count > 0, f"{door} {place}"
            assert len(reason) > 20, f"{door} {place}: powód jest zbyt ogólny"


def _labels() -> set[str]:
    """Every label a person-only gate can be asked for: a literal argument of
    `assert_person_required`, or one handed to a helper that forwards its
    parameter to it (its default included)."""
    labels: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name) and isinstance(node.value.value, str)
        }
        forwarders: dict[str, int] = {}
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            parameters = [argument.arg for argument in function.args.args]
            defaults = dict(
                zip(
                    parameters[len(parameters) - len(function.args.defaults) :],
                    function.args.defaults, strict=False,
                )
            )
            for call in ast.walk(function):
                if _called(call) != "assert_person_required" or len(call.args) < 2:
                    continue
                label = call.args[1]
                if isinstance(label, ast.Name) and label.id in parameters:
                    forwarders[function.name] = parameters.index(label.id)
                    default = defaults.get(label.id)
                    if isinstance(default, ast.Name) and default.id in constants:
                        labels.add(constants[default.id])
        for call in ast.walk(tree):
            name = _called(call)
            if name == "assert_person_required" and len(call.args) >= 2:
                argument = call.args[1]
            elif name in forwarders and len(call.args) > forwarders[name]:
                argument = call.args[forwarders[name]]
            else:
                continue
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                labels.add(argument.value)
            elif isinstance(argument, ast.Name) and argument.id in constants:
                labels.add(constants[argument.id])
    return labels


def _called(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")


def test_gates_open_only_labels_that_exist() -> None:
    labels = _labels()
    assert {"Strona prawna", "Cennik", "Publikacja wersji językowej"} <= labels
    assert "Odrzucenie wersji językowej" in labels
    for channel, opened in ACTING_PERSON_GATE_ALLOWED.items():
        assert opened <= labels, f"{channel}: {sorted(opened - labels)}"
    for command in registered_commands():
        assert command.person_gates <= labels, (
            f"{command.key}: {sorted(command.person_gates - labels)}"
        )
