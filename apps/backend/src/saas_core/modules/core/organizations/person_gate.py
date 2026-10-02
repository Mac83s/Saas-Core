"""Decisions only a person makes (ADR-035 §4, ADR-076 §6, ADR-078 pkt 8).

Moved here from `shared.sites` with the first settings that need it — the
company's languages — because the settings live in the core and the core does
not import shared modules; `shared.sites` re-exports both names.
"""

from __future__ import annotations

from rest_framework.exceptions import APIException

from .audit import PANEL_PRINCIPAL
from .context import ACTING_PERSON_GATE_ALLOWED, TenantContext


class PersonRequired(APIException):
    status_code = 403
    default_detail = "Ta operacja wymaga decyzji człowieka."
    default_code = "person_required"


def assert_person_required(context: TenantContext, what: str) -> None:
    """Refuses an automation outright, with the reason in the message.

    These are the operations ADR-035 §4 keeps for a person no matter which mode
    the grant carries: domains, the main menu, legal pages, the price list,
    removals and anything site-wide. A grant is a limit on what an integration
    may do routinely, not a way of buying past the short list of things nobody
    wants a machine deciding alone.
    """
    # A membership acting through the assistant or a translation job is
    # refused too, unless a person's consent opened this label for this run,
    # within what its channel may ever reach (ADR-076 §6).
    opened = ACTING_PERSON_GATE_ALLOWED.get(context.acting_via, frozenset()) & context.acting_opened
    if context.principal_kind == PANEL_PRINCIPAL and (not context.acting_via or what in opened):
        return
    raise PersonRequired(detail=f"{what} wymaga decyzji człowieka.")
