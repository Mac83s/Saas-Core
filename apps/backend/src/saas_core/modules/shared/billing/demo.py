"""Billing's part of the demo (core/organizations/demo.py): the scenario's plan.

A demo organization gets the entitlements of its plan's current version
without a payment — the same snapshot a paid subscription writes
(`update_entitlement_snapshot`), carrying the plan's active price when the stack
has one, so on a stack billed through Stripe (test mode) nobody has to go
through a checkout. The
panel's billing screen then shows no subscription; the modules work. An
organization already on that plan, subscribed or seeded, is left alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from saas_core.modules.core.organizations.context import set_local_organization_id

from .models import AccessMode, EntitlementSnapshot, Plan, StripePriceMapping, SubscriptionState
from .snapshots import _write_entitlement_snapshot

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import DemoRun

LIVE = (SubscriptionState.ACTIVE, SubscriptionState.TRIALING)


def seed_plans(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        organization = run.organizations[spec.key]
        plan = Plan.objects.select_related("current_version").get(key=spec.plan)
        version = plan.current_version
        if version is None:
            raise ValueError(f"Plan {plan.key} nie ma opublikowanej wersji.")
        with transaction.atomic():
            set_local_organization_id(organization.id)
            snapshot = EntitlementSnapshot.all_objects.filter(organization=organization).first()
            if (
                snapshot is not None
                and snapshot.subscription_state in LIVE
                and snapshot.plan_version is not None
                and snapshot.plan_version.plan_id == plan.id
            ):
                run.log(f"= plan {plan.key} ({spec.name})")
                continue
            mapping = (
                StripePriceMapping.objects.filter(plan_version=version, is_active=True)
                .order_by("-created_at")
                .first()
            )
            _write_entitlement_snapshot(
                organization,
                plan_version=version,
                stripe_price_id=mapping.stripe_price_id if mapping else None,
                state=SubscriptionState.ACTIVE,
                access_mode=AccessMode.FULL,
                effective_until=None,
            )
        run.log(f"+ plan {plan.key} v{version.version} ({spec.name}), bez płatności")
