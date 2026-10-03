"""Evals of the commands for the company's documents for customers
(`shared/customers/command_declarations.py`)."""

from __future__ import annotations

from typing import Any

from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.shared.customers.models import CustomerDocument

from . import CommandEval

KIND = "privacy_policy"


def _drafted(context: TenantContext) -> None:
    """A document somebody has begun: its lock is what a consent sees."""
    CustomerDocument.all_objects.create(
        organization_id=context.organization_id,
        kind=KIND,
        draft_text="Administratorem danych jest firma.",
        draft_locale="pl",
        version=1,
    )


def _state(context: TenantContext) -> list[Any]:
    return list(
        CustomerDocument.all_objects.filter(organization_id=context.organization_id)
        .order_by("kind")
        .values_list("kind", "draft_text", "draft_locale", "draft_origin_ref", "version")
    )


def _bump(context: TenantContext) -> None:
    CustomerDocument.all_objects.filter(organization_id=context.organization_id).update(
        version=F("version") + 1
    )


EVALS = {
    "customers.documents.read@1": CommandEval(
        arguments=lambda _context: {"kind": None},
        wrong_arguments={"kind": "regulamin"},
        wrong_field="kind",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_state,
        prepare=_drafted,
    ),
    "customers.document.draft.save@1": CommandEval(
        arguments=lambda _context: {
            "kind": KIND,
            "text": "Administratorem danych jest Studio.\n\nDane przetwarzamy, żeby umówić wizytę.",
            "locale": "pl",
        },
        # Refused by the service: a language the company does not have.
        wrong_arguments={"kind": KIND, "text": "Der Verantwortliche ist Studio.", "locale": "de"},
        wrong_field="locale",
        stale=_bump,
        state=_state,
        prepare=_drafted,
    ),
}
