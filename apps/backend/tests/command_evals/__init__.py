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
from dataclasses import dataclass
from typing import Any

from saas_core.modules.core.organizations.context import TenantContext


@dataclass(frozen=True)
class CommandEval:
    arguments: Callable[[TenantContext], dict[str, Any]]
    wrong_arguments: dict[str, Any]
    wrong_field: str
    #: Moves what the preview read, or why nothing can go stale.
    stale: Callable[[TenantContext], None] | str
    #: What a run in another company must leave as it was.
    state: Callable[[TenantContext], Any]


def all_evals() -> dict[str, CommandEval]:
    from . import organization  # noqa: PLC0415

    return {**organization.EVALS}
