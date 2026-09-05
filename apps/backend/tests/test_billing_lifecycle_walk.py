"""One customer, from the first plan to the second, in order.

Every payment defect found on 3–4 September sat on a seam between two pieces
that each had green tests of their own: the redirect and the activation, the
activation and a second purchase, the catalog and the provider. A test per
piece cannot see a seam. This one walks the whole road — trial, first payment,
a failed payment, the grace period running out, paying again, changing plan,
cancelling, and coming back — and checks what the customer would have at each
stop.

It deliberately uses the webhook path rather than the panel, because that is
what production runs on: the browser coming back is a convenience, not the
mechanism.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.test import override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Organization,
)
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing import lifecycle, services
from saas_core.modules.shared.billing.lifecycle import process_due_lifecycle_actions
from saas_core.modules.shared.billing.models import (
    AccessMode,
    BillingSubscription,
    CheckoutStatus,
    EntitlementSnapshot,
    Plan,
    StripePriceMapping,
    StripeSubscriptionStatus,
    StripeWebhookEvent,
    SubscriptionState,
    WebhookProcessingStatus,
)
from saas_core.modules.shared.billing.processor import process_stripe_event
from saas_core.modules.shared.billing.provider import (
    ProviderCheckout,
    ProviderCustomer,
    ProviderSubscription,
)
from saas_core.modules.shared.billing.services import create_setup_checkout

pytestmark = pytest.mark.django_db

CUSTOMER = "cus_walk"
SUBSCRIPTION = "sub_walk"
DAY = 86_400
# A readable clock: every step names its own day, so a wrong order shows up as a
# date rather than as a silently reordered assertion.
SIGNED_UP = 1_786_000_000
TRIAL_ENDS = SIGNED_UP + 3 * DAY
PAYMENT_FAILS = TRIAL_ENDS + 30 * DAY
GRACE_ENDS = PAYMENT_FAILS + 7 * DAY
PAID_AGAIN = GRACE_ENDS + DAY
UPGRADED = PAID_AGAIN + DAY
CANCELED = UPGRADED + 5 * DAY
PERIOD_ENDS = CANCELED + 20 * DAY
COMES_BACK = PERIOD_ENDS + 40 * DAY


def moment(stamp: int) -> datetime:
    return datetime.fromtimestamp(stamp, tz=UTC)


class WalkProvider:
    """Stripe as far as this walk needs it: it opens sessions and starts plans."""

    def __init__(self) -> None:
        self.subscriptions: list[dict[str, Any]] = []
        self.sessions = 0

    def create_customer(self, **_kwargs: Any) -> ProviderCustomer:
        return ProviderCustomer(CUSTOMER)

    def create_setup_checkout(self, **_kwargs: Any) -> ProviderCheckout:
        self.sessions += 1
        return ProviderCheckout(
            f"cs_walk_{self.sessions}",
            f"https://checkout.stripe.test/cs_walk_{self.sessions}",
            None,
        )

    def create_subscription(self, **kwargs: Any) -> ProviderSubscription:
        self.subscriptions.append(kwargs)
        if kwargs["trial_days"] == 0:
            started = moment(COMES_BACK)
            return ProviderSubscription(
                id=f"{SUBSCRIPTION}_again",
                status=StripeSubscriptionStatus.ACTIVE,
                trial_start=None,
                trial_end=None,
                current_period_start=started,
                current_period_end=started + timedelta(days=30),
            )
        return ProviderSubscription(
            id=SUBSCRIPTION,
            status=StripeSubscriptionStatus.TRIALING,
            trial_start=moment(SIGNED_UP),
            trial_end=moment(TRIAL_ENDS),
            current_period_start=moment(SIGNED_UP),
            current_period_end=moment(TRIAL_ENDS),
        )


def customer_ready() -> tuple[Organization, TenantContext, dict[str, StripePriceMapping]]:
    organization = Organization.objects.create(name="walk", slug="walk")
    BillingProfile.objects.create(
        organization=organization,
        legal_name="Firma w drodze",
        billing_email="faktury@example.com",
        country_code="PL",
        address_line1="Testowa 1",
        postal_code="00-001",
        city="Warszawa",
    )
    actor = User.objects.create_user(email="walk@example.com")
    context = TenantContext(
        organization_id=organization.id,
        membership_id=actor.id,
        actor_id=actor.id,
        role_key="owner",
        permissions=frozenset({BILLING_MANAGE}),
    )
    prices = {
        key: StripePriceMapping.objects.create(
            plan_version=Plan.objects.get(key=key).current_version,
            stripe_product_id=f"prod_walk_{key}",
            stripe_price_id=f"price_walk_{key}",
            livemode=False,
        )
        for key in ("starter", "pro")
    }
    return organization, context, prices


def deliver(
    *,
    event_id: str,
    event_type: str,
    created: int,
    data_object: dict[str, Any],
) -> StripeWebhookEvent:
    event = StripeWebhookEvent.objects.create(
        stripe_event_id=event_id,
        event_type=event_type,
        api_version="2026-07-29.dahlia",
        livemode=False,
        provider_created_at=moment(created),
        payload={
            "id": event_id,
            "object": "event",
            "api_version": "2026-07-29.dahlia",
            "created": created,
            "data": {"object": data_object},
            "livemode": False,
            "type": event_type,
        },
        signature_verified_at=moment(created),
    )
    processed = process_stripe_event(event.id)
    assert processed is not None
    assert processed.status == WebhookProcessingStatus.PROCESSED, processed.processing_error
    return processed


def subscription_payload(
    *,
    status: str,
    price_id: str,
    period_start: int,
    period_end: int,
    subscription_id: str = SUBSCRIPTION,
    cancel_at_period_end: bool = False,
    trial: tuple[int, int] | None = None,
) -> dict[str, Any]:
    return {
        "id": subscription_id,
        "object": "subscription",
        "customer": CUSTOMER,
        "status": status,
        "items": {
            "data": [
                {
                    "id": "si_walk",
                    "price": {"id": price_id, "object": "price"},
                    "current_period_start": period_start,
                    "current_period_end": period_end,
                }
            ]
        },
        "trial_start": trial[0] if trial else None,
        "trial_end": trial[1] if trial else None,
        "cancel_at_period_end": cancel_at_period_end,
        "canceled_at": None,
        "ended_at": None,
    }


def invoice_payload(*, amount: int = 14_900) -> dict[str, Any]:
    return {
        "id": "in_walk",
        "object": "invoice",
        "customer": CUSTOMER,
        "subscription": SUBSCRIPTION,
        "amount_paid": amount,
        "amount_due": amount,
        "currency": "pln",
        "parent": {"subscription_details": {"subscription": SUBSCRIPTION}},
    }


def access(organization: Organization) -> tuple[str, str, str]:
    snapshot = EntitlementSnapshot.all_objects.select_related("plan_version__plan").get(
        organization=organization
    )
    return (
        snapshot.subscription_state,
        snapshot.access_mode,
        snapshot.plan_version.plan.key,
    )


@override_settings(
    BILLING_PROVIDER="stripe",
    STRIPE_LIVEMODE=False,
    BILLING_PLAN_KEYS=("profile", "starter", "pro"),
    BILLING_LIFECYCLE_WARNING_LEAD_SECONDS=86_400,
)
def test_a_customer_walks_the_whole_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    organization, context, prices = customer_ready()
    provider = WalkProvider()
    monkeypatch.setattr(services, "get_billing_provider", lambda: provider)
    monkeypatch.setattr(lifecycle, "get_billing_provider", lambda: provider)

    # 1. Chooses a plan. Nothing is owed yet and nothing is granted yet.
    with activate_tenant_context(context):
        checkout = create_setup_checkout(plan_key="starter", idempotency_key="walk-one")
    assert checkout.checkout.status == CheckoutStatus.OPEN
    assert not EntitlementSnapshot.all_objects.filter(organization=organization).exists()

    # 2. Pays. The event starts the plan — the browser is not involved.
    deliver(
        event_id="evt_walk_checkout",
        event_type="checkout.session.completed",
        created=SIGNED_UP,
        data_object={
            "id": checkout.checkout.stripe_checkout_session_id,
            "object": "checkout.session",
            "customer": CUSTOMER,
            "setup_intent": "seti_walk",
            "metadata": {
                "saas_core_organization_id": str(organization.id),
                "saas_core_plan_version_id": str(prices["starter"].plan_version_id),
                "saas_core_price_mapping_id": str(prices["starter"].id),
            },
        },
    )
    assert access(organization) == (
        SubscriptionState.TRIALING,
        AccessMode.FULL,
        "starter",
    )

    # 3. The trial ends and the first payment goes through.
    deliver(
        event_id="evt_walk_active",
        event_type="customer.subscription.updated",
        created=TRIAL_ENDS,
        data_object=subscription_payload(
            status=StripeSubscriptionStatus.ACTIVE,
            price_id=prices["starter"].stripe_price_id,
            period_start=TRIAL_ENDS,
            period_end=TRIAL_ENDS + 30 * DAY,
        ),
    )
    assert access(organization) == (SubscriptionState.ACTIVE, AccessMode.FULL, "starter")

    # 4. A month later the card fails. Nothing is taken away yet.
    deliver(
        event_id="evt_walk_failed",
        event_type="invoice.payment_failed",
        created=PAYMENT_FAILS,
        data_object=invoice_payload(),
    )
    assert access(organization) == (
        SubscriptionState.GRACE_PERIOD,
        AccessMode.FULL,
        "starter",
    )

    # 5. The grace period runs out with nobody paying: read-only, data intact.
    assert process_due_lifecycle_actions(at=moment(GRACE_ENDS) + timedelta(minutes=1)) >= 1
    assert access(organization) == (
        SubscriptionState.READ_ONLY,
        AccessMode.READ_ONLY,
        "starter",
    )

    # 6. They pay. Full access comes back.
    deliver(
        event_id="evt_walk_paid",
        event_type="invoice.paid",
        created=PAID_AGAIN,
        data_object=invoice_payload(),
    )
    assert access(organization) == (SubscriptionState.ACTIVE, AccessMode.FULL, "starter")

    # 7. They upgrade in the portal. The plan and its limits move with them.
    deliver(
        event_id="evt_walk_upgrade",
        event_type="customer.subscription.updated",
        created=UPGRADED,
        data_object=subscription_payload(
            status=StripeSubscriptionStatus.ACTIVE,
            price_id=prices["pro"].stripe_price_id,
            period_start=UPGRADED,
            period_end=PERIOD_ENDS,
        ),
    )
    assert access(organization) == (SubscriptionState.ACTIVE, AccessMode.FULL, "pro")
    snapshot = EntitlementSnapshot.all_objects.get(organization=organization)
    assert snapshot.quotas["sites.max"] == 3

    # 8. They cancel. The days already paid for stay theirs.
    deliver(
        event_id="evt_walk_cancel",
        event_type="customer.subscription.updated",
        created=CANCELED,
        data_object=subscription_payload(
            status=StripeSubscriptionStatus.ACTIVE,
            price_id=prices["pro"].stripe_price_id,
            period_start=UPGRADED,
            period_end=PERIOD_ENDS,
            cancel_at_period_end=True,
        ),
    )
    assert access(organization) == (SubscriptionState.ACTIVE, AccessMode.FULL, "pro")

    # 9. The paid period ends.
    assert process_due_lifecycle_actions(at=moment(PERIOD_ENDS) + timedelta(minutes=1)) >= 1
    state, mode, _plan = access(organization)
    assert state == SubscriptionState.CANCELED
    assert mode != AccessMode.FULL

    # 10. Months later they come back. A second free trial is not owed.
    with activate_tenant_context(context):
        again = create_setup_checkout(plan_key="pro", idempotency_key="walk-two")
    deliver(
        event_id="evt_walk_return",
        event_type="checkout.session.completed",
        created=COMES_BACK,
        data_object={
            "id": again.checkout.stripe_checkout_session_id,
            "object": "checkout.session",
            "customer": CUSTOMER,
            "setup_intent": "seti_walk_again",
            "metadata": {
                "saas_core_organization_id": str(organization.id),
                "saas_core_plan_version_id": str(prices["pro"].plan_version_id),
                "saas_core_price_mapping_id": str(prices["pro"].id),
            },
        },
    )

    assert provider.subscriptions[0]["trial_days"] == 3
    assert provider.subscriptions[1]["trial_days"] == 0
    assert access(organization) == (SubscriptionState.ACTIVE, AccessMode.FULL, "pro")
    assert (
        BillingSubscription.all_objects.filter(organization=organization)
        .exclude(state=SubscriptionState.CANCELED)
        .count()
        == 1
    )
