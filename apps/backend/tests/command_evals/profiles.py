"""Evals of the business card commands (`shared/profiles/command_declarations.py`)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)
from saas_core.modules.shared.profiles.catalog import _place_entry
from saas_core.modules.shared.profiles.catalog_contract import categories
from saas_core.modules.shared.profiles.models import (
    CatalogEntry,
    ProfileSubjectKind,
    PublicProfile,
)

from . import CommandEval

CITY = "mragowo"


def _category() -> str:
    return next(iter(categories(settings.DEFAULT_ORGANIZATION_TYPE)))


def _card(context: TenantContext) -> PublicProfile:
    """Profiles in the plan and a card that can go into the catalogue."""
    EntitlementSnapshot.all_objects.create(
        organization_id=context.organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"profiles.enabled": True},
        quotas={},
        sources={"profiles.enabled": {"kind": "plan"}},
    )
    return PublicProfile.all_objects.create(
        organization_id=context.organization_id,
        subject_kind=ProfileSubjectKind.ORGANIZATION,
        display_name="Domki nad jeziorem",
        city_slug=CITY,
        category=_category(),
        locale="pl",
    )


def _listed(context: TenantContext) -> None:
    _place_entry(_card(context), context.organization_id)


def _state(context: TenantContext) -> dict[str, Any]:
    return {
        "card": list(
            PublicProfile.all_objects.filter(organization_id=context.organization_id).values_list(
                "display_name", "headline", "city_slug", "version"
            )
        ),
        "listed": CatalogEntry.all_objects.filter(organization_id=context.organization_id).exists(),
    }


def _bump(context: TenantContext) -> None:
    PublicProfile.all_objects.filter(organization_id=context.organization_id).update(
        version=F("version") + 1
    )


def _fields(**given: Any) -> dict[str, Any]:
    return {
        **dict.fromkeys((
            "display_name",
            "headline",
            "bio",
            "contact_email",
            "contact_phone",
            "contact_address",
            "city_slug",
            "category",
        )),
        **given,
    }


EVALS = {
    "profiles.organization.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"display_name": "Domki"},
        wrong_field="display_name",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_card,
    ),
    "profiles.catalog_options.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"locale": "pl"},
        wrong_field="locale",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_card,
    ),
    "profiles.organization.update@1": CommandEval(
        arguments=lambda _context: _fields(headline="Domki z widokiem na jezioro"),
        # Refused by the catalogue's dictionary, in the service.
        wrong_arguments=_fields(city_slug="atlantyda"),
        wrong_field="city_slug",
        stale=_bump,
        state=_state,
        prepare=_card,
    ),
    "profiles.catalog.publish@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"city_slug": CITY},
        wrong_field="city_slug",
        stale=_bump,
        state=_state,
        prepare=_card,
    ),
    "profiles.catalog.withdraw@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"slug": "domki"},
        wrong_field="slug",
        stale=_bump,
        state=_state,
        prepare=_listed,
    ),
}
