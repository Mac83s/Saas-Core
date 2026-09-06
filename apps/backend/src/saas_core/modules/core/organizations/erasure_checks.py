"""Modules register local preconditions; Core never imports an optional module."""

from collections.abc import Callable
from uuid import UUID

_checks: dict[str, Callable[[UUID], None]] = {}


def register_erasure_check(name: str, check: Callable[[UUID], None]) -> None:
    _checks[name] = check


def check_erasure_preconditions(organization_id: UUID) -> None:
    for check in _checks.values():
        check(organization_id)
