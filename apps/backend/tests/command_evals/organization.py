"""Evals of the company's own commands (`core/organizations/command_declarations.py`)."""

from __future__ import annotations

from typing import Any

from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization

from . import CommandEval


def _settings(context: TenantContext) -> dict[str, Any]:
    return dict(
        Organization.objects.filter(pk=context.organization_id)
        .values("name", "default_locale", "timezone", "currency", "version")
        .get()
    )


def _bump(context: TenantContext) -> None:
    Organization.objects.filter(pk=context.organization_id).update(version=F("version") + 1)


EVALS = {
    "organization.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"name": "Domki"},
        wrong_field="name",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_settings,
    ),
    "organization.update@1": CommandEval(
        arguments=lambda _context: {
            "name": "Domki nad jeziorem",
            "default_locale": None,
            "timezone": "Europe/Berlin",
            "currency": None,
        },
        wrong_arguments={"name": None, "default_locale": "de", "timezone": None, "currency": None},
        wrong_field="default_locale",
        stale=_bump,
        state=_settings,
    ),
}
