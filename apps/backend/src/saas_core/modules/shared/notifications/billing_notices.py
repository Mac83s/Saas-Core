"""Delivering the warnings billing writes but cannot send.

`BillingNotice` has carried a `delivered_at` column since it was written, and
nothing ever set it: the trial-ending warning was recorded in the database and
reached nobody. Billing cannot fix that itself — this module already depends on
billing, so the arrow only runs one way and billing must not learn about
e-mail.

So the delivery is a pull. Notices are durable rows; this walks the ones nobody
has sent yet and turns each into two things: a message in the product, for the
people who can act on it, and an e-mail, for the days they are not looking.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.utils import timezone

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus
from saas_core.modules.core.organizations.permissions import BILLING_MANAGE
from saas_core.modules.shared.billing.models import BillingNotice, BillingNoticeType
from saas_core.modules.shared.billing.tenant_scope import (
    billing_organization_ids,
    billing_tenant_scope,
)

from .models import AppNotification, NotificationPreference, NotificationSeverity
from .services import queue_email

#: How loud each warning is. A trial ending is a date to know about; a grace
#: period ending is the last moment before the product locks.
SEVERITY = {
    BillingNoticeType.TRIAL_ENDING: NotificationSeverity.WARNING,
    BillingNoticeType.GRACE_ENDING: NotificationSeverity.CRITICAL,
}
TEMPLATE_VERSION = 1


def deliver_billing_notices(*, at: datetime | None = None, limit: int = 200) -> int:
    """Send every notice nobody has sent yet. Returns how many were delivered."""
    now = at or timezone.now()
    delivered = 0
    remaining = limit
    for organization_id in billing_organization_ids():
        if remaining <= 0:
            break
        with billing_tenant_scope(organization_id):
            notices = list(
                BillingNotice.all_objects.select_for_update()
                .select_related("subscription__price_mapping__plan_version__plan", "organization")
                .filter(organization_id=organization_id, delivered_at__isnull=True)
                .order_by("created_at")[:remaining]
            )
            if not notices:
                continue
            recipients = _who_can_act(organization_id)
            for notice in notices:
                _deliver(notice, recipients=recipients, now=now)
                notice.delivered_at = now
                notice.save(update_fields=["delivered_at"])
                delivered += 1
                remaining -= 1
    return delivered


def _who_can_act(organization_id: uuid.UUID) -> list[Membership]:
    """The people who could do something about a billing warning.

    Not the invoice address: that is where documents go, and it is often an
    accountant who cannot change a plan. This is whoever holds the permission
    to manage billing in this organization.
    """
    # Membership status is the tenant's own answer to "does this person still
    # work here". Whether the account has finished verifying its e-mail is a
    # different question, and somebody mid-verification still needs to hear
    # that their card failed.
    memberships = Membership.objects.select_related("role", "user").filter(
        organization_id=organization_id, status=MembershipStatus.ACTIVE
    )
    return [
        membership
        for membership in memberships
        if BILLING_MANAGE in (membership.role.permissions or [])
    ]


def _deliver(notice: BillingNotice, *, recipients: list[Membership], now: datetime) -> None:
    plan = notice.subscription.price_mapping.plan_version.plan
    ends_at = str(notice.payload.get("ends_at", ""))
    payload = {
        "organization_name": notice.organization.name,
        "plan_name": plan.name,
        "ends_at": ends_at[:10],
    }
    kind = f"billing.{notice.notice_type}"
    severity = SEVERITY.get(BillingNoticeType(notice.notice_type), NotificationSeverity.INFO)
    key = f"billing-notice:{notice.id}"

    for membership in recipients:
        AppNotification.all_objects.get_or_create(
            organization_id=notice.organization_id,
            user=membership.user,
            idempotency_key=key,
            defaults={
                "kind": kind,
                "payload": payload,
                "severity": severity,
                "created_at": now,
            },
        )
        # The tenant context is what queue_email signs into the delivery task,
        # and the recipient is the actor it is sent on behalf of.
        with activate_tenant_context(
            TenantContext(
                organization_id=notice.organization_id,
                membership_id=membership.id,
                actor_id=membership.user_id,
                role_key=membership.role.key,
                permissions=frozenset({BILLING_MANAGE}),
            )
        ):
            queue_email(
                recipient_email=membership.user.email,
                template_key=kind,
                template_version=TEMPLATE_VERSION,
                locale=_locale_for(notice.organization_id, membership),
                template_context=payload,
                idempotency_key=f"{key}:{membership.user_id}",
                causation_id=str(notice.id),
                recipient_user=membership.user,
            )


def _locale_for(organization_id: uuid.UUID, membership: Membership) -> str:
    preference = NotificationPreference.all_objects.filter(
        organization_id=organization_id, user_id=membership.user_id
    ).first()
    if preference is not None:
        return str(preference.locale)
    return str(getattr(membership.user, "locale", "") or "pl")
