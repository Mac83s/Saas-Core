"""The pricing page reads its prices from billing, before anyone signs in."""

from __future__ import annotations

import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_a_visitor_sees_the_profiles_public_plans_without_a_session() -> None:
    from saas_core.modules.shared.billing.plan_offer import (  # noqa: PLC0415
        plan_keys_for_type,
    )

    response = APIClient().get("/api/v1/billing/plans/")

    assert response.status_code == 200
    # Gość widzi plany typu domyślnego, a nie wszystkie plany profilu: produkt
    # z kilkoma typami organizacji sprzedaje każdemu z nich co innego.
    assert [plan["key"] for plan in response.data] == list(
        plan_keys_for_type(settings.DEFAULT_ORGANIZATION_TYPE)
    )
    for plan in response.data:
        # Zero jest poprawną ceną: plan darmowy nadaje się przy zakładaniu
        # organizacji i nie ma czego w nim kupować.
        assert plan["unit_amount_minor"] >= 0
        assert plan["currency"]


def test_the_catalogue_says_nothing_about_any_organization() -> None:
    """Organization-shaped fields belong to the authenticated overview only."""
    response = APIClient().get("/api/v1/billing/plans/")

    for plan in response.data:
        assert not {"is_current", "checkout_available", "subscription"} & set(plan)
