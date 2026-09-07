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
        1,
        "usunięcie tenanta: sprawdzenie, czy rejestr nadal zna tę organizację, "
        "gdy tenanta już nie ma",
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
    "modules/core/organizations/lifecycle.py": (
        1,
        "zaproszenie odnalezione po tokenie przez kogoś, kto nie jest jeszcze członkiem",
    ),
    "modules/core/organizations/platform_workspace.py": (
        2,
        "workspace platformy: czy ten deployment ma już swojego wydawcę — pytanie "
        "o rejestr, zadawane zanim istnieje organizacja, której mogłoby dotyczyć",
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
    "modules/shared/sites/management/commands/sites_e2e_fixture.py": (
        3,
        "fixture E2E: czy slug jest wolny w całym rejestrze i czy po sprzątaniu "
        "konto nie należy już do żadnej firmy",
    ),
}

#: The module that defines the alias obviously names it.
DEFINITION = "modules/core/organizations/pre_tenant.py"


def _door_usage() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        if relative == DEFINITION:
            continue
        uses = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if "PRE_TENANT_DB" in line
            and not line.lstrip().startswith(("from ", "import ", "#"))
        ]
        if uses:
            found[relative] = len(uses)
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
