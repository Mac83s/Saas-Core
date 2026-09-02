"""Billing under forced row-level security (ADR-039, billing.0013).

Two things have to hold at once. The database must refuse to show one
company's subscription to another — that is the point of the policies. And the
background work must keep running, because a sweep that used to ask for every
organization's rows in one query now gets nothing back unless it walks
organizations one at a time. The first is checked under a role that cannot
bypass RLS, since the test database connects as the table owner and would
never notice a missing policy; the second is checked by making two
organizations due at once and expecting both to be handled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import override_settings

from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.lifecycle import (
    process_due_lifecycle_actions,
    sync_subscription_lifecycle,
)
from saas_core.modules.shared.billing.models import (
    BillingLifecycleAction,
    BillingSubscription,
    LifecycleActionStatus,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.billing.tenant_scope import (
    billing_organization_ids,
    billing_tenant_scope,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


def price_mapping() -> StripePriceMapping:
    """One active Price per plan and mode, shared the way real customers share it."""
    mapping, _ = StripePriceMapping.objects.get_or_create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        livemode=False,
        defaults={
            "stripe_product_id": "prod_isolation",
            "stripe_price_id": "price_isolation",
        },
    )
    return mapping


def trialing_subscription(slug: str) -> BillingSubscription:
    organization = Organization.objects.create(name=slug, slug=slug)
    mapping = price_mapping()
    return BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{slug}",
        state=SubscriptionState.TRIALING,
        provider_status=StripeSubscriptionStatus.TRIALING,
        trial_start=NOW,
        trial_end=NOW + timedelta(days=3),
    )


@override_settings(BILLING_LIFECYCLE_WARNING_LEAD_SECONDS=86400)
def test_a_sweep_still_reaches_every_organization_that_has_work() -> None:
    """The regression the policies could have caused: work silently skipped."""
    first = trialing_subscription("sweep-one")
    second = trialing_subscription("sweep-two")
    sync_subscription_lifecycle(first)
    sync_subscription_lifecycle(second)
    due_at = NOW + timedelta(days=2)

    assert process_due_lifecycle_actions(at=due_at) == 2
    assert process_due_lifecycle_actions(at=due_at) == 0
    for item in (first, second):
        action = BillingLifecycleAction.all_objects.get(subscription=item)
        assert action.status == LifecycleActionStatus.PROCESSED


@override_settings(BILLING_LIFECYCLE_WARNING_LEAD_SECONDS=86400)
def test_a_sweep_limit_counts_work_not_organizations() -> None:
    for slug in ("limit-one", "limit-two"):
        sync_subscription_lifecycle(trialing_subscription(slug))
    due_at = NOW + timedelta(days=2)

    assert process_due_lifecycle_actions(at=due_at, limit=1) == 1
    assert process_due_lifecycle_actions(at=due_at, limit=1) == 1
    assert process_due_lifecycle_actions(at=due_at, limit=1) == 0


def test_the_sweep_index_lists_organizations_without_a_billing_profile() -> None:
    """An organization created outside the billing flow still gets swept.

    BillingProfile exists only for organizations created through the
    onboarding service, so using it as the index would quietly drop the rest.
    """
    organization = Organization.objects.create(name="no-profile", slug="no-profile")

    assert organization.id in billing_organization_ids()


def test_another_organizations_subscription_is_invisible_under_the_app_role() -> None:
    mine = trialing_subscription("rls-mine")
    theirs = trialing_subscription("rls-theirs")

    role_name = f"billing_rls_{uuid7().hex}"
    quoted_role = connection.ops.quote_name(role_name)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {quoted_role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
        cursor.execute(f"GRANT SELECT ON billing_billingsubscription TO {quoted_role}")
        cursor.execute(f"SET LOCAL ROLE {quoted_role}")

        cursor.execute("SET LOCAL app.organization_id = ''")
        cursor.execute("SELECT COUNT(*) FROM billing_billingsubscription")
        assert cursor.fetchone()[0] == 0

        cursor.execute("SET LOCAL app.organization_id = %s", [str(mine.organization_id)])
        cursor.execute("SELECT id FROM billing_billingsubscription")
        visible = {row[0] for row in cursor.fetchall()}
        assert visible == {mine.id}
        assert theirs.id not in visible

        cursor.execute("RESET ROLE")


def test_a_lifecycle_action_cannot_name_another_organizations_subscription() -> None:
    """The policy checks the row's own tenant; the trigger checks its parents.

    A foreign key is verified by the system whatever row-level security says,
    so without the guard a row could claim this organization while pointing at
    somebody else's subscription.
    """
    mine = trialing_subscription("guard-mine")
    theirs = trialing_subscription("guard-theirs")

    with pytest.raises(DatabaseError), transaction.atomic():
        BillingLifecycleAction.all_objects.create(
            organization_id=mine.organization_id,
            subscription=theirs,
            action_type="trial_ending_notice",
            due_at=NOW,
        )


def test_the_scope_refuses_to_run_outside_a_transaction() -> None:
    """SET LOCAL only lives inside one; silently doing nothing would be worse."""
    identifiers: list[Any] = billing_organization_ids(limit=1)
    organization_id = identifiers[0] if identifiers else uuid7()

    with billing_tenant_scope(organization_id):
        assert connection.in_atomic_block
