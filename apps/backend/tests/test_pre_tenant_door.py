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
from importlib import import_module
from pathlib import Path

from django.conf import settings

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
        "jedna kolumna) dla odczytów z listy DECLARED_WORKSPACE_LOOKUPS",
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

#: The functions that find the platform's workspace through the door. A call
#: to one of them is a read before a tenant is known just as a line with
#: `PRE_TENANT_DB` is — and the count above cannot see it: the line it counts
#: stays where it is, in the module that defines them, however many places
#: start calling it.
WORKSPACE_LOOKUPS = frozenset({"platform_workspace", "platform_workspace_id"})
WORKSPACE_LOOKUP_DEFINITION = "modules/core/organizations/platform_workspace.py"

#: Who may ask, which of the two, and why. A module is on this list when it
#: names a lookup at all — imports it, reaches it as an attribute, or spells
#: its name in a string — so a new caller fails the test until somebody
#: writes down here what it does with the answer.
DECLARED_WORKSPACE_LOOKUPS: dict[str, tuple[frozenset[str], str]] = {
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


def _lookups_named(source: str) -> set[str]:
    """The workspace lookups a module names, however it gets at them.

    - `from … import platform_workspace_id`, from the defining module or from
      one that passes it on;
    - the defining module taken whole (`import ….platform_workspace`,
      `from …organizations import platform_workspace`): everything in it is
      then one attribute away, so that counts as both;
    - an attribute of either name on anything (`module.platform_workspace()`);
    - either name spelled in a string, which is how `getattr` reaches it.

    A local variable that merely happens to be called `platform_workspace` is
    none of these.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").rsplit(".", 1)[-1]
            for alias in node.names:
                if alias.name in WORKSPACE_LOOKUPS and module != "platform_workspace":
                    # The defining module itself, imported from its package.
                    found |= (
                        WORKSPACE_LOOKUPS if alias.name == "platform_workspace" else {alias.name}
                    )
                elif module == "platform_workspace" and alias.name in WORKSPACE_LOOKUPS:
                    found.add(alias.name)
                elif module == "platform_workspace" and alias.name == "*":
                    found |= WORKSPACE_LOOKUPS
        elif isinstance(node, ast.Import):
            if any(alias.name.rsplit(".", 1)[-1] == "platform_workspace" for alias in node.names):
                found |= WORKSPACE_LOOKUPS
        elif isinstance(node, ast.Attribute) and node.attr in WORKSPACE_LOOKUPS:
            found.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= {
                name
                for name in WORKSPACE_LOOKUPS
                if node.value == name or node.value.endswith(f".{name}")
            }
    return found


def _workspace_lookup_usage() -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        if relative == WORKSPACE_LOOKUP_DEFINITION:
            continue
        names = _lookups_named(path.read_text(encoding="utf-8"))
        if names:
            found[relative] = frozenset(names)
    return found


def test_only_the_declared_places_read_before_a_tenant() -> None:
    actual = _door_usage()
    expected = {path: count for path, (count, _reason) in DECLARED_DOOR.items()}

    assert actual == expected, (
        "Lista miejsc czytających przed poznaniem tenanta rozjechała się z "
        "deklaracją (ADR-041). Dopisz nowe użycie do DECLARED_DOOR razem z "
        f"powodem albo usuń wpis, którego już nie ma: {actual}"
    )


def test_every_declared_place_says_why() -> None:
    for path, (count, reason) in DECLARED_DOOR.items():
        assert count > 0, path
        assert len(reason) > 20, f"{path}: powód jest zbyt ogólny, żeby coś znaczył"


def test_only_the_declared_places_look_the_platform_workspace_up() -> None:
    """ADR-079 pkt 31. The product's own pages read the platform's published
    content with no host to name a tenant, so that read finds the workspace
    through the door — the one public path that does. What keeps it one is
    this list: the count of `PRE_TENANT_DB` lines does not move when another
    module starts calling the lookup, and this fails when one does."""
    actual = _workspace_lookup_usage()
    expected = {path: names for path, (names, _reason) in DECLARED_WORKSPACE_LOOKUPS.items()}

    assert actual == expected, (
        "Ktoś nowy odnajduje workspace platformy przez drzwi sprzed tenanta albo "
        "zadeklarowane miejsce już tego nie robi. Dopisz je do "
        "DECLARED_WORKSPACE_LOOKUPS razem z powodem albo usuń wpis (ADR-041, "
        f"ADR-079 pkt 31): {actual}"
    )
    for path, (names, reason) in DECLARED_WORKSPACE_LOOKUPS.items():
        assert names and names <= WORKSPACE_LOOKUPS, path
        assert len(reason) > 20, f"{path}: powód jest zbyt ogólny, żeby coś znaczył"


def test_a_new_caller_of_the_workspace_lookup_is_noticed_however_it_is_written() -> None:
    """The list is worth what its detector sees. The review of ADR-079 found
    that the door test above would not notice a new caller at all; this holds
    the detector to the ways a caller can be written."""
    package = "saas_core.modules.core.organizations"
    module = f"{package}.platform_workspace"
    both, one, by_id = set(WORKSPACE_LOOKUPS), {"platform_workspace"}, {"platform_workspace_id"}
    for source, expected in (
        (f"from {module} import platform_workspace_id\n", by_id),
        (f"from {module} import platform_workspace as find\n", one),
        ("def read():\n    from .platform_workspace import platform_workspace_id\n", by_id),
        (f"from {module} import *\n", both),
        # Passed on by another module, and taken from there.
        (f"from {package}.api import platform_workspace_id\n", by_id),
        # The defining module taken whole: everything in it is within reach.
        (f"from {package} import platform_workspace\n", both),
        (f"import {module} as publisher\n", both),
        ("found = organizations.platform_workspace_id()\n", by_id),
        ("found = getattr(module, 'platform_workspace_id')()\n", by_id),
        (f"module = import_module('{module}')\n", one),
    ):
        assert _lookups_named(source) == expected, source
    for source in (
        # Another function of that module, and a name that only resembles one.
        f"from {package}.platform_workspace import is_platform_workspace\n",
        "platform_workspace = organization.workspace_kind == WorkspaceKind.PLATFORM\n",
        "def test(platform_workspace_slug):\n    return ensure_platform_workspace()\n",
        "dependencies = [('organizations', '0021_platform_workspace')]\n",
        "default_code = 'platform_workspace_forbidden'\n",
    ):
        assert _lookups_named(source) == set(), source


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
    # Nor by asking somebody else to: the workspace lookups read through it.
    assert public & set(_workspace_lookup_usage()) == set()


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
