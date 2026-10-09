"""The door from ADR-041 is only worth having if somebody counts it.

A second database identity that reads past row-level security is a hole by
construction — logging in has to read memberships somehow. What makes it a
door rather than a hole is that the list of places using it is written down,
and that adding a place to the list is something a person does on purpose and
somebody else sees in review.

This is that count. It fails when a call site appears that nobody declared,
and it fails when a declared one disappears, so the list cannot rot in either
direction.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path

from django.conf import settings

from saas_core.modules.core.organizations import api as organizations_api

SOURCE = Path(settings.BASE_DIR) / "src" / "saas_core"

#: Where the door may be used, and how many times, with the reason each one
#: exists. A number here is not decoration: it is what catches a second query
#: quietly added to a module that already had permission for one.
DECLARED_DOOR: dict[str, tuple[int, str]] = {
    "modules/core/identity/sessions.py": (
        1,
        "logowanie: gdy konto należy do dokładnie jednej firmy, wybrać ją bez pytania",
    ),
    "modules/core/organizations/middleware.py": (
        2,
        "logowanie: znaleźć członkostwo, żeby dopiero z niego zbudować kontekst",
    ),
    "modules/core/organizations/erasure.py": (
        2,
        "usunięcie tenanta: sprawdzenie, czy rejestr nadal zna tę organizację, "
        "gdy tenanta już nie ma; oraz trasy osierocone po organizacjach, których "
        "rejestr już nie zna (purge_test_tenants --orphans)",
    ),
    "modules/core/organizations/demo.py": (
        1,
        "seed_demo na stosie testowym: czy organizacja demo o tym slugu już jest, "
        "zanim da się ustawić jej tenanta",
    ),
    "modules/core/organizations/management/commands/erase_organization.py": (
        1,
        "komenda operatorska: odnalezienie organizacji po identyfikatorze, zanim "
        "cokolwiek ustawi tenanta",
    ),
    "modules/core/organizations/services.py": (
        2,
        "przełącznik organizacji: do jakich firm należy to konto i czy może wybrać wskazaną firmę",
    ),
    "modules/core/organizations/platform_settings.py": (
        1,
        "podgląd zmiany wartości platformy: lista firm, w których potem — każda we "
        "własnym tenancie — liczy się, czy mają własną wartość klucza; operator nie ma tenanta",
    ),
    "modules/core/organizations/retention.py": (
        1,
        "usuwanie danych osobowych po czasie (37a): lista firm, z których każda jest potem "
        "czytana we własnym tenancie — jej ustawienie i to, co byłoby do usunięcia",
    ),
    "modules/core/organizations/lifecycle.py": (
        1,
        "zaproszenie odnalezione po tokenie przez kogoś, kto nie jest jeszcze członkiem",
    ),
    "modules/core/organizations/platform_workspace.py": (
        3,
        "workspace platformy: czy ten deployment ma już swojego wydawcę — pytanie "
        "o rejestr, zadawane zanim istnieje organizacja, której mogłoby dotyczyć; "
        "oraz sam identyfikator wydawcy (`platform_workspace_id`: stałe zapytanie, "
        "jedna kolumna) dla odczytów z listy DECLARED_WORKSPACE_LOOKUPS i dla bloku "
        "`in_platform_workspace`, który pyta tą samą linią",
    ),
    "modules/core/organizations/management/commands/purge_test_tenants.py": (
        4,
        "operatorskie usuwanie kont testowych: do jakich firm należy konto, kto "
        "jeszcze w nich jest i ile wierszy zniknie — wszystko ponad tenantami",
    ),
    "modules/shared/billing/tenant_scope.py": (
        2,
        "przemiatania w tle po wszystkich organizacjach oraz rozpoznanie tenanta "
        "po kliencie Stripe",
    ),
    "modules/shared/translation/management/commands/translation_e2e_fixture.py": (
        1,
        "atrapa tłumaczeń testu przeglądarkowego (tylko stack lokalny): odnalezienie "
        "firmy testu po slugu, zanim cokolwiek zna jej tenanta",
    ),
    "modules/shared/sites/management/commands/sites_e2e_fixture.py": (
        3,
        "fixture E2E: czy slug jest wolny w całym rejestrze i czy po sprzątaniu "
        "konto nie należy już do żadnej firmy",
    ),
}

#: The module that defines the alias obviously names it.
DEFINITION = "modules/core/organizations/pre_tenant.py"

#: The setting the constant is read from, and the alias it holds on a running
#: deployment. A query sent through either — `.using("pre_tenant")`,
#: `connections[settings.PRE_TENANT_DATABASE_ALIAS]` — goes through the door
#: exactly as one written with `PRE_TENANT_DB`, and the count above, which
#: looks for the constant's name, would not see it (found in the review of
#: PR1c). So the alias has a list of its own: who names it without the
#: constant, how many times, and why — none of them to read a row.
ALIAS_SETTING = "PRE_TENANT_DATABASE_ALIAS"
DECLARED_ALIAS: dict[str, tuple[int, str]] = {
    DEFINITION: (
        1,
        "definicja stałej `PRE_TENANT_DB`: jedyne miejsce, które czyta alias z ustawień, "
        "żeby dało się go policzyć po nazwie",
    ),
    "config/settings/base.py": (
        3,
        "ustawienia: nazwa aliasu i wpis `DATABASES` z osobną rolą bazy — konfiguracja "
        "połączenia, żadnego zapytania",
    ),
    "config/settings/test.py": (
        1,
        "ustawienia testów: alias wskazuje połączenie domyślne, bo baza testowa i tak "
        "omija RLS — żadnego zapytania",
    ),
    "config/db_router.py": (
        1,
        "router: migracje nie są wykonywane drugi raz na aliasie drzwi — porównanie "
        "nazwy połączenia, żadnego zapytania",
    ),
    **{
        f"modules/core/organizations/migrations/{name}.py": (
            2,
            "migracja polityki RLS: nazwa roli bazy stojącej za aliasem, żeby polityka "
            "mogła ją wymienić — zamrożona historia, czyta ustawienia, nie wiersze",
        )
        for name in (
            "0025_rls_billingprofile_invitation",
            "0026_rls_membership_audit",
            "0027_rls_role",
            "0028_rls_organization",
        )
    },
}

#: The functions that find the platform's workspace through the door. A call
#: to one of them is a read before a tenant is known just as a line with
#: `PRE_TENANT_DB` is — and the count above cannot see it: the line it counts
#: stays where it is, in the module that defines them, however many places
#: start calling it. The one that provisions the workspace is among them: it
#: gives back the row it finds, loaded through the door.
WORKSPACE_LOOKUPS = frozenset({
    "platform_workspace",
    "platform_workspace_id",
    "ensure_platform_workspace",
})
#: The block that runs inside that workspace (ADR-080, „Uzupełnienie PR1c").
#: It asks the lookup itself, so whoever calls it reads before a tenant is
#: known just the same — it is counted with them.
WORKSPACE_BLOCK = "in_platform_workspace"
WORKSPACE_NAMES = WORKSPACE_LOOKUPS | {WORKSPACE_BLOCK}
#: What makes a function that yields a block of its own rather than a
#: generator somebody reads at leisure.
CONTEXT_MANAGERS = frozenset({"contextmanager", "asynccontextmanager"})
WORKSPACE_LOOKUP_DEFINITION = "modules/core/organizations/platform_workspace.py"

#: A product's own modules. Its public pages stand on the platform's host,
#: which is no site's domain, and its operator's commands have no request at
#: all: "the platform's workspace, without a host" is the designed answer
#: there and nowhere else. So the block is theirs to call without a line in
#: this file — a product may not edit a file of the core (ADR-049) — and the
#: lookups are never theirs to name, in a view or in a command.
#:
#: What this does not catch, said plainly:
#: - a file put under `modules/vertical/` in the core's own tree — the core
#:   ships none there, and one that appeared would pass as a product's;
#: - a name put together while the program runs (two strings joined, an
#:   f-string, bytes decoded) or taken out of `sys.modules` — the door's
#:   alias among them: `"pre_" + "tenant"` is no literal `_alias_names` sees,
#:   and neither is an alias read from the environment or from
#:   `connections` by position;
#: - an answer handed on: a module that may ask giving the identifier to one
#:   that may not, under a name of its own — or a module that may hold the
#:   constant handing the alias on under another name.
#: The alias written as a literal, or read from settings, is caught since
#: PR1d (`DECLARED_ALIAS`).
#: A product is held to it by its own gate running this file; a product that
#: does not run the core's tests is held to nothing.
PRODUCT_MODULES = "modules/vertical/"

#: Who of the core may ask, by which name, and why. A module is on this list
#: when it names a lookup or the block at all — imports it, reaches it as an
#: attribute, or spells its name in a string — so a new caller fails the test
#: until somebody writes down here what it does with the answer.
DECLARED_WORKSPACE_LOOKUPS: dict[str, tuple[frozenset[str], str]] = {
    "modules/core/organizations/api.py": (
        frozenset({"in_platform_workspace"}),
        "podaje blok dalej i niczego nie odczytuje: publiczna powierzchnia modułu, "
        "z której bierze go moduł produktu (ADR-080, „Uzupełnienie PR1c”)",
    ),
    "modules/shared/billing/management/commands/provision_platform_workspace.py": (
        frozenset({"ensure_platform_workspace"}),
        "komenda operatora: zakłada workspace platformy tego wdrożenia albo bierze "
        "istniejący, żeby nadać mu funkcje i pierwszego operatora — jedyne miejsce, "
        "które go tworzy; żadnego żądania, żadnej danej od gościa",
    ),
    "modules/shared/model_port/service.py": (
        frozenset({"platform_workspace"}),
        "port modeli: czy żądanie do modelu składa workspace platformy — porównanie "
        "identyfikatora z kontekstem żądania, odczytane raz na proces",
    ),
    "modules/shared/sites/content_reads.py": (
        frozenset({"platform_workspace_id"}),
        "odczyt opublikowanej treści platformy dla stron produktu (ADR-079 pkt 31): "
        "jedyny publiczny odczyt, któremu host nie nazwie tenanta, bo strony produktu "
        "stoją na hoście platformy — stałe zapytanie, wraca jeden identyfikator, "
        "wszystko dalej jest czytane w tym tenancie",
    ),
}


def _door_usage() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        if relative == DEFINITION:
            continue
        uses = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if "PRE_TENANT_DB" in line and not line.lstrip().startswith(("from ", "import ", "#"))
        ]
        if uses:
            found[relative] = len(uses)
    return found


def _alias_names(source: str, alias: str) -> int:
    """How many times a source names the door's alias without the constant:
    the alias itself as a string, or the setting that holds it — as an
    attribute, a bare name or a string handed to `getattr`. A sentence that
    merely mentions either is no such string."""
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if (isinstance(node, ast.Constant) and node.value in (alias, ALIAS_SETTING))
        or (isinstance(node, ast.Attribute) and node.attr == ALIAS_SETTING)
        or (isinstance(node, ast.Name) and node.id == ALIAS_SETTING)
    )


def _alias_usage(root: Path = SOURCE) -> dict[str, int]:
    # The running settings, not the test ones, where the alias is "default".
    alias = import_module("saas_core.config.settings.base").PRE_TENANT_DATABASE_ALIAS
    found: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        uses = _alias_names(path.read_text(encoding="utf-8"), alias)
        if uses:
            found[path.relative_to(root).as_posix()] = uses
    return found


def _workspace_names(source: str) -> set[str]:
    """The workspace lookups and the block a module names, however it gets at
    them.

    - `from … import platform_workspace_id`, from the defining module or from
      one that passes it on;
    - the defining module taken whole (`import ….platform_workspace`,
      `from …organizations import platform_workspace`): everything in it is
      then one attribute away, so that counts as every lookup;
    - an attribute of any of the names on anything
      (`module.platform_workspace()`);
    - a name spelled in a string, which is how `getattr` reaches it.

    A local variable that merely happens to be called `platform_workspace` is
    none of these.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").rsplit(".", 1)[-1]
            for alias in node.names:
                if module == "platform_workspace":
                    if alias.name == "*":
                        found |= WORKSPACE_NAMES
                    elif alias.name in WORKSPACE_NAMES:
                        found.add(alias.name)
                elif alias.name == "platform_workspace":
                    # The defining module itself, imported from its package.
                    found |= WORKSPACE_LOOKUPS
                elif alias.name in WORKSPACE_NAMES:
                    found.add(alias.name)
        elif isinstance(node, ast.Import):
            if any(alias.name.rsplit(".", 1)[-1] == "platform_workspace" for alias in node.names):
                found |= WORKSPACE_LOOKUPS
        elif isinstance(node, ast.Attribute) and node.attr in WORKSPACE_NAMES:
            found.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= {
                name
                for name in WORKSPACE_NAMES
                if node.value == name or node.value.endswith(f".{name}")
            }
    return found


def _workspace_usage(root: Path = SOURCE) -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == WORKSPACE_LOOKUP_DEFINITION:
            continue
        names = _workspace_names(path.read_text(encoding="utf-8"))
        if names:
            found[relative] = frozenset(names)
    return found


def _workspace_problems(
    usage: dict[str, frozenset[str]], declared: dict[str, frozenset[str]]
) -> list[str]:
    """What is wrong with who reaches the platform's workspace, one line per
    module — each line says what its author is to do."""
    problems: list[str] = []
    for path, names in sorted(usage.items()):
        if path.startswith(PRODUCT_MODULES):
            # The block is a product's module's by design; a lookup never is.
            named = sorted(names & WORKSPACE_LOOKUPS)
            if named:
                problems.append(
                    f"{path}: moduł produktu nazywa odnalezienie workspace'u platformy "
                    f"wprost ({', '.join(named)}). Moduł wertykału nie nazywa go nigdy, "
                    "także w komendzie operatora — użyj bloku: "
                    "`from saas_core.modules.core.organizations.api import "
                    f"{WORKSPACE_BLOCK}` i `with {WORKSPACE_BLOCK}() as organization_id:`. "
                    "Komenda, która potrzebuje wiersza organizacji, czyta go w bloku "
                    "(`Organization.objects.get(pk=organization_id)`), wychodzi i prowadzi "
                    "własne transakcje jak dotąd (ADR-080, „Uzupełnienie PR1c”; "
                    "docs/architecture/product-public-site.md §13). Workspace zakłada "
                    "komenda rdzenia provision_platform_workspace."
                )
        elif path not in declared:
            problems.append(
                f"{path}: nowy moduł rdzenia sięga po workspace platformy bez hosta "
                f"({', '.join(sorted(names))}). Dopisz go do DECLARED_WORKSPACE_LOOKUPS "
                "razem z powodem (ADR-041, ADR-079 pkt 31) — albo nie sięgaj."
            )
        elif names != declared[path]:
            problems.append(
                f"{path}: nazywa {', '.join(sorted(names))}, a deklaracja mówi "
                f"{', '.join(sorted(declared[path]))} — popraw wpis w DECLARED_WORKSPACE_LOOKUPS."
            )
    problems.extend(
        f"{path}: zadeklarowany w DECLARED_WORKSPACE_LOOKUPS, a niczego już nie nazywa — usuń wpis."
        for path in sorted(set(declared) - set(usage))
    )
    return problems


def _yields_inside_the_block(source: str) -> list[int]:
    """The lines where a function gives control away from inside the block:
    a `yield` under `with in_platform_workspace()`.

    A generator suspended there hands control back to its caller with the
    platform's tenant still set and a signed-in visitor's own context still
    hidden — the caller's statements between two values run as the platform.
    The block is known by its name, by the name it was imported under, or as
    an attribute of anything. A function defined inside the block is another
    scope and is looked at by itself; a `@contextmanager` that wraps the
    block is a block itself, entered and left by its caller's `with`, and is
    let through.
    """
    tree = ast.parse(source)
    names = {WORKSPACE_BLOCK} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == WORKSPACE_BLOCK and alias.asname
    }
    functions = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

    def own(node: ast.AST) -> Iterator[ast.AST]:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, functions):
                yield child
                yield from own(child)

    def enters(item: ast.withitem) -> bool:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            return False
        function = call.func
        return (isinstance(function, ast.Name) and function.id in names) or (
            isinstance(function, ast.Attribute) and function.attr == WORKSPACE_BLOCK
        )

    def wraps(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any(
            (isinstance(decorator, ast.Name) and decorator.id in CONTEXT_MANAGERS)
            or (isinstance(decorator, ast.Attribute) and decorator.attr in CONTEXT_MANAGERS)
            for decorator in function.decorator_list
        )

    found: set[int] = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or wraps(function):
            continue
        for node in own(function):
            if isinstance(node, (ast.With, ast.AsyncWith)) and any(map(enters, node.items)):
                found |= {
                    inner.lineno
                    for inner in own(node)
                    if isinstance(inner, (ast.Yield, ast.YieldFrom))
                }
    return sorted(found)


def _suspended_blocks(root: Path = SOURCE) -> list[str]:
    """One line per `yield` inside the block, saying what to write instead."""
    return [
        f"{path.relative_to(root).as_posix()}:{line}: `yield` wewnątrz "
        f"`with {WORKSPACE_BLOCK}()` — generator zawieszony w bloku oddaje sterowanie "
        "wywołującemu z ustawionym tenantem platformy i ukrytym kontekstem zalogowanego "
        "gościa. Policz wynik w bloku (`list(…)`) i oddaj go po wyjściu; `yield` w bloku "
        "wolno tylko funkcji `@contextmanager`, która sama jest blokiem."
        for path in sorted(root.rglob("*.py"))
        for line in _yields_inside_the_block(path.read_text(encoding="utf-8"))
    ]


def test_only_the_declared_places_read_before_a_tenant() -> None:
    actual = _door_usage()
    expected = {path: count for path, (count, _reason) in DECLARED_DOOR.items()}

    assert actual == expected, (
        "Lista miejsc czytających przed poznaniem tenanta rozjechała się z "
        "deklaracją (ADR-041). Dopisz nowe użycie do DECLARED_DOOR razem z "
        f"powodem albo usuń wpis, którego już nie ma: {actual}"
    )


def test_every_declared_place_says_why() -> None:
    for path, (count, reason) in {**DECLARED_DOOR, **DECLARED_ALIAS}.items():
        assert count > 0, path
        assert len(reason) > 20, f"{path}: powód jest zbyt ogólny, żeby coś znaczył"


def test_nobody_names_the_doors_alias_but_the_declared_places(tmp_path: Path) -> None:
    """The count of `PRE_TENANT_DB` is only a count of the door if the
    constant is the one way to it. The alias written out, or read from the
    setting, is the other way — so every place that does either is listed
    with what it does, and none of them sends a query."""
    actual = _alias_usage()

    assert actual == {path: count for path, (count, _reason) in DECLARED_ALIAS.items()}, (
        "Ktoś nazywa alias drzwi sprzed tenanta bez stałej `PRE_TENANT_DB` (literał albo "
        "`settings.PRE_TENANT_DATABASE_ALIAS`). Zapytanie przez drzwi pisz stałą i dopisz "
        f"do DECLARED_DOOR; inne użycie dopisz z powodem do DECLARED_ALIAS: {actual}"
    )
    # What the first count cannot see, each written the way it would be.
    alias = import_module("saas_core.config.settings.base").PRE_TENANT_DATABASE_ALIAS
    for source, uses in (
        (f'Membership.all_objects.using("{alias}").filter(user=user)\n', 1),
        ("rows = Role.objects.using(settings.PRE_TENANT_DATABASE_ALIAS).all()\n", 1),
        ("from django.conf import settings as s\nx = s.PRE_TENANT_DATABASE_ALIAS\n", 1),
        (f'with connections["{alias}"].cursor() as cursor:\n    pass\n', 1),
        ('alias = getattr(settings, "PRE_TENANT_DATABASE_ALIAS", None)\n', 1),
        (f'DOOR = "{alias}"\nrows = Role.objects.using(DOOR)\n', 1),
        # The constant is the first count's business, and words are no alias.
        ("from .pre_tenant import PRE_TENANT_DB\nrows = Role.objects.using(PRE_TENANT_DB)\n", 0),
        (f'"""Reads through the {alias} door, see PRE_TENANT_DATABASE_ALIAS."""\n', 0),
        (f"# .using('{alias}') would be wrong here\nvalue = 1\n", 0),
    ):
        assert _alias_names(source, alias) == uses, source
    # A file nobody declared is noticed wherever it lies.
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "quiet.py").write_text(
        f'rows = Organization.objects.using("{alias}").all()\n', encoding="utf-8"
    )
    assert _alias_usage(tmp_path) == {"modules/quiet.py": 1}


def test_only_the_declared_places_look_the_platform_workspace_up() -> None:
    """ADR-079 pkt 31, ADR-080 „Uzupełnienie PR1c". The product's own pages
    read and write with no host to name a tenant, so they find the workspace
    through the door — the public paths that do. What keeps them few is this
    list: the count of `PRE_TENANT_DB` lines does not move when another
    module starts calling a lookup or the block, and this fails when one of
    the core does. A product's own module calls the block without a line
    here and fails for naming a lookup — with what to write instead."""
    declared = {path: names for path, (names, _reason) in DECLARED_WORKSPACE_LOOKUPS.items()}
    problems = _workspace_problems(_workspace_usage(), declared) + _suspended_blocks()

    assert not problems, (
        "Kto sięga po workspace platformy bez hosta, rozjechał się z regułą "
        "(ADR-041, ADR-079 pkt 31, ADR-080 „Uzupełnienie PR1c”):\n" + "\n".join(problems)
    )
    for path, (names, reason) in DECLARED_WORKSPACE_LOOKUPS.items():
        assert names and names <= WORKSPACE_NAMES, path
        assert len(reason) > 20, f"{path}: powód jest zbyt ogólny, żeby coś znaczył"
        # A product's module needs no line, and may not buy a lookup with one.
        assert not path.startswith(PRODUCT_MODULES), path


def test_a_products_module_runs_the_block_and_never_names_the_lookup(tmp_path: Path) -> None:
    """The rule as a product's tree meets it, on a module no product has.

    A product takes this file with the core and may not edit it (ADR-049):
    its vertical module passes with the block and without a declaration, in
    a view and in a command alike; where it names a lookup, the failure
    tells its author what to write. The core stays closed — a shared or core
    module that starts using either fails until it is declared here."""
    block = (
        "from saas_core.modules.core.organizations.api import in_platform_workspace\n\n\n"
        "def rows():\n"
        "    with in_platform_workspace() as organization_id:\n"
        "        return organization_id\n"
    )
    lookup = "from saas_core.modules.core.organizations.platform_workspace import {name}\n"
    tree = {
        # What a product writes: a visitor's form, a public read, a command.
        "modules/vertical/kennel/site_forms.py": block,
        "modules/vertical/kennel/management/commands/kennel_import.py": block,
        # What it wrote before: the lookup, in a view and in a command.
        "modules/vertical/kennel/breeds.py": lookup.format(name="platform_workspace_id"),
        "modules/vertical/kennel/management/commands/kennel_seed.py": lookup.format(
            name="platform_workspace"
        ),
        "modules/vertical/kennel/management/commands/kennel_setup.py": lookup.format(
            name="ensure_platform_workspace"
        ),
        # The core, quietly: the block and a lookup, undeclared.
        "modules/shared/somebody/reads.py": block,
        "modules/core/somebody/reads.py": lookup.format(name="platform_workspace_id"),
        # Nothing to do with any of it.
        "modules/vertical/kennel/models.py": "platform_workspace = None\n",
    }
    for relative, source in tree.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    problems = _workspace_problems(_workspace_usage(tmp_path), {})

    told = {problem.split(": ", 1)[0]: problem for problem in problems}
    assert sorted(told) == [
        "modules/core/somebody/reads.py",
        "modules/shared/somebody/reads.py",
        "modules/vertical/kennel/breeds.py",
        "modules/vertical/kennel/management/commands/kennel_seed.py",
        "modules/vertical/kennel/management/commands/kennel_setup.py",
    ]
    for path, named in (
        ("modules/vertical/kennel/breeds.py", "platform_workspace_id"),
        ("modules/vertical/kennel/management/commands/kennel_seed.py", "platform_workspace"),
        (
            "modules/vertical/kennel/management/commands/kennel_setup.py",
            "ensure_platform_workspace",
        ),
    ):
        # Names what it found, and the block with where it is imported from.
        assert f"({named})" in told[path]
        assert (
            "from saas_core.modules.core.organizations.api import in_platform_workspace"
            in (told[path])
        )
        assert "with in_platform_workspace() as organization_id:" in told[path]
        # And how a command gets the row it used to get from the lookup.
        assert "Organization.objects.get(pk=organization_id)" in told[path]
        assert "DECLARED_WORKSPACE_LOOKUPS" not in told[path]
    for path in ("modules/shared/somebody/reads.py", "modules/core/somebody/reads.py"):
        assert "DECLARED_WORKSPACE_LOOKUPS" in told[path]
    # A declaration opens the core's module, and only for the name it gives.
    declared = {"modules/shared/somebody/reads.py": frozenset({"in_platform_workspace"})}
    assert "modules/shared/somebody/reads.py" not in {
        problem.split(": ", 1)[0]
        for problem in _workspace_problems(_workspace_usage(tmp_path), declared)
    }
    declared = {"modules/shared/somebody/reads.py": frozenset({"platform_workspace_id"})}
    assert any(
        problem.startswith("modules/shared/somebody/reads.py: nazywa in_platform_workspace")
        for problem in _workspace_problems(_workspace_usage(tmp_path), declared)
    )


def test_nothing_yields_from_inside_the_block(tmp_path: Path) -> None:
    """„Evaluate inside, never yield inside." A product's reader written as a
    generator would run its caller — a signed-in customer's request, say —
    under the platform's tenant between two values. The guard names the line;
    a `@contextmanager` around the block is the one `yield` it lets through,
    because its caller enters and leaves it as it would the block."""
    surface = "from saas_core.modules.core.organizations.api import in_platform_workspace"
    tree = {
        "modules/vertical/kennel/readers.py": (
            f"{surface}\n\n\n"
            "def breeds():\n"
            "    with in_platform_workspace() as organization_id:\n"
            "        for row in rows(organization_id):\n"
            "            yield row\n"  # line 7
        ),
        "modules/vertical/kennel/pages.py": (
            f"{surface} as publisher\n"
            "from saas_core.modules.core.organizations import api\n\n\n"
            "def pages():\n"
            "    with publisher():\n"
            "        yield from every()\n"  # line 7
            "\n\n"
            "async def later():\n"
            "    with api.in_platform_workspace() as organization_id:\n"
            "        if organization_id:\n"
            "            yield organization_id\n"  # line 13
        ),
        # What a product writes instead, and the wrapper that is a block.
        "modules/vertical/kennel/site_forms.py": (
            "from contextlib import contextmanager\n\n"
            f"{surface}\n\n\n"
            "@contextmanager\n"
            "def publisher():\n"
            "    with in_platform_workspace() as organization_id:\n"
            "        yield organization_id\n"
            "\n\n"
            "def breeds():\n"
            "    with in_platform_workspace() as organization_id:\n"
            "        found = list(rows(organization_id))\n"
            "    yield from found\n"
            "\n\n"
            "def names():\n"
            "    with in_platform_workspace() as organization_id:\n"
            "        def each():\n"
            "            yield organization_id\n"
            "        return list(each())\n"
        ),
    }
    for relative, source in tree.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    problems = _suspended_blocks(tmp_path)

    assert [problem.split(": ", 1)[0] for problem in problems] == [
        "modules/vertical/kennel/pages.py:7",
        "modules/vertical/kennel/pages.py:13",
        "modules/vertical/kennel/readers.py:7",
    ]
    for problem in problems:
        assert "`yield` wewnątrz `with in_platform_workspace()`" in problem
        assert "list(" in problem and "@contextmanager" in problem


def test_the_block_is_what_the_modules_surface_offers_and_the_lookups_are_not() -> None:
    """A product imports from `core.organizations.api`. The block is there;
    a lookup passed on from there would be one import away from every
    vertical module — the detector would still name it, and it is simply
    not offered."""
    assert WORKSPACE_BLOCK in organizations_api.__all__
    assert callable(getattr(organizations_api, WORKSPACE_BLOCK))
    assert "PlatformWorkspaceMissing" in organizations_api.__all__
    for name in WORKSPACE_LOOKUPS:
        assert name not in organizations_api.__all__
        assert not hasattr(organizations_api, name)


def test_a_new_caller_of_the_workspace_lookup_is_noticed_however_it_is_written() -> None:
    """The list is worth what its detector sees. The review of ADR-079 found
    that the door test above would not notice a new caller at all; this holds
    the detector to the ways a caller can be written."""
    package = "saas_core.modules.core.organizations"
    module = f"{package}.platform_workspace"
    every, one, by_id = set(WORKSPACE_LOOKUPS), {"platform_workspace"}, {"platform_workspace_id"}
    block, provisioning = {WORKSPACE_BLOCK}, {"ensure_platform_workspace"}
    for source, expected in (
        # The block, from the module's surface, from where it is defined, as
        # an attribute and by its name.
        (f"from {package}.api import in_platform_workspace\n", block),
        (f"from {module} import in_platform_workspace as publisher\n", block),
        ("with organizations.in_platform_workspace() as found:\n    pass\n", block),
        ("enter = getattr(api, 'in_platform_workspace')\n", block),
        (f"from {module} import in_platform_workspace, platform_workspace_id\n", block | by_id),
        # The one that provisions it finds it too, and gives the row back.
        (f"from {module} import ensure_platform_workspace\n", provisioning),
        ("found, _made = organizations.ensure_platform_workspace()\n", provisioning),
        (f"from {module} import platform_workspace_id\n", by_id),
        (f"from {module} import platform_workspace as find\n", one),
        ("def read():\n    from .platform_workspace import platform_workspace_id\n", by_id),
        (f"from {module} import *\n", every | block),
        # Passed on by another module, and taken from there.
        (f"from {package}.api import platform_workspace_id\n", by_id),
        # The defining module taken whole: everything in it is within reach.
        (f"from {package} import platform_workspace\n", every),
        (f"import {module} as publisher\n", every),
        ("found = organizations.platform_workspace_id()\n", by_id),
        ("found = getattr(module, 'platform_workspace_id')()\n", by_id),
        (f"module = import_module('{module}')\n", one),
    ):
        assert _workspace_names(source) == expected, source
    for source in (
        # Another function of that module, and a name that only resembles one.
        f"from {package}.platform_workspace import is_platform_workspace\n",
        "platform_workspace = organization.workspace_kind == WorkspaceKind.PLATFORM\n",
        "def test(platform_workspace_slug):\n    return platform_workspace_slug\n",
        "dependencies = [('organizations', '0021_platform_workspace')]\n",
        "default_code = 'platform_workspace_forbidden'\n",
        "raise PlatformWorkspaceMissing\n",
        "def in_platform_workspace_demo():\n    return in_platform()\n",
    ):
        assert _workspace_names(source) == set(), source


def test_the_public_renderer_never_reads_through_the_door() -> None:
    """The most exposed surface stays inside the tenant its host named.

    A hostname resolves to an organization through `sites_domain`, which has no
    policy to bypass, so the renderer can set that tenant and read the registry
    from inside it. Letting it hold the pre-tenant connection instead would give
    one injection in the public path the reach over every tenant's memberships
    and invitations that ADR-041 exists to take away — so this is a rule about
    where the door may be, not only how often.
    """
    public = {
        "modules/shared/sites/publication_routing.py",
        "modules/shared/sites/public_views.py",
        "modules/shared/sites/public_feeds.py",
        "modules/shared/sites/public_media.py",
        "modules/shared/sites/tls.py",
    }
    assert public & set(_door_usage()) == set()
    assert public & set(_alias_usage()) == set()
    # Nor by asking somebody else to: the workspace lookups read through it,
    # and so does the block — a host named this tenant, and no other is its.
    assert public & set(_workspace_usage()) == set()


def test_the_door_is_configured_as_its_own_identity_outside_tests() -> None:
    """Its reach is the policies naming it, not a role attribute.

    A role with BYPASSRLS would see every tenant table in the database; this one
    sees exactly the tables a migration opened to it, which is why opening the
    next one is a change somebody has to write down. The running settings are
    read here rather than the test ones, where both aliases deliberately point
    at the same connection.
    """
    module = import_module("saas_core.config.settings.base")
    alias = module.PRE_TENANT_DATABASE_ALIAS
    door = module.DATABASES[alias]

    assert alias != "default"
    assert door["USER"] != module.DATABASES["default"]["USER"]
    assert door["HOST"] == module.DATABASES["default"]["HOST"]
    # One database behind both names, so the door is a different identity
    # rather than a different store.
    assert door["TEST"] == {"MIRROR": "default"}
