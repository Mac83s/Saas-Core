"""The pricing page reads its prices from billing, before anyone signs in."""

from __future__ import annotations

import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_a_visitor_sees_the_profiles_public_plans_without_a_session() -> None:
    response = APIClient().get("/api/v1/billing/plans/")

    assert response.status_code == 200
    assert [plan["key"] for plan in response.data] == list(settings.BILLING_PLAN_KEYS)
    for plan in response.data:
        assert plan["unit_amount_minor"] > 0
        assert plan["currency"]


def test_the_catalogue_says_nothing_about_any_organization() -> None:
    """Organization-shaped fields belong to the authenticated overview only."""
    response = APIClient().get("/api/v1/billing/plans/")

    for plan in response.data:
        assert not {"is_current", "checkout_available", "subscription"} & set(plan)
