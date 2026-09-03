"""Credits: a prepaid pool our customers spend on metered operations.

Two buckets behind one number. The plan grants a monthly allowance that resets
and does not carry over; purchased credits never expire. Spending always takes
the allowance first, so a company never loses what it paid for separately just
because the month turned over.

The ledger is the source of truth and the balance row is its cached sum. Every
movement writes exactly one ledger entry per bucket it touches, and a test
rebuilds the balance from the ledger to prove the two cannot drift.

Reservations exist because a metered operation can fail. Reserving holds the
credits without spending them, committing spends them, releasing gives them
back — the same shape quotas already use, and for the same reason: an AI call
that times out must not bill anybody.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import APIException, PermissionDenied

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.models import (
    Organization,
    OrganizationAuditAction,
)

from .models import (
    AccessMode,
    CreditBalance,
    CreditBucket,
    CreditLedgerEntry,
    CreditLedgerKind,
    CreditOperation,
    CreditPack,
    CreditPurchase,
    CreditPurchaseStatus,
    CreditReservation,
    CreditReservationState,
    EntitlementSnapshot,
)
from .tenant_scope import billing_organization_ids, billing_tenant_scope

#: The plan's monthly allowance is an ordinary entitlement quota, so it is
#: versioned with the plan, overridable per organization and already visible in
#: the entitlement snapshot. Credits do not need a second catalog for it.
ALLOWANCE_QUOTA_KEY = "credits.monthly"


class CreditsUnavailable(PermissionDenied):
    default_detail = "Kredyty nie są dostępne dla tej organizacji."
    default_code = "credits_unavailable"


class CreditsExhausted(APIException):
    status_code = 402
    default_detail = "Brak wystarczającej liczby kredytów."
    default_code = "credits_exhausted"


class UnknownCreditOperation(APIException):
    status_code = 409
    default_detail = "Nieznana operacja kredytowa."
    default_code = "credit_operation_unknown"


class CreditReservationConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji został użyty dla innej rezerwacji."
    default_code = "credit_reservation_conflict"


class CreditReservationExpired(APIException):
    status_code = 409
    default_detail = "Rezerwacja kredytów wygasła przed rozliczeniem."
    default_code = "credit_reservation_expired"


class CreditPurchaseConflict(APIException):
    status_code = 409
    default_detail = "Zakup kredytów jest w innym stanie niż oczekiwany."
    default_code = "credit_purchase_conflict"


@dataclass(frozen=True, slots=True)
class CreditSummary:
    allowance_remaining: int
    allowance_reserved: int
    allowance_granted: int
    allowance_period_start: date | None
    allowance_period_end: date | None
    purchased_remaining: int
    purchased_reserved: int
    available: int


# ------------------------------------------------------------------ catalog --


def operation_cost(operation_key: str) -> int:
    """What one operation costs now, or zero when it is not metered yet.

    An unknown key is an error rather than a free pass: a typo must not turn
    into silent free usage. A known but inactive operation costs nothing, which
    is how metering is switched on for a surface without a code change.
    """
    operation = CreditOperation.objects.filter(key=operation_key).first()
    if operation is None:
        raise UnknownCreditOperation(f"Operacja {operation_key!r} nie jest w katalogu.")
    return operation.cost if operation.is_active else 0


# ------------------------------------------------------------------ balance --


def _month_window(at: datetime) -> tuple[date, date]:
    checked_at = at.astimezone(UTC)
    start = date(checked_at.year, checked_at.month, 1)
    if checked_at.month == 12:
        return start, date(checked_at.year + 1, 1, 1)
    return start, date(checked_at.year, checked_at.month + 1, 1)


def _allowance_for(organization_id: UUID) -> int:
    snapshot = (
        EntitlementSnapshot.all_objects.filter(organization_id=organization_id)
        .values_list("quotas", "access_mode")
        .first()
    )
    if snapshot is None:
        return 0
    quotas, access_mode = snapshot
    if access_mode != AccessMode.FULL:
        # Read-only access keeps the data visible and stops it growing; handing
        # out a fresh allowance to a company that stopped paying would not be
        # read-only in any sense that matters.
        return 0
    value = quotas.get(ALLOWANCE_QUOTA_KEY, 0) if isinstance(quotas, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _locked_balance(organization_id: UUID) -> CreditBalance:
    balance, _ = CreditBalance.all_objects.get_or_create(organization_id=organization_id)
    return CreditBalance.all_objects.select_for_update().get(pk=balance.pk)


def _write_entry(
    balance: CreditBalance,
    *,
    kind: str,
    bucket: str,
    amount: int,
    at: datetime,
    operation_key: str = "",
    operation_cost_value: int | None = None,
    reservation: CreditReservation | None = None,
    purchase: CreditPurchase | None = None,
    reason: str = "",
    actor: User | None = None,
    idempotency_key: str = "",
) -> CreditLedgerEntry:
    balance_after = (
        balance.allowance_remaining
        if bucket == CreditBucket.ALLOWANCE
        else balance.purchased_remaining
    )
    return CreditLedgerEntry.all_objects.create(
        organization_id=balance.organization_id,
        kind=kind,
        bucket=bucket,
        amount=amount,
        balance_after=balance_after,
        operation_key=operation_key,
        operation_cost=operation_cost_value,
        reservation=reservation,
        purchase=purchase,
        reason=reason,
        actor=actor,
        idempotency_key=idempotency_key,
        occurred_at=at,
    )


def _sync_allowance(balance: CreditBalance, *, at: datetime) -> None:
    """Brings the allowance bucket up to date with the plan and the calendar.

    Rollover expires only what is free: an in-flight reservation keeps its
    credits until it settles, so a month boundary cannot make a running
    operation fail. A mid-month upgrade tops the allowance up to the new
    figure; a downgrade never claws back what was already granted.
    """
    period_start, period_end = _month_window(at)
    allowance = _allowance_for(balance.organization_id)
    dirty = False

    if balance.allowance_period_start != period_start:
        expiring = balance.allowance_remaining - balance.allowance_reserved
        if expiring > 0:
            balance.allowance_remaining -= expiring
            _write_entry(
                balance,
                kind=CreditLedgerKind.ALLOWANCE_EXPIRED,
                bucket=CreditBucket.ALLOWANCE,
                amount=-expiring,
                at=at,
                reason="Pula planu wygasła wraz z końcem okresu.",
            )
        balance.allowance_period_start = period_start
        balance.allowance_period_end = period_end
        balance.allowance_granted = 0
        dirty = True

    missing = allowance - balance.allowance_granted
    if missing > 0:
        balance.allowance_remaining += missing
        balance.allowance_granted += missing
        _write_entry(
            balance,
            kind=CreditLedgerKind.ALLOWANCE_GRANTED,
            bucket=CreditBucket.ALLOWANCE,
            amount=missing,
            at=at,
            reason=f"Pula planu na okres {period_start.isoformat()}.",
        )
        dirty = True

    if dirty:
        balance.version += 1
        balance.save(
            update_fields=[
                "allowance_remaining",
                "allowance_granted",
                "allowance_period_start",
                "allowance_period_end",
                "version",
                "updated_at",
            ]
        )


@transaction.atomic
def credit_summary(*, at: datetime | None = None) -> CreditSummary:
    """The current tenant's balance, with the allowance brought up to date."""
    context = require_tenant_context()
    checked_at = at or datetime.now(UTC)
    balance = _locked_balance(context.organization_id)
    _sync_allowance(balance, at=checked_at)
    return CreditSummary(
        allowance_remaining=balance.allowance_remaining,
        allowance_reserved=balance.allowance_reserved,
        allowance_granted=balance.allowance_granted,
        allowance_period_start=balance.allowance_period_start,
        allowance_period_end=balance.allowance_period_end,
        purchased_remaining=balance.purchased_remaining,
        purchased_reserved=balance.purchased_reserved,
        available=balance.available,
    )


# -------------------------------------------------------------- reservation --


def _normalized_key(idempotency_key: str) -> str:
    normalized = idempotency_key.strip()
    if not normalized:
        raise ValueError("Klucz idempotencji jest wymagany.")
    if len(normalized) > 120:
        raise ValueError("Klucz idempotencji może mieć maksymalnie 120 znaków.")
    return normalized


@transaction.atomic
def reserve_credits(
    operation_key: str,
    *,
    idempotency_key: str,
    at: datetime | None = None,
    expires_at: datetime | None = None,
) -> CreditReservation | None:
    """Holds the credits one operation will cost. ``None`` means it is free."""
    context = require_tenant_context()
    normalized = _normalized_key(idempotency_key)
    checked_at = at or datetime.now(UTC)
    if expires_at is not None and expires_at <= checked_at:
        raise ValueError("Wygaśnięcie rezerwacji musi przypadać w przyszłości.")

    existing = CreditReservation.all_objects.filter(
        organization_id=context.organization_id, idempotency_key=normalized
    ).first()
    if existing is not None:
        if existing.operation_key != operation_key:
            raise CreditReservationConflict
        return existing

    cost = operation_cost(operation_key)
    if cost == 0:
        return None

    balance = _locked_balance(context.organization_id)
    _sync_allowance(balance, at=checked_at)
    if balance.available < cost:
        raise CreditsExhausted

    from_allowance = min(cost, balance.allowance_remaining - balance.allowance_reserved)
    from_purchased = cost - from_allowance
    balance.allowance_reserved += from_allowance
    balance.purchased_reserved += from_purchased
    balance.version += 1
    balance.save(
        update_fields=["allowance_reserved", "purchased_reserved", "version", "updated_at"]
    )
    return CreditReservation.all_objects.create(
        organization_id=context.organization_id,
        idempotency_key=normalized,
        operation_key=operation_key,
        cost=cost,
        allowance_amount=from_allowance,
        purchased_amount=from_purchased,
        expires_at=expires_at,
    )


def _locked_pair(idempotency_key: str) -> tuple[CreditReservation, CreditBalance]:
    context = require_tenant_context()
    reservation = CreditReservation.all_objects.select_for_update().get(
        organization_id=context.organization_id,
        idempotency_key=_normalized_key(idempotency_key),
    )
    balance = _locked_balance(context.organization_id)
    return reservation, balance


@transaction.atomic
def commit_credits(idempotency_key: str, *, at: datetime | None = None) -> CreditReservation:
    """Spends a held reservation and writes it into the ledger."""
    checked_at = at or datetime.now(UTC)
    reservation, balance = _locked_pair(idempotency_key)
    if reservation.state == CreditReservationState.COMMITTED:
        return reservation
    if reservation.state == CreditReservationState.RELEASED:
        raise CreditReservationConflict
    if reservation.expires_at is not None and reservation.expires_at <= checked_at:
        raise CreditReservationExpired

    balance.allowance_reserved -= reservation.allowance_amount
    balance.allowance_remaining -= reservation.allowance_amount
    balance.purchased_reserved -= reservation.purchased_amount
    balance.purchased_remaining -= reservation.purchased_amount
    balance.version += 1
    balance.save(
        update_fields=[
            "allowance_reserved",
            "allowance_remaining",
            "purchased_reserved",
            "purchased_remaining",
            "version",
            "updated_at",
        ]
    )
    for bucket, amount in (
        (CreditBucket.ALLOWANCE, reservation.allowance_amount),
        (CreditBucket.PURCHASED, reservation.purchased_amount),
    ):
        if amount == 0:
            continue
        _write_entry(
            balance,
            kind=CreditLedgerKind.CONSUMED,
            bucket=bucket,
            amount=-amount,
            at=checked_at,
            operation_key=reservation.operation_key,
            operation_cost_value=reservation.cost,
            reservation=reservation,
            idempotency_key=reservation.idempotency_key,
        )
    reservation.state = CreditReservationState.COMMITTED
    reservation.save(update_fields=["state", "updated_at"])
    return reservation


@transaction.atomic
def release_credits(idempotency_key: str) -> CreditReservation:
    """Gives back a hold that was never spent. Nothing reaches the ledger."""
    reservation, balance = _locked_pair(idempotency_key)
    if reservation.state == CreditReservationState.RELEASED:
        return reservation
    if reservation.state == CreditReservationState.COMMITTED:
        raise CreditReservationConflict
    balance.allowance_reserved -= reservation.allowance_amount
    balance.purchased_reserved -= reservation.purchased_amount
    balance.version += 1
    balance.save(
        update_fields=["allowance_reserved", "purchased_reserved", "version", "updated_at"]
    )
    reservation.state = CreditReservationState.RELEASED
    reservation.save(update_fields=["state", "updated_at"])
    return reservation


def spend_credits(
    operation_key: str,
    *,
    idempotency_key: str,
    at: datetime | None = None,
) -> CreditReservation | None:
    """Reserve and commit in one step, for an operation that cannot fail."""
    reservation = reserve_credits(operation_key, idempotency_key=idempotency_key, at=at)
    if reservation is None:
        return None
    return commit_credits(idempotency_key, at=at)


@transaction.atomic
def refund_credits(
    idempotency_key: str,
    *,
    reason: str,
    at: datetime | None = None,
) -> CreditReservation:
    """Returns a committed spend to the buckets it came from.

    Compensation rather than deletion: the original consumption stays in the
    ledger and the refund is its own entry, so the history still says what
    happened.
    """
    checked_at = at or datetime.now(UTC)
    reservation, balance = _locked_pair(idempotency_key)
    if reservation.state != CreditReservationState.COMMITTED:
        raise CreditReservationConflict
    already_refunded = CreditLedgerEntry.all_objects.filter(
        organization_id=balance.organization_id,
        reservation=reservation,
        kind=CreditLedgerKind.REFUNDED,
    ).exists()
    if already_refunded:
        return reservation

    balance.allowance_remaining += reservation.allowance_amount
    balance.purchased_remaining += reservation.purchased_amount
    balance.version += 1
    balance.save(
        update_fields=["allowance_remaining", "purchased_remaining", "version", "updated_at"]
    )
    for bucket, amount in (
        (CreditBucket.ALLOWANCE, reservation.allowance_amount),
        (CreditBucket.PURCHASED, reservation.purchased_amount),
    ):
        if amount == 0:
            continue
        _write_entry(
            balance,
            kind=CreditLedgerKind.REFUNDED,
            bucket=bucket,
            amount=amount,
            at=checked_at,
            operation_key=reservation.operation_key,
            operation_cost_value=reservation.cost,
            reservation=reservation,
            reason=reason,
        )
    return reservation


# ----------------------------------------------------------------- purchase --


@transaction.atomic
def start_credit_purchase(pack_key: str, *, idempotency_key: str) -> CreditPurchase:
    """Records the intent to buy a pack. Nothing is credited until it is paid."""
    context = require_tenant_context()
    normalized = _normalized_key(idempotency_key)
    existing = (
        CreditPurchase.all_objects.select_related("pack")
        .filter(organization_id=context.organization_id, idempotency_key=normalized)
        .first()
    )
    if existing is not None:
        if existing.pack.key != pack_key:
            raise CreditPurchaseConflict
        return existing

    snapshot = (
        EntitlementSnapshot.all_objects.filter(organization_id=context.organization_id)
        .values_list("access_mode", flat=True)
        .first()
    )
    if snapshot != AccessMode.FULL:
        # Credits are an add-on to a live subscription, not a way around one.
        raise CreditsUnavailable

    pack = CreditPack.objects.filter(key=pack_key, is_active=True).first()
    if pack is None:
        raise CreditPurchaseConflict(f"Pakiet {pack_key!r} nie jest dostępny.")
    return CreditPurchase.all_objects.create(
        organization_id=context.organization_id,
        pack=pack,
        credits=pack.credits,
        currency=pack.currency,
        unit_amount_minor=pack.unit_amount_minor,
        idempotency_key=normalized,
    )


@transaction.atomic
def complete_credit_purchase(
    *,
    organization_id: UUID,
    purchase_id: UUID,
    provider_reference: str,
    at: datetime | None = None,
) -> CreditPurchase:
    """Credits a paid pack. Called from a confirmed payment, never from a return URL."""
    checked_at = at or datetime.now(UTC)
    purchase = CreditPurchase.all_objects.select_for_update().get(
        pk=purchase_id, organization_id=organization_id
    )
    if purchase.status == CreditPurchaseStatus.SUCCEEDED:
        return purchase
    if purchase.status != CreditPurchaseStatus.PENDING:
        raise CreditPurchaseConflict

    balance = _locked_balance(organization_id)
    balance.purchased_remaining += purchase.credits
    balance.version += 1
    balance.save(update_fields=["purchased_remaining", "version", "updated_at"])
    purchase.status = CreditPurchaseStatus.SUCCEEDED
    purchase.provider_reference = provider_reference
    purchase.completed_at = checked_at
    purchase.save(update_fields=["status", "provider_reference", "completed_at", "updated_at"])
    _write_entry(
        balance,
        kind=CreditLedgerKind.PURCHASED,
        bucket=CreditBucket.PURCHASED,
        amount=purchase.credits,
        at=checked_at,
        purchase=purchase,
        reason=f"Zakup pakietu {purchase.pack.key}.",
        idempotency_key=purchase.idempotency_key,
    )
    record_audit(
        organization=Organization.objects.get(pk=organization_id),
        action=OrganizationAuditAction.BILLING_CREDITS_PURCHASED,
        actor=None,
        target_type="credit_purchase",
        target_id=purchase.id,
        metadata={
            "pack": purchase.pack.key,
            "credits": purchase.credits,
            "provider_reference": provider_reference,
        },
    )
    return purchase


@transaction.atomic
def grant_operator_credits(
    *,
    organization_id: UUID,
    actor: User,
    credits: int,
    reason: str,
    idempotency_key: str,
    at: datetime | None = None,
) -> CreditBalance:
    """An audited manual correction, the same escape hatch entitlements have."""
    if not isinstance(credits, int) or isinstance(credits, bool) or credits == 0:
        raise ValueError("Korekta musi być niezerową liczbą całkowitą.")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("Korekta operatora wymaga uzasadnienia.")
    if not actor.is_staff:
        raise CreditsUnavailable("Korekta kredytów wymaga operatora platformy.")
    normalized = _normalized_key(idempotency_key)
    checked_at = at or datetime.now(UTC)

    balance = _locked_balance(organization_id)
    replay = CreditLedgerEntry.all_objects.filter(
        organization_id=organization_id,
        kind=CreditLedgerKind.OPERATOR_ADJUSTMENT,
        idempotency_key=normalized,
    ).first()
    if replay is not None:
        return balance
    available_purchased = balance.purchased_remaining - balance.purchased_reserved
    if credits < 0 and available_purchased < -credits:
        raise CreditsExhausted

    balance.purchased_remaining += credits
    balance.version += 1
    balance.save(update_fields=["purchased_remaining", "version", "updated_at"])
    _write_entry(
        balance,
        kind=CreditLedgerKind.OPERATOR_ADJUSTMENT,
        bucket=CreditBucket.PURCHASED,
        amount=credits,
        at=checked_at,
        reason=normalized_reason,
        actor=actor,
        idempotency_key=normalized,
    )
    record_audit(
        organization=Organization.objects.get(pk=organization_id),
        action=OrganizationAuditAction.BILLING_CREDITS_ADJUSTED,
        actor=actor,
        target_type="credit_balance",
        target_id=balance.id,
        metadata={"credits": credits, "reason": normalized_reason},
    )
    return balance


# ------------------------------------------------------------------- sweeps --


def refresh_credit_allowances(*, at: datetime | None = None) -> int:
    """Grants the month's allowance to everybody who has one coming.

    Nothing depends on this running on time: any read of the balance syncs the
    allowance first. The sweep exists so the ledger tells a truthful story
    month by month even for an organization nobody looked at.
    """
    checked_at = at or datetime.now(UTC)
    refreshed = 0
    for organization_id in billing_organization_ids():
        with billing_tenant_scope(organization_id):
            balance = _locked_balance(organization_id)
            before = (balance.allowance_period_start, balance.allowance_granted)
            _sync_allowance(balance, at=checked_at)
            if (balance.allowance_period_start, balance.allowance_granted) != before:
                refreshed += 1
    return refreshed


def release_expired_credit_reservations(
    *,
    at: datetime | None = None,
    batch_size: int = 100,
) -> int:
    """Gives back holds whose operation never came back to settle them."""
    checked_at = at or datetime.now(UTC)
    released = 0
    remaining = batch_size
    for organization_id in billing_organization_ids():
        if remaining <= 0:
            break
        with billing_tenant_scope(organization_id):
            keys = list(
                CreditReservation.all_objects.filter(
                    organization_id=organization_id,
                    state=CreditReservationState.RESERVED,
                    expires_at__lte=checked_at,
                )
                .order_by("expires_at", "id")
                .values_list("idempotency_key", flat=True)[:remaining]
            )
        remaining -= len(keys)
        for key in keys:
            with billing_tenant_scope(organization_id):
                reservation = CreditReservation.all_objects.select_for_update().get(
                    organization_id=organization_id, idempotency_key=key
                )
                if reservation.state != CreditReservationState.RESERVED:
                    continue
                balance = _locked_balance(organization_id)
                balance.allowance_reserved -= reservation.allowance_amount
                balance.purchased_reserved -= reservation.purchased_amount
                balance.version += 1
                balance.save(
                    update_fields=[
                        "allowance_reserved",
                        "purchased_reserved",
                        "version",
                        "updated_at",
                    ]
                )
                reservation.state = CreditReservationState.RELEASED
                reservation.save(update_fields=["state", "updated_at"])
                released += 1
    return released
