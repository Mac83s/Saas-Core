"""What billing does when something happens elsewhere in the platform."""

from __future__ import annotations

from typing import Any

from saas_core.modules.core.organizations.models import Organization

from .snapshots import grant_free_plan


def grant_free_plan_on_create(
    sender: type[Organization], instance: Organization, created: bool, **kwargs: Any
) -> None:
    """A new organization starts on the free plan of its type, if it has one.

    In the caller's transaction, not after commit: `create_organization` sets
    the tenant with `SET LOCAL` before it saves, and that setting dies with the
    transaction — a callback running after commit would write the snapshot with
    no tenant at all, which the policy on the table rejects (and which the test
    database, connecting as the owner, would happily accept).
    """
    if not created:
        return
    grant_free_plan(instance)
