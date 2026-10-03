"""What the eval battery (`test_command_evals.py`) needs to know about each
registered command (ADR-076 §1).

Every command has an entry: valid arguments, wrong ones and the field they are
refused on, how to move what its preview read so a consent goes stale, and
what to compare to prove another company was left alone. A case that does not
apply says why, in words. A command without an entry fails the battery: an
assistant tool nobody evaluated is not offered to a model.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from saas_core.modules.core.organizations.context import TenantContext


@dataclass(frozen=True)
class CommandEval:
    arguments: Callable[[TenantContext], dict[str, Any]]
    #: Or made for the company, when the wrong value needs its real ids.
    wrong_arguments: dict[str, Any] | Callable[[TenantContext], dict[str, Any]]
    wrong_field: str
    #: Moves what the preview read, or why nothing can go stale.
    stale: Callable[[TenantContext], None] | str
    #: What a run in another company must leave as it was.
    state: Callable[[TenantContext], Any]
    #: What the company needs before the command means anything — a plan with
    #: the module, a place, a person.
    prepare: Callable[[TenantContext], None] = lambda _context: None
    #: Why the preview runs the write itself in a savepoint it rolls back
    #: (ADR-072 §11); the battery then checks that nothing stayed, not that
    #: nothing ran.
    preview_rolls_back: str = ""
    #: Process-wide setup `prepare` cannot express — a source in a registry, a
    #: model the port may call — entered around the whole test. It must put
    #: back everything it changed: the next command's evals run in the same
    #: process.
    around: Callable[[], AbstractContextManager[None]] | None = None


def all_evals() -> dict[str, CommandEval]:
    from django.conf import settings  # noqa: PLC0415

    from . import booking, company_settings, organization, profiles, sites  # noqa: PLC0415

    evals = {
        **organization.EVALS,
        **booking.EVALS,
        **company_settings.EVALS,
        **profiles.EVALS,
        **sites.EVALS,
    }
    # A profile without the translation module (HoofCare, MedPlano) registers
    # none of its commands, and its models cannot even be imported there.
    if "shared.translation" in settings.ACTIVE_MODULES:
        from . import translation  # noqa: PLC0415

        evals |= translation.EVALS
    return evals
