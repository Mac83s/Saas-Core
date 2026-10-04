"""Which customers the caller sees on orders (ADR-076, uzupełnienie 2026-10-04
„karty osób”): whoever reads the company's orders reads their buyers — the
name, the e-mail and the phone on the order's page — and nobody else does.
Said to `shared.customers` for the cards the assistant's conversation shows.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from django.db.models import F
from rest_framework.exceptions import APIException

from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.billing.decisions import FeatureOperation
from saas_core.modules.shared.customers.api import Sight

from .models import Order
from .names import COMMERCE_ENABLED, ORDERS_READ


def buyers_of_orders(ids: Sequence[UUID]) -> dict[UUID, Sight]:
    try:
        context = authorize_entitled(ORDERS_READ, COMMERCE_ENABLED, operation=FeatureOperation.READ)
    except APIException:
        return {}
    seen: dict[UUID, Sight] = {}
    # Oldest first, so each buyer ends with the newest of their orders.
    for order_id, customer_id, number in (
        Order.all_objects.filter(organization_id=context.organization_id, customer_id__in=list(ids))
        .order_by(F("placed_at").asc(nulls_first=True), "id")
        .values_list("id", "customer_id", "number")
    ):
        title = (
            {"pl": f"Zamówienie {number}", "en": f"Order {number}"}
            if number
            else {"pl": "Zamówienie", "en": "The order"}
        )
        seen[customer_id] = Sight(
            contact=True, links=({"title": title, "href": f"/panel/orders/{order_id}"},)
        )
    return seen
