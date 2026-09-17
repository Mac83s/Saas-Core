"""A profile composes a product; a module left out of it is not there at all.

P1 of the post-audit plan asks for two products from one repository. Until the
profile actually decided what the process is made of, that claim rested on a
validator: `deployment.json` was checked and then ignored, and every image
installed every module, so `core-only` still carried Billing's tables, Sites'
URLs and Booking's scheduled tasks. These tests are what makes the claim
checkable — they ask what each profile composes without booting a second
Django, which is the only way to ask about a profile the suite does not run
under.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest
from django.conf import settings

from saas_core.config.composition import (
    CompositionError,
    ModuleDescriptor,
    compose,
    django_apps_for,
    load_catalog,
    select_by_module,
    verify_artifact,
)
from saas_core.config.urls import urlpatterns_for

DEPLOYMENTS = Path(settings.BASE_DIR).parent.parent / "deployments"
CATALOG = load_catalog(settings.MODULE_CATALOG_PATH)

#: What a deployment without the Shared layer must not contain, in any form.
SHARED_MODULES = (
    "shared.billing",
    "shared.sites",
    "shared.media",
    "shared.notifications",
    "shared.booking",
)


def profile_modules(name: str) -> list[str]:
    profile = json.loads((DEPLOYMENTS / name / "deployment.json").read_text(encoding="utf-8"))
    return list(profile["modules"])


def route_prefixes(active_modules: list[str]) -> set[str]:
    return {str(route.pattern) for route in urlpatterns_for(active_modules)}


def test_core_only_composes_three_apps_and_nothing_from_shared() -> None:
    modules = compose(profile_modules("core-only"), CATALOG)
    apps = django_apps_for(modules, CATALOG)

    assert apps == (
        "saas_core.modules.core.health",
        "saas_core.modules.core.identity",
        "saas_core.modules.core.organizations",
    )
    assert not [app for app in apps if ".shared." in app]


def test_business_composes_every_shared_module() -> None:
    modules = compose(profile_modules("business"), CATALOG)

    assert set(SHARED_MODULES) <= set(modules)
    # Dependencies first, so Django sees an app after everything it imports.
    assert modules.index("core.organizations") < modules.index("shared.billing")


def test_core_only_registers_no_route_of_a_module_it_does_not_have() -> None:
    prefixes = route_prefixes(profile_modules("core-only"))

    assert "api/v1/auth/" in prefixes
    assert "api/v1/organizations/" in prefixes
    for absent in (
        "api/v1/billing/",
        "api/v1/sites/",
        "api/v1/media/",
        "api/v1/notifications/",
        "api/v1/booking/",
        "api/v1/public/site/",
        "internal/caddy/domains/authorize/",
    ):
        assert absent not in prefixes, f"core-only nie powinien wystawiać {absent}"


def test_business_registers_the_routes_core_only_refuses() -> None:
    prefixes = route_prefixes(profile_modules("business"))

    for present in ("api/v1/billing/", "api/v1/sites/", "api/v1/booking/"):
        assert present in prefixes


#: Every vertical and the profile that owns it, with the route it registers.
VERTICALS = (
    ("hoofcare", "vertical.hoofcare", "api/v1/hoofcare/"),
    ("medplano", "vertical.medical", "api/v1/medical/"),
)


@pytest.mark.parametrize(("profile", "module", "route"), VERTICALS)
def test_a_vertical_composes_only_where_its_profile_names_it(
    profile: str, module: str, route: str
) -> None:
    modules = compose(profile_modules(profile), CATALOG)

    assert module in modules
    # Dependencies first: a vertical sits above shared, which sits above core.
    assert modules.index("shared.booking") < modules.index(module)
    assert route in route_prefixes(profile_modules(profile))

    for other in ("business", "core-only"):
        elsewhere = compose(profile_modules(other), CATALOG)
        assert module not in elsewhere
        assert not [app for app in django_apps_for(elsewhere, CATALOG) if ".vertical." in app]
        assert route not in route_prefixes(profile_modules(other))


def test_one_vertical_never_arrives_with_another() -> None:
    """Two products, one tree: a profile must carry its vertical and no other."""
    for profile, module, route in VERTICALS:
        modules = compose(profile_modules(profile), CATALOG)
        strangers = [
            other for _, other, _ in VERTICALS if other != module and other in modules
        ]
        assert strangers == [], f"{profile} wciągnął cudzy wertykał: {strangers}"

        prefixes = route_prefixes(profile_modules(profile))
        assert [r for _, _, r in VERTICALS if r != route and r in prefixes] == []


def test_core_only_schedules_no_work_for_modules_it_does_not_have() -> None:
    base = import_module("saas_core.config.settings.base")
    core_only = compose(profile_modules("core-only"), CATALOG)

    schedule = select_by_module(base._MODULE_BEAT_SCHEDULE, core_only, frozenset(CATALOG))

    assert schedule == {}


def test_the_running_deployment_schedules_only_its_own_modules() -> None:
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        owner = str(entry["task"]).removeprefix("saas_core.modules.")
        module_id = ".".join(owner.split(".")[:2])
        assert module_id in settings.ACTIVE_MODULES, f"{name} należy do nieaktywnego {module_id}"


def test_installed_apps_are_the_composition_rather_than_a_second_list() -> None:
    """Nobody may re-hardcode the list next to the one the profile derives."""
    module_apps = tuple(
        app for app in settings.INSTALLED_APPS if app.startswith("saas_core.modules.")
    )

    assert module_apps == django_apps_for(settings.ACTIVE_MODULES, CATALOG)


def test_module_middleware_is_mounted_only_where_its_module_is() -> None:
    api_key = (
        "saas_core.modules.shared.notifications.api_key_middleware."
        "ApiKeyTenantContextMiddleware"
    )
    base = import_module("saas_core.config.settings.base")

    assert base._MODULE_MIDDLEWARE["shared.notifications"] == api_key
    assert (api_key in settings.MIDDLEWARE) == ("shared.notifications" in settings.ACTIVE_MODULES)


def test_a_profile_that_omits_a_dependency_is_refused_rather_than_completed() -> None:
    """Silently pulling `core.organizations` in would compose what nobody chose."""
    with pytest.raises(CompositionError, match="wymaga modułu core.organizations"):
        compose(["core.health", "core.identity", "shared.billing"], CATALOG)


def test_a_dependency_pointing_outwards_is_refused() -> None:
    catalog = {
        "core.identity": ModuleDescriptor(
            id="core.identity",
            layer="core",
            depends_on=("shared.billing",),
            django_app="saas_core.modules.core.identity",
        ),
        "shared.billing": ModuleDescriptor(
            id="shared.billing",
            layer="shared",
            depends_on=(),
            django_app="saas_core.modules.shared.billing",
        ),
    }

    with pytest.raises(CompositionError, match="Niedozwolony kierunek"):
        compose(["core.identity", "shared.billing"], catalog)


def test_a_cycle_is_named_rather_than_walked_forever() -> None:
    catalog = {
        "shared.a": ModuleDescriptor("shared.a", "shared", ("shared.b",), None),
        "shared.b": ModuleDescriptor("shared.b", "shared", ("shared.a",), None),
    }

    with pytest.raises(CompositionError, match="cykl"):
        compose(["shared.a", "shared.b"], catalog)


def test_scheduled_work_attached_to_an_unknown_module_fails_loudly() -> None:
    """A typo here is a job that never runs and never says so."""
    with pytest.raises(CompositionError, match="shared.bookings"):
        select_by_module(
            {"shared.bookings": {"x": {"task": "t", "schedule": 1.0}}},
            ("shared.booking",),
            frozenset(CATALOG),
        )


def test_the_artifact_describes_the_composition_this_process_derived() -> None:
    """A build fingerprint is only worth carrying if it matches what booted."""
    artifact = json.loads(Path(settings.MODULE_ARTIFACT_PATH).read_text(encoding="utf-8"))

    assert (
        verify_artifact(
            artifact,
            deployment=settings.DEPLOYMENT,
            modules=settings.ACTIVE_MODULES,
            catalog=CATALOG,
        )
        == settings.PROFILE_HASH
    )
    assert settings.PROFILE_HASH.startswith("sha256:")


def test_an_artifact_from_another_deployment_is_refused() -> None:
    other = json.loads((DEPLOYMENTS / "core-only" / "module-artifact.json").read_text("utf-8"))

    with pytest.raises(CompositionError, match="deployment"):
        verify_artifact(
            other,
            deployment=settings.DEPLOYMENT,
            modules=settings.ACTIVE_MODULES,
            catalog=CATALOG,
        )


def test_an_artifact_that_lists_other_modules_is_refused() -> None:
    """The image was built from a tree this one no longer is."""
    artifact = json.loads(Path(settings.MODULE_ARTIFACT_PATH).read_text(encoding="utf-8"))
    artifact["modules"] = artifact["modules"][:-1]

    with pytest.raises(CompositionError, match="inne moduły"):
        verify_artifact(
            artifact,
            deployment=settings.DEPLOYMENT,
            modules=settings.ACTIVE_MODULES,
            catalog=CATALOG,
        )


def test_an_artifact_without_a_fingerprint_is_refused() -> None:
    artifact = json.loads(Path(settings.MODULE_ARTIFACT_PATH).read_text(encoding="utf-8"))
    artifact.pop("profileHash")

    with pytest.raises(CompositionError, match="profileHash"):
        verify_artifact(
            artifact,
            deployment=settings.DEPLOYMENT,
            modules=settings.ACTIVE_MODULES,
            catalog=CATALOG,
        )
