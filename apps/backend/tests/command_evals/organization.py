"""Evals of the company's own commands (`core/organizations/command_declarations.py`)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.core.organizations.public_locales import offered_locales

from . import CommandEval


def _settings(context: TenantContext) -> dict[str, Any]:
    return dict(
        Organization.objects.filter(pk=context.organization_id)
        .values("name", "default_locale", "timezone", "currency", "version")
        .get()
    )


def _bump(context: TenantContext) -> None:
    Organization.objects.filter(pk=context.organization_id).update(version=F("version") + 1)


def _locales(context: TenantContext) -> dict[str, Any]:
    return dict(
        Organization.objects.filter(pk=context.organization_id)
        .values("public_locales", "public_locales_version")
        .get()
    )


def _one_more(_context: TenantContext) -> list[str]:
    """A new company's language and one more of the product's — from the
    settings, without a read: the battery counts the queries a refusal makes."""
    first = str(settings.SITES_DEFAULT_LOCALE)
    return [first, next(code for code in offered_locales() if code != first)]


def _bump_locales(context: TenantContext) -> None:
    Organization.objects.filter(pk=context.organization_id).update(
        public_locales_version=F("public_locales_version") + 1
    )


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
    "organization.public_locales.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"public_locales": ["pl"]},
        wrong_field="public_locales",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_locales,
    ),
    "organization.public_locales.update@1": CommandEval(
        # Adding: within a plan without a limit (the battery's companies have
        # one); removing and the limit have their own tests in
        # test_company_languages.py.
        arguments=lambda context: {"public_locales": _one_more(context)},
        wrong_arguments={"public_locales": "pl"},
        wrong_field="public_locales",
        stale=_bump_locales,
        state=_locales,
    ),
}
