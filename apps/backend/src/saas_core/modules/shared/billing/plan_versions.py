"""An operator brings a company to the current version of its plan (owner
decisions of 2026-10-04).

A published version never changes and a company stays on the one it was given
or bought (ADR-032), so what a newer version adds never reaches the companies
already there. This is the one way over, and it is never taken by itself:

- at the same price (amount, currency, interval) any number of companies may
  move in one run;
- at another price one named company moves at a time, behind the operator's
  step-up, and the price is said;
- whatever the newer version takes away — a feature, a limit lowered or
  dropped — moves nobody until the operator accepts it.

A subscription kept at Stripe is not moved from here at all. Its version is
named by its price at the provider: every webhook and the reconciliation write
the snapshot from that price, and this module has no call that changes the
price of a running subscription, so a local change would be undone by the next
event. Such a company is refused with that sentence. The simulator's
subscription lives in this database only and moves with its price mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.identity.operators import (
    PLATFORM_ADMIN,
    OperatorLevelRequired,
    operator_level,
)
from saas_core.modules.core.identity.step_up import require_step_up
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization

from .models import (
    BillingSubscription,
    EntitlementSnapshot,
    PlanVersion,
    StripePriceMapping,
    SubscriptionState,
)
from .snapshots import _write_entitlement_snapshot
from .tenant_scope import billing_organization_ids, billing_tenant_scope

#: The company's history: „Plan zaktualizowany do bieżącej wersji przez operatora”.
PLAN_VERSION_MOVED = "billing.plan.version_moved"

#: How the company holds its plan.
GRANTED = "granted"  # given without a payment; no subscription behind it
SIMULATED = "simulated"  # a subscription of the payment simulator
STRIPE = "stripe"  # a subscription kept at Stripe

_SIMULATED_PROVIDER = "simulated"
_IN_FORCE = (SubscriptionState.ACTIVE, SubscriptionState.TRIALING)

#: Why a company stays where it is. The first three hold whatever the operator
#: accepts; the last two are what the operator has to accept.
REFUSALS = {
    "stripe_subscription": (
        "Firma ma subskrypcję w Stripe. Wersję planu takiej subskrypcji wyznacza jej cena "
        "u operatora płatności, a moduł rozliczeń nie zmienia ceny trwającej subskrypcji — "
        "firma zostaje na swojej wersji."
    ),
    "simulated_price_missing": (
        "Bieżąca wersja planu nie ma aktywnej ceny w symulatorze płatności, więc subskrypcji "
        "nie ma do czego przepiąć."
    ),
    "plan_not_in_force": (
        "Plan firmy nie jest teraz w mocy (zakończony albo wstrzymany) — nie ma czego przenosić."
    ),
    "price_differs": (
        "Bieżąca wersja planu ma inną cenę. Taką firmę przenosi się pojedynczo, "
        "po potwierdzeniu zmiany ceny."
    ),
    "losses": (
        "Bieżąca wersja planu coś firmie odbiera. Przeniesienie wymaga osobnej zgody operatora."
    ),
}


class PlanMoveRefused(APIException):
    status_code = 409
    default_code = "billing_plan_move_refused"

    def __init__(self, code: str) -> None:
        super().__init__(detail=REFUSALS[code], code=f"billing_plan_move_{code}")
        self.reason = code


class PlanMoveReasonRequired(APIException):
    status_code = 400
    default_detail = "Podaj powód przeniesienia; trafia do historii firmy."
    default_code = "billing_plan_move_reason_required"


@dataclass(frozen=True, slots=True)
class Price:
    unit_amount_minor: int
    currency: str
    billing_interval: str


@dataclass(frozen=True, slots=True)
class PlanMove:
    """What moving one company to its plan's current version means for it."""

    organization_id: UUID
    organization_name: str
    plan_key: str
    from_version: int
    to_version: int
    payment: str
    price_from: Price
    price_to: Price
    gained_features: tuple[str, ...]
    lost_features: tuple[str, ...]
    #: Limit key -> (now, after); None where that version has no such limit.
    raised_limits: dict[str, tuple[int | None, int | None]]
    lowered_limits: dict[str, tuple[int | None, int | None]]
    #: A key of `REFUSALS` when no consent of the operator can move the company.
    refusal: str = ""

    @property
    def same_price(self) -> bool:
        return self.price_from == self.price_to

    @property
    def has_losses(self) -> bool:
        return bool(self.lost_features or self.lowered_limits)

    def blocked_by(self, *, accept_losses: bool, accept_price_change: bool) -> str:
        """The key of `REFUSALS` that stops this move, or "" when it may run."""
        if self.refusal:
            return self.refusal
        if not self.same_price and not accept_price_change:
            return "price_differs"
        if self.has_losses and not accept_losses:
            return "losses"
        return ""


def _price(version: PlanVersion) -> Price:
    return Price(version.unit_amount_minor, version.currency, version.billing_interval)


def _limit_changes(
    own: dict[str, int], current: dict[str, int]
) -> tuple[dict[str, tuple[int | None, int | None]], dict[str, tuple[int | None, int | None]]]:
    raised: dict[str, tuple[int | None, int | None]] = {}
    lowered: dict[str, tuple[int | None, int | None]] = {}
    for key in sorted({*own, *current}):
        now, after = own.get(key), current.get(key)
        if now == after:
            continue
        # A limit the version does not name is one the company does not have.
        if after is None or (now is not None and after < now):
            lowered[key] = (now, after)
        else:
            raised[key] = (now, after)
    return raised, lowered


def _simulated_price(version: PlanVersion) -> StripePriceMapping | None:
    return StripePriceMapping.objects.filter(
        plan_version=version, provider=_SIMULATED_PROVIDER, livemode=False, is_active=True
    ).first()


def _pending(
    organization_id: UUID, *, lock: bool
) -> tuple[PlanMove, EntitlementSnapshot, BillingSubscription | None, PlanVersion] | None:
    """The move one company is due, read inside its tenant scope; None when it
    has no plan or is already on the current version."""
    snapshots = EntitlementSnapshot.all_objects.filter(organization_id=organization_id)
    subscriptions = BillingSubscription.all_objects.filter(organization_id=organization_id).exclude(
        state=SubscriptionState.CANCELED
    )
    if lock:
        snapshots = snapshots.select_for_update(of=("self",))
        subscriptions = subscriptions.select_for_update(of=("self",))
    snapshot = snapshots.select_related("plan_version__plan__current_version").first()
    subscription = subscriptions.select_related(
        "price_mapping__plan_version__plan__current_version"
    ).first()
    if snapshot is None:
        return None
    # The company's version is its subscription's while one runs, exactly as
    # the plan card reads it (overview.py).
    own = subscription.price_mapping.plan_version if subscription else snapshot.plan_version
    if own is None:
        return None
    current = own.plan.current_version
    # Only forward: a catalogue put back to an earlier version takes nobody along.
    if current is None or current.id == own.id or current.version <= own.version:
        return None

    refusal = ""
    if subscription is None:
        payment = GRANTED
        if snapshot.subscription_state != SubscriptionState.ACTIVE:
            refusal = "plan_not_in_force"
    elif subscription.price_mapping.provider == _SIMULATED_PROVIDER:
        payment = SIMULATED
        if subscription.state not in _IN_FORCE:
            refusal = "plan_not_in_force"
        elif _simulated_price(current) is None:
            refusal = "simulated_price_missing"
    else:
        payment = STRIPE
        refusal = "stripe_subscription"

    raised, lowered = _limit_changes(own.quotas, current.quotas)
    move = PlanMove(
        organization_id=organization_id,
        organization_name=Organization.objects.values_list("name", flat=True).get(
            pk=organization_id
        ),
        plan_key=own.plan.key,
        from_version=own.version,
        to_version=current.version,
        payment=payment,
        price_from=_price(own),
        price_to=_price(current),
        gained_features=tuple(sorted(set(current.feature_keys) - set(own.feature_keys))),
        lost_features=tuple(sorted(set(own.feature_keys) - set(current.feature_keys))),
        raised_limits=raised,
        lowered_limits=lowered,
        refusal=refusal,
    )
    return move, snapshot, subscription, current


def plan_move(organization_id: UUID) -> PlanMove | None:
    """What the move would mean for one company. Writes nothing."""
    with billing_tenant_scope(organization_id):
        pending = _pending(organization_id, lock=False)
    return pending[0] if pending else None


def pending_plan_moves(*, plan_key: str | None = None) -> list[PlanMove]:
    """Every company on an older version of its plan. Writes nothing."""
    moves = [plan_move(organization_id) for organization_id in billing_organization_ids()]
    return [
        move
        for move in moves
        if move is not None and (plan_key is None or move.plan_key == plan_key)
    ]


def apply_plan_move(
    organization_id: UUID,
    *,
    operator: User,
    reason: str,
    accept_losses: bool = False,
    accept_price_change: bool = False,
) -> PlanMove | None:
    """Moves one company in a transaction of its own; None when it is already
    on the current version, so a second run changes nothing.

    Only a level-2 operator: the move changes what a company gets, and may
    change what it pays. Another price also asks for a fresh step-up.
    """
    if operator_level(operator) < PLATFORM_ADMIN:
        raise OperatorLevelRequired
    stated = reason.strip()
    if not stated:
        raise PlanMoveReasonRequired
    with billing_tenant_scope(organization_id):
        pending = _pending(organization_id, lock=True)
        if pending is None:
            return None
        move, snapshot, subscription, current = pending
        blocked = move.blocked_by(
            accept_losses=accept_losses, accept_price_change=accept_price_change
        )
        if blocked:
            raise PlanMoveRefused(blocked)
        if not move.same_price:
            require_step_up(user_id=operator.pk, reason="billing.plan_version_move")

        price_id: str | None = None
        if subscription is not None:
            # Only the simulator's subscription reaches this line (see `_pending`).
            mapping = _simulated_price(current)
            if mapping is None:
                raise PlanMoveRefused("simulated_price_missing")
            subscription.price_mapping = mapping
            subscription.version += 1
            subscription.save(update_fields=["price_mapping", "version", "updated_at"])
            price_id = mapping.stripe_price_id
        organization = Organization.objects.get(pk=organization_id)
        # State, access and its end stay as they are: the move changes the
        # terms of the plan, not whether the plan is in force.
        _write_entitlement_snapshot(
            organization,
            plan_version=current,
            stripe_price_id=price_id,
            state=snapshot.subscription_state,
            access_mode=snapshot.access_mode,
            effective_until=snapshot.effective_until,
            snapshot=snapshot,
        )
        record_audit(
            organization=organization,
            action=PLAN_VERSION_MOVED,
            actor=operator,
            target_type="billing_plan_version",
            target_id=current.id,
            metadata=_history(move, stated),
        )
    return move


def _history(move: PlanMove, reason: str) -> dict[str, Any]:
    def price(value: Price) -> dict[str, Any]:
        return {
            "unit_amount_minor": value.unit_amount_minor,
            "currency": value.currency,
            "billing_interval": value.billing_interval,
        }

    return {
        "plan": move.plan_key,
        "from_version": move.from_version,
        "to_version": move.to_version,
        "payment": move.payment,
        "price_from": price(move.price_from),
        "price_to": price(move.price_to),
        "gained_features": list(move.gained_features),
        "lost_features": list(move.lost_features),
        "raised_limits": {key: list(pair) for key, pair in move.raised_limits.items()},
        "lowered_limits": {key: list(pair) for key, pair in move.lowered_limits.items()},
        "reason": reason,
    }
