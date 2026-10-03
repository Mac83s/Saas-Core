"""A company that pays confirms each change to its billing with a fresh code
from the authenticator app — invoice details, the payment portal, credits —
and its first plan needs none (owner answer 52a; ADR-076, 31b)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from saas_core.modules.core.identity.models import UserMfaMethod
from saas_core.modules.core.identity.step_up import (
    StepUpMfaSetupRequired,
    StepUpRequired,
    activate_step_up,
)
from saas_core.modules.core.organizations.models import BillingProfile
from saas_core.modules.shared.billing.models import (
    BillingSubscription,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.billing.services import (
    create_credit_checkout,
    create_customer_portal,
    update_billing_details,
)
from test_billing_isolation import price_mapping
from test_booking import membership, tenant

pytestmark = pytest.mark.django_db


def _paying(member: Any) -> None:
    now = timezone.now()
    BillingSubscription.all_objects.create(
        organization=member.organization,
        price_mapping=price_mapping(),
        stripe_subscription_id=f"sub_{member.organization.slug}",
        state=SubscriptionState.ACTIVE,
        provider_status=StripeSubscriptionStatus.ACTIVE,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )


def _with_2fa(member: Any) -> None:
    UserMfaMethod.objects.create(
        user_id=member.user_id, secret_ciphertext="x", confirmed_at=timezone.now()
    )


def test_the_first_plan_s_invoice_details_need_no_code() -> None:
    member = membership("pay-first")
    BillingProfile.objects.get_or_create(organization=member.organization)
    with tenant(member):
        profile = update_billing_details(changes={"legal_name": "Studio Pierwsze"})
    assert profile.legal_name == "Studio Pierwsze"


@override_settings(BILLING_PROVIDER="stripe")
@pytest.mark.parametrize(
    "change",
    [
        lambda: update_billing_details(changes={"legal_name": "Studio Płacące"}),
        lambda: create_customer_portal(),
        lambda: create_credit_checkout(pack_key="small", idempotency_key="credits-1"),
    ],
    ids=["details", "portal", "credits"],
)
def test_a_paying_company_confirms_each_billing_change_with_a_code(change: Any) -> None:
    member = membership("pay-code")
    BillingProfile.objects.get_or_create(organization=member.organization)
    _paying(member)

    with tenant(member), pytest.raises(StepUpMfaSetupRequired):
        change()
    _with_2fa(member)
    with tenant(member), pytest.raises(StepUpRequired):
        change()
    # A fresh code lets the change through to its own checks.
    with tenant(member), activate_step_up(int(timezone.now().timestamp())):
        try:
            change()
        except (StepUpRequired, StepUpMfaSetupRequired):  # pragma: no cover
            pytest.fail("a fresh code must be enough")
        except Exception:  # noqa: BLE001 - the change's own checks (provider, packs) may refuse
            pass
