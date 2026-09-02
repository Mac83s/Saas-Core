"""Running billing background work inside one organization (ADR-039).

The sweeps and the Stripe webhook processor have no request and no member
behind them, so nothing sets ``app.organization_id`` on their connection. Under
forced row-level security a read taken before that setting answers with no rows
instead of failing, which is the failure mode that has already taken this
product down twice. Every background path therefore resolves its organization
first — from a table that carries no RLS (``BillingProfile``,
``StripeWebhookEvent``) or from the task payload — and only then works inside
the scope below.

A sweep is a loop over organizations rather than one query across all of them.
That costs a query per organization even when nothing is due, which is the
price of the second layer; reconciliation has to visit every subscription
anyway, so the batch that dominates the cost was already shaped this way.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.db import transaction

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.models import BillingProfile, Organization


@contextmanager
def billing_tenant_scope(organization_id: UUID | Any) -> Iterator[None]:
    """Opens a transaction that can see one organization's billing rows."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        yield


def billing_organization_ids(*, limit: int | None = None) -> list[UUID]:
    """Organizations a sweep may have work for, read without a tenant.

    ``Organization`` is the tenant itself rather than tenant data, so it
    carries no RLS and is the one list a background job can obtain before it
    knows which tenant it is working for. Deliberately unfiltered by status:
    a suspended organization is exactly the one whose grace period is about to
    expire, and narrowing the list would quietly drop that work.
    """
    identifiers = Organization.objects.order_by("created_at", "id").values_list("id", flat=True)
    if limit is not None:
        identifiers = identifiers[:limit]
    return list(identifiers)


def organization_id_for_customer(external_customer_id: str) -> UUID | None:
    """Maps a provider customer to a tenant before any tenant row is read."""
    return (
        BillingProfile.objects.filter(external_customer_id=external_customer_id)
        .values_list("organization_id", flat=True)
        .first()
    )
