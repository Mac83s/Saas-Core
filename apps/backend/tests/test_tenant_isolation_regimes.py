"""ADR-039: two isolation regimes, checked against the live schema.

Every tenant table carries forced row-level security unless its module
descriptor lists it in ``backend.publicTables`` — the tables the public
renderer reads for a visitor who has no tenant context. The descriptor is the
declaration; this test is what makes the declaration true: a new tenant table
without RLS fails here, and so does a table declared public that still has a
policy (RLS on a table read without the tenant setting answers with no rows,
which is a worse failure than an honest error).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models import ForeignKey

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.tenancy import TenantScopedModel

MODULES_PATH = Path(settings.SITE_BLOCK_CONTRACTS_PATH).parent / "modules"

# Debt the rule already knows about, listed so it cannot grow and cannot
# linger: a table added here that later gains RLS fails the test until the
# entry is removed. Add an entry only with the plan item that removes it.
#
# These six are read or written before a tenant is known, which is why a policy
# cannot simply be added to them (plan 13, P1):
#   - organizations_membership answers "which companies is this account in?"
#     at login, before any organization is chosen — under a policy keyed on
#     app.organization_id that question returns nothing and nobody logs in;
#   - organizations_organization is the registry the same answer resolves to;
#   - organizations_role holds the global roles as organization IS NULL rows,
#     shared by every tenant, so a policy has to admit them;
#   - organizations_invitation is read by its token by someone who is not yet
#     a member, and organizations_billingprofile is how the Stripe processor
#     finds the tenant an event belongs to — both reads precede the tenant;
#   - organizations_organizationauditentry is written on those same paths;
# ADR-041 decides each of them: a plain tenant policy plus a named door for the
# pre-tenant paths, migrated table by table, personal data first. The webhook
# inbox left this list by being classified as a platform table, which is what
# it always was.
KNOWN_OPEN_PRIVATE_TABLES: dict[str, frozenset[str]] = {
    "saas_core.modules.core.organizations": frozenset(
        {
            "organizations_billingprofile",
            "organizations_invitation",
            "organizations_membership",
            "organizations_organization",
            "organizations_organizationauditentry",
            "organizations_role",
        }
    ),
}

pytestmark = pytest.mark.django_db


def _declared_tables_by_app(field: str) -> dict[str, set[str]]:
    declared: dict[str, set[str]] = {}
    for path in sorted(MODULES_PATH.glob("*.json")):
        descriptor: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        django_app = descriptor["backend"]["djangoApp"]
        if django_app is not None:
            declared[django_app] = set(descriptor["backend"][field])
    return declared


def _public_tables_by_app() -> dict[str, set[str]]:
    return _declared_tables_by_app("publicTables")


def _platform_tables_by_app() -> dict[str, set[str]]:
    """ADR-041: rows that name an organization but belong to the platform.

    A webhook event is stored the moment it arrives, before its payload says
    which tenant it concerns, so the row is born without one. Calling that
    table public would be a lie about why it has no policy.
    """
    return _declared_tables_by_app("platformTables")


def _carries_a_tenant(model: type[Any]) -> bool:
    """Whether a row of this model belongs to one organization.

    Inheriting ``TenantScopedModel`` is the usual way to say so, but it is not
    the only one and must not be what the rule looks for: a model that names an
    organization with a plain foreign key holds exactly as much tenant data,
    and asking only about the base class is how organizations_membership — the
    table that decides who belongs to which company — stayed invisible here
    while it had no policy at all. The organization registry counts too; its
    rows belong to one tenant each.
    """
    if model is Organization:
        return True
    if issubclass(model, TenantScopedModel):
        return True
    return any(
        isinstance(field, ForeignKey) and field.related_model is Organization
        for field in model._meta.get_fields()
    )


def _tenant_tables_by_app() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for model in apps.get_models():
        if not _carries_a_tenant(model):
            continue
        tables.setdefault(model._meta.app_config.name, set()).add(model._meta.db_table)
    return tables


def _rls_state(tables: set[str]) -> dict[str, tuple[bool, bool]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = ANY(%s) AND relkind = 'r'
            """,
            [sorted(tables)],
        )
        return {name: (enabled, forced) for name, enabled, forced in cursor.fetchall()}


def test_every_module_with_tenant_tables_has_a_descriptor() -> None:
    undeclared = set(_tenant_tables_by_app()) - set(_public_tables_by_app())

    assert sorted(undeclared) == []


def test_private_tenant_tables_force_row_level_security() -> None:
    public = _public_tables_by_app()
    platform = _platform_tables_by_app()
    open_private: dict[str, set[str]] = {}
    for django_app, tables in _tenant_tables_by_app().items():
        private = tables - public.get(django_app, set()) - platform.get(django_app, set())
        state = _rls_state(private)
        unguarded = {table for table in private if state.get(table) != (True, True)}
        if unguarded:
            open_private[django_app] = unguarded

    unexpected = {
        app: sorted(tables - KNOWN_OPEN_PRIVATE_TABLES.get(app, frozenset()))
        for app, tables in open_private.items()
        if tables - KNOWN_OPEN_PRIVATE_TABLES.get(app, frozenset())
    }
    assert unexpected == {}, (
        "tabele tenantowe bez wymuszonego RLS — dodaj politykę albo zadeklaruj "
        f"je w backend.publicTables deskryptora: {unexpected}"
    )

    # The debt list may only shrink: a table that gained RLS must leave it.
    stale = {
        app: sorted(known - open_private.get(app, set()))
        for app, known in KNOWN_OPEN_PRIVATE_TABLES.items()
        if known - open_private.get(app, set())
    }
    assert stale == {}, f"tabele mają już RLS — usuń je z KNOWN_OPEN_PRIVATE_TABLES: {stale}"


def test_declared_public_tables_exist_are_tenant_scoped_and_open() -> None:
    tenant_tables = _tenant_tables_by_app()
    for django_app, public in _public_tables_by_app().items():
        unknown = public - tenant_tables.get(django_app, set())
        assert sorted(unknown) == [], (
            f"{django_app}: publicTables wymienia tabele, które nie są tenantowymi "
            f"tabelami tego modułu: {sorted(unknown)}"
        )
        app_label = django_app.rsplit(".", 1)[-1]
        assert all(table.startswith(f"{app_label}_") for table in public), (
            f"{django_app}: tabela publiczna musi należeć do własnego modułu"
        )
        state = _rls_state(public)
        guarded = [table for table in sorted(public) if state.get(table) != (False, False)]
        assert guarded == [], (
            "tabele publiczne nie mogą mieć RLS, bo renderer czyta je bez kontekstu "
            f"tenanta i dostałby puste odpowiedzi: {guarded}"
        )


def test_platform_tables_are_declared_tenant_tables_without_policies() -> None:
    """ADR-041: the third regime has to be earned, not assumed.

    A platform table still has to be a real table of the module that claims it,
    and it has to actually be open — a policy on it would answer the webhook
    endpoint with silence instead of an error, which is the failure mode this
    whole contract exists to avoid.
    """
    tenant_tables = _tenant_tables_by_app()
    for django_app, platform in _platform_tables_by_app().items():
        unknown = platform - tenant_tables.get(django_app, set())
        assert sorted(unknown) == [], (
            f"{django_app}: platformTables wymienia tabele, które nie należą do "
            f"tego modułu: {sorted(unknown)}"
        )
        state = _rls_state(platform)
        guarded = [table for table in sorted(platform) if state.get(table) != (False, False)]
        assert guarded == [], (
            "tabela platformowa nie może mieć RLS, bo wiersz powstaje zanim "
            f"tenant jest znany: {guarded}"
        )
