"""What an organization's own work may be signed as (ADR-073 §5).

A `service` contract is work the organization owes on its own account — a
customer's reminder, a payment's deadline, a mail to the people on a visit —
not on a person's. Each module says from its `AppConfig.ready` which role its
work is signed with and what that role may carry: core knows no module's
names. A contract whose role nobody registered, or that carries more than the
role allows, is refused when the task runs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class ServiceScope:
    role_key: str
    permissions: frozenset[str]
    #: The contract carries exactly these — a job with one purpose — rather
    #: than any part of them.
    exact: bool = False

    def allows(self, permissions: Iterable[str]) -> bool:
        carried = frozenset(permissions)
        return carried == self.permissions if self.exact else carried <= self.permissions


_scopes: dict[str, ServiceScope] = {}


def register_service_scope(
    role_key: str, permissions: Iterable[str] = (), *, exact: bool = False
) -> None:
    """Declares `role_key` as a role of the organization's own work, allowed
    to carry `permissions`. A second module may add its own permission to a
    scope another module declared (a customer's public link that also pays);
    a scope declared `exact` takes no additions, because the contracts already
    signed carry the first set."""
    added = frozenset(permissions)
    existing = _scopes.get(role_key)
    if existing is None:
        _scopes[role_key] = ServiceScope(role_key, added, exact)
        return
    if (existing.exact or exact) and (added != existing.permissions or exact != existing.exact):
        raise ImproperlyConfigured(
            f"Zakres usługowy {role_key!r} jest zamknięty: nie przyjmuje innych uprawnień."
        )
    _scopes[role_key] = ServiceScope(role_key, existing.permissions | added, existing.exact)


def service_scope(role_key: str) -> ServiceScope | None:
    return _scopes.get(role_key)
