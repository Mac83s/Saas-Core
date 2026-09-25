"""Modules register local preconditions; Core never imports an optional module."""

from collections.abc import Callable
from uuid import UUID

from django.db.models import Model

_checks: dict[str, Callable[[UUID], None]] = {}
_rows: dict[str, tuple[type[Model], str]] = {}


def register_erasure_check(name: str, check: Callable[[UUID], None]) -> None:
    _checks[name] = check


def check_erasure_preconditions(organization_id: UUID) -> None:
    for check in _checks.values():
        check(organization_id)


def register_erasure_rows(name: str, model: type[Model], column: str) -> None:
    """A table that names its organization in a plain column, not a foreign key.

    Routing indexes read before the tenant is known (a public slug, a token
    digest, a reminder due time) keep `organization_id` as a bare UUID, so the
    discovery by foreign key never sees them and they outlived every erasure.
    """
    _rows[name] = (model, column)


def registered_erasure_rows() -> list[tuple[type[Model], str]]:
    return list(_rows.values())
