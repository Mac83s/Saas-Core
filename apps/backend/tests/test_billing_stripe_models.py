from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    MissingTenantContext,
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import BillingProfile, Organization
from saas_core.modules.shared.billing.models import (
    BillingSubscription,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    StripeWebhookEvent,
    SubscriptionState,
)

pytestmark = pytest.mark.django_db


def organization(slug: str) -> Organization:
    return Organization.objects.create(name=slug, slug=slug)


def tenant_context(tenant: Organization) -> TenantContext:
    actor = User.objects.create_user(email=f"{tenant.slug}@example.com")
    return TenantContext(
        organization_id=tenant.id,
        membership_id=uuid.uuid7(),
        actor_id=actor.id,
        role_key="owner",
        permissions=frozenset({"organization.billing.manage"}),
    )


def price_mapping(*, plan_key: str = "starter", suffix: str = "starter") -> StripePriceMapping:
    return StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key=plan_key, version=1),
        stripe_product_id=f"prod_{suffix}",
        stripe_price_id=f"price_{suffix}",
        livemode=False,
    )


def subscription(
    tenant: Organization,
    mapping: StripePriceMapping,
    *,
    suffix: str,
    state: SubscriptionState = SubscriptionState.ACTIVE,
) -> BillingSubscription:
    return BillingSubscription.all_objects.create(
        organization=tenant,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{suffix}",
        state=state,
        provider_status=StripeSubscriptionStatus.ACTIVE,
    )


def test_external_customer_maps_to_only_one_organization() -> None:
    first = organization("stripe-customer-one")
    second = organization("stripe-customer-two")
    BillingProfile.objects.create(organization=first, external_customer_id="cus_shared")

    with pytest.raises(IntegrityError), transaction.atomic():
        BillingProfile.objects.create(organization=second, external_customer_id="cus_shared")

    BillingProfile.objects.create(organization=second, external_customer_id="")


def test_only_one_active_price_mapping_exists_per_plan_version_and_mode() -> None:
    first = price_mapping()

    with pytest.raises(IntegrityError), transaction.atomic():
        StripePriceMapping.objects.create(
            plan_version=first.plan_version,
            stripe_product_id="prod_duplicate",
            stripe_price_id="price_duplicate",
            livemode=False,
        )

    StripePriceMapping.objects.filter(pk=first.pk).update(is_active=False)
    replacement = StripePriceMapping.objects.create(
        plan_version=first.plan_version,
        stripe_product_id="prod_replacement",
        stripe_price_id="price_replacement",
        livemode=False,
    )
    assert replacement.is_active is True


def test_subscription_is_tenant_scoped_and_only_one_current_is_allowed() -> None:
    tenant = organization("stripe-subscription")
    mapping = price_mapping()
    current = subscription(tenant, mapping, suffix="current")

    with pytest.raises(MissingTenantContext):
        BillingSubscription.objects.count()
    with activate_tenant_context(tenant_context(tenant)):
        assert BillingSubscription.objects.get() == current
    with pytest.raises(IntegrityError), transaction.atomic():
        subscription(tenant, mapping, suffix="duplicate")

    current.state = SubscriptionState.CANCELED
    current.provider_status = StripeSubscriptionStatus.CANCELED
    current.save(update_fields=["state", "provider_status", "updated_at"])
    replacement = subscription(tenant, mapping, suffix="replacement")
    assert replacement.state == SubscriptionState.ACTIVE


def test_subscription_rejects_partial_or_reversed_provider_windows() -> None:
    tenant = organization("stripe-windows")
    mapping = price_mapping()
    now = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        BillingSubscription.all_objects.create(
            organization=tenant,
            price_mapping=mapping,
            stripe_subscription_id="sub_partial_period",
            provider_status=StripeSubscriptionStatus.TRIALING,
            current_period_start=now,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        BillingSubscription.all_objects.create(
            organization=tenant,
            price_mapping=mapping,
            stripe_subscription_id="sub_reversed_trial",
            provider_status=StripeSubscriptionStatus.TRIALING,
            trial_start=now,
            trial_end=now - timedelta(seconds=1),
        )


def test_webhook_inbox_deduplicates_stripe_event_id() -> None:
    received = timezone.now()
    StripeWebhookEvent.objects.create(
        stripe_event_id="evt_checkout_completed",
        event_type="checkout.session.completed",
        api_version="2026-02-25.clover",
        livemode=False,
        provider_created_at=received,
        payload={"id": "evt_checkout_completed", "object": "event"},
        signature_verified_at=received,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        StripeWebhookEvent.objects.create(
            stripe_event_id="evt_checkout_completed",
            event_type="checkout.session.completed",
            livemode=False,
            provider_created_at=received,
            payload={"id": "evt_checkout_completed", "object": "event"},
            signature_verified_at=received,
        )
