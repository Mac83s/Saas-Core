"""The warning that used to be written and never sent.

`BillingNotice` had a `delivered_at` column and nothing ever set it: a trial
ending was recorded in the database and reached nobody. These tests pin the two
halves of the fix — the message inside the product, for the people who can act
on it, and the e-mail for the days they are not looking — and the rule that
delivering twice must not tell anybody twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import (
    BillingProfile,
    Membership,
    Organization,
    Role,
)
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing.models import (
    BillingLifecycleAction,
    BillingNotice,
    BillingNoticeType,
    BillingSubscription,
    LifecycleActionType,
    PlanVersion,
    StripePriceMapping,
    StripeSubscriptionStatus,
    SubscriptionState,
)
from saas_core.modules.shared.notifications.billing_notices import deliver_billing_notices
from saas_core.modules.shared.notifications.models import (
    AppNotification,
    NotificationMessage,
    NotificationSeverity,
)
from saas_core.modules.shared.notifications.services import (
    list_app_notifications,
    mark_app_notifications_read,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
ENDS_AT = NOW + timedelta(days=1)


def tenant_with_notice(
    *,
    slug: str = "notice",
    notice_type: str = BillingNoticeType.TRIAL_ENDING,
) -> tuple[Organization, User, User, BillingNotice]:
    """An organization with somebody who pays the bills and somebody who does not."""
    organization = Organization.objects.create(name=slug, slug=slug)
    BillingProfile.objects.create(organization=organization, external_customer_id=f"cus_{slug}")
    owner = User.objects.create_user(email=f"{slug}-owner@example.com")
    member = User.objects.create_user(email=f"{slug}-member@example.com")
    Membership.objects.create(
        organization=organization,
        user=owner,
        role=Role.objects.get(key="owner", organization=None, organization_type=""),
    )
    Membership.objects.create(
        organization=organization,
        user=member,
        role=Role.objects.get(key="staff", organization=None, organization_type=""),
    )
    mapping = StripePriceMapping.objects.create(
        plan_version=PlanVersion.objects.get(plan__key="starter", version=1),
        stripe_product_id=f"prod_{slug}",
        stripe_price_id=f"price_{slug}",
        livemode=False,
    )
    subscription = BillingSubscription.all_objects.create(
        organization=organization,
        price_mapping=mapping,
        stripe_subscription_id=f"sub_{slug}",
        state=SubscriptionState.TRIALING,
        provider_status=StripeSubscriptionStatus.TRIALING,
        trial_start=NOW,
        trial_end=ENDS_AT,
        current_period_start=NOW,
        current_period_end=ENDS_AT,
    )
    action = BillingLifecycleAction.all_objects.create(
        organization=organization,
        subscription=subscription,
        action_type=LifecycleActionType.TRIAL_ENDING_NOTICE,
        due_at=NOW,
    )
    notice = BillingNotice.all_objects.create(
        organization=organization,
        lifecycle_action=action,
        subscription=subscription,
        notice_type=notice_type,
        payload={
            "subscription_id": str(subscription.id),
            "notice_type": notice_type,
            "ends_at": ENDS_AT.isoformat(),
        },
    )
    return organization, owner, member, notice


def context_for(organization: Organization, user: User) -> TenantContext:
    return TenantContext(
        organization_id=organization.id,
        membership_id=uuid.uuid7(),
        actor_id=user.id,
        role_key="owner",
        permissions=frozenset({BILLING_MANAGE}),
    )


@override_settings(NOTIFICATIONS_RETENTION_DAYS=30)
def test_a_notice_reaches_the_people_who_can_act_on_it() -> None:
    organization, owner, member, notice = tenant_with_notice()

    assert deliver_billing_notices(at=NOW) == 1

    notice.refresh_from_db()
    assert notice.delivered_at == NOW
    inbox = AppNotification.all_objects.filter(organization=organization)
    assert [row.user_id for row in inbox] == [owner.id]
    entry = inbox.get()
    assert entry.kind == "billing.trial_ending"
    assert entry.severity == NotificationSeverity.WARNING
    assert entry.payload["plan_name"] and entry.payload["ends_at"] == "2026-09-06"
    assert entry.read_at is None
    # The staff member cannot change a plan, so a warning about one is noise.
    assert not AppNotification.all_objects.filter(user=member).exists()
    email = NotificationMessage.all_objects.get(organization=organization)
    assert email.recipient_email == owner.email
    assert email.template_key == "billing.trial_ending"


@override_settings(NOTIFICATIONS_RETENTION_DAYS=30)
def test_running_the_delivery_twice_does_not_warn_anybody_twice() -> None:
    organization, _owner, _member, _notice = tenant_with_notice(slug="notice-twice")

    assert deliver_billing_notices(at=NOW) == 1
    assert deliver_billing_notices(at=NOW + timedelta(minutes=1)) == 0

    assert AppNotification.all_objects.filter(organization=organization).count() == 1
    assert NotificationMessage.all_objects.filter(organization=organization).count() == 1


@override_settings(NOTIFICATIONS_RETENTION_DAYS=30)
def test_the_end_of_a_grace_period_is_louder_than_the_end_of_a_trial() -> None:
    organization, _owner, _member, _notice = tenant_with_notice(
        slug="notice-grace", notice_type=BillingNoticeType.GRACE_ENDING
    )

    deliver_billing_notices(at=NOW)

    entry = AppNotification.all_objects.get(organization=organization)
    assert entry.kind == "billing.grace_ending"
    assert entry.severity == NotificationSeverity.CRITICAL


@override_settings(NOTIFICATIONS_RETENTION_DAYS=30)
def test_the_inbox_belongs_to_one_person_in_one_organization() -> None:
    organization, owner, member, _notice = tenant_with_notice(slug="notice-inbox")
    deliver_billing_notices(at=NOW)

    with activate_tenant_context(context_for(organization, owner)):
        items, unread = list_app_notifications()
        assert len(items) == 1
        assert unread == 1
        assert mark_app_notifications_read() == 0
        _items, unread_after = list_app_notifications()
        assert unread_after == 0

    with activate_tenant_context(context_for(organization, member)):
        items, unread = list_app_notifications()
    assert items == [] and unread == 0
