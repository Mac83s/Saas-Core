"""Drzwi do rejestru rolnika są coś warte tylko wtedy, gdy ktoś je liczy.

`registry_door` przełącza tenanta na organizację rolnika i przez chwilę pisze
w cudzej bazie danych. To ta sama klasa ryzyka co `PRE_TENANT_DB` (ADR-041):
obejście granicy, bez którego produkt nie działa, więc nie da się go zabronić —
da się je policzyć. Drzwiami, a nie dziurą, czyni je to, że lista miejsc ich
użycia jest spisana, a dopisanie się do niej robi człowiek świadomie i ktoś inny
widzi to w przeglądzie (ADR-052, „Konsekwencje").

To jest ten licznik. Pada, gdy pojawi się użycie, którego nikt nie zadeklarował,
i pada, gdy zadeklarowane zniknie — lista nie może zgnić w żadną stronę.

Liczone są wywołania, nie wystąpienia napisu: definicja drzwi, import i wzmianka
w docstringu nie są przejściem przez nie i nie mogą podbijać licznika.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings

SOURCE = Path(settings.BASE_DIR) / "src" / "saas_core"

#: Funkcja, której wywołanie otwiera rejestr rolnika.
DOOR = "registry_door"

#: Gdzie wolno przez nie przejść, ile razy i po co. Liczba nie jest ozdobą:
#: to ona łapie drugie wejście dopisane po cichu do funkcji, która miała już
#: pozwolenie na jedno.
DECLARED_DOOR: dict[str, tuple[int, str]] = {
    "modules/shared/farms/herd_sync.py::mirror_animal": (
        1,
        "zapis jednej sztuki do rejestru rolnika, gdy karta firmy jest połączona "
        "udziałem z can_write_herd (ADR-051 pkt 7)",
    ),
    "modules/shared/farms/herd_sync.py::push_herd": (
        1,
        "całe stado jednym przejściem zamiast jednego na sztukę: trzysta krów to "
        "inaczej trzysta przełączeń tenanta i trzysta wpisów audytu",
    ),
    "modules/shared/farms/herd_sync.py::publish_health_entry": (
        1,
        "wpis zdrowotny do kartoteki zwierzęcia, pod udziałem z can_publish_health "
        "(ADR-051 pkt 8)",
    ),
    "modules/shared/farms/herd_sync.py::registry_health_entries": (
        1,
        "ta sama kartoteka w drugą stronę: firma czyta, co inni zapisali o zwierzęciu "
        "— dlatego jedyne przejście z uprawnieniem tylko do odczytu",
    ),
    "modules/shared/farms/herd_sync.py::publish_farm_visit": (
        1,
        "wizyta gospodarstwa i jej raport, pod osobną zgodą can_publish_schedule, "
        "której can_publish_health nie zastępuje (ADR-052 pkt 4)",
    ),
}


class _DoorCalls(ast.NodeVisitor):
    """Wywołania drzwi w jednym pliku, przypisane do funkcji, która je otwiera."""

    def __init__(self) -> None:
        self.found: dict[str, int] = {}
        self.where = "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        outer, self.where = self.where, node.name
        self.generic_visit(node)
        self.where = outer

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == DOOR:
            self.found[self.where] = self.found.get(self.where, 0) + 1
        self.generic_visit(node)


def _door_usage() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        visitor = _DoorCalls()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        for where, count in visitor.found.items():
            found[f"{relative}::{where}"] = count
    return found


def test_only_the_declared_places_write_in_the_farmers_tenant() -> None:
    actual = _door_usage()
    expected = {place: count for place, (count, _reason) in DECLARED_DOOR.items()}

    assert actual == expected, (
        "Lista miejsc wchodzących do rejestru rolnika rozjechała się z deklaracją "
        "(ADR-052). Dopisz nowe użycie do DECLARED_DOOR razem z powodem albo usuń "
        f"wpis, którego już nie ma: {actual}"
    )


def test_every_declared_place_says_why() -> None:
    for place, (count, reason) in DECLARED_DOOR.items():
        assert count > 0, place
        assert len(reason) > 20, f"{place}: powód jest zbyt ogólny, żeby coś znaczył"
