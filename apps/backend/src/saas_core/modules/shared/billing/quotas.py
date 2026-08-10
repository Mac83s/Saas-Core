from __future__ import annotations

from datetime import UTC, date, datetime

from django.db import transaction
from rest_framework.exceptions import APIException, PermissionDenied

from saas_core.modules.core.organizations.context import require_tenant_context

from .decisions import QuotaDecision, decide_quota
from .models import (
    AccessMode,
    EntitlementSnapshot,
    QuotaDefinition,
    QuotaPeriod,
    QuotaReservation,
    QuotaReservationState,
    QuotaUsage,
)


class QuotaUnavailable(PermissionDenied):
    default_detail = "Limit nie jest dostępny dla organizacji."
    default_code = "quota_unavailable"

    def __init__(self, decision: QuotaDecision) -> None:
        self.decision = decision
        super().__init__(code=self.default_code)


class QuotaExceeded(APIException):
    status_code = 409
    default_detail = "Limit organizacji został wyczerpany."
    default_code = "quota_exceeded"


class QuotaReservationConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji został użyty dla innej rezerwacji."
    default_code = "quota_reservation_conflict"


@transaction.atomic
def reserve_quota(
    quota_key: str,
    *,
    amount: int,
    idempotency_key: str,
    at: datetime | None = None,
    expires_at: datetime | None = None,
) -> QuotaReservation:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("Rezerwowana ilość musi być dodatnią liczbą całkowitą.")
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ValueError("Klucz idempotencji jest wymagany.")
    if len(normalized_key) > 120:
        raise ValueError("Klucz idempotencji może mieć maksymalnie 120 znaków.")
    checked_at = at or datetime.now(UTC)
    if expires_at is not None and expires_at <= checked_at:
        raise ValueError("Wygaśnięcie rezerwacji musi przypadać w przyszłości.")

    context = require_tenant_context()
    snapshot = (
        EntitlementSnapshot.all_objects.select_for_update()
        .filter(organization_id=context.organization_id)
        .first()
    )
    existing = (
        QuotaReservation.all_objects.select_related("usage__quota_definition")
        .filter(
            organization_id=context.organization_id,
            idempotency_key=normalized_key,
        )
        .first()
    )
    if existing is not None:
        if existing.usage.quota_definition.key != quota_key or existing.amount != amount:
            raise QuotaReservationConflict
        return existing

    decision = decide_quota(quota_key, at=checked_at)
    if snapshot is None or snapshot.access_mode != AccessMode.FULL or not decision.available:
        raise QuotaUnavailable(decision)

    quota_definition = QuotaDefinition.objects.get(key=quota_key, is_active=True)
    period_start, period_end = _period_window(quota_definition.period, at=checked_at)
    usage, _ = QuotaUsage.all_objects.select_for_update().get_or_create(
        organization_id=context.organization_id,
        quota_definition=quota_definition,
        period_start=period_start,
        period_end=period_end,
    )
    if usage.used + usage.reserved + amount > decision.value:
        raise QuotaExceeded

    reservation = QuotaReservation.all_objects.create(
        organization_id=context.organization_id,
        usage=usage,
        idempotency_key=normalized_key,
        amount=amount,
        expires_at=expires_at,
    )
    usage.reserved += amount
    usage.save(update_fields=["reserved", "updated_at"])
    return reservation


@transaction.atomic
def commit_quota(idempotency_key: str) -> QuotaReservation:
    reservation, usage = _locked_reservation(idempotency_key)
    if reservation.state == QuotaReservationState.COMMITTED:
        return reservation
    if reservation.state == QuotaReservationState.RELEASED:
        raise QuotaReservationConflict
    usage.reserved -= reservation.amount
    usage.used += reservation.amount
    usage.save(update_fields=["reserved", "used", "updated_at"])
    reservation.state = QuotaReservationState.COMMITTED
    reservation.save(update_fields=["state", "updated_at"])
    return reservation


@transaction.atomic
def release_quota(idempotency_key: str) -> QuotaReservation:
    reservation, usage = _locked_reservation(idempotency_key)
    if reservation.state == QuotaReservationState.RELEASED:
        return reservation
    if reservation.state == QuotaReservationState.COMMITTED:
        raise QuotaReservationConflict
    usage.reserved -= reservation.amount
    usage.save(update_fields=["reserved", "updated_at"])
    reservation.state = QuotaReservationState.RELEASED
    reservation.save(update_fields=["state", "updated_at"])
    return reservation


def _locked_reservation(idempotency_key: str) -> tuple[QuotaReservation, QuotaUsage]:
    context = require_tenant_context()
    reservation = QuotaReservation.all_objects.select_for_update().get(
        organization_id=context.organization_id,
        idempotency_key=idempotency_key.strip(),
    )
    usage = QuotaUsage.all_objects.select_for_update().get(pk=reservation.usage_id)
    return reservation, usage


def _period_window(period: str, *, at: datetime | None) -> tuple[date, date | None]:
    if period == QuotaPeriod.LIFETIME:
        return date(1970, 1, 1), None
    checked_at = (at or datetime.now(UTC)).astimezone(UTC)
    start = date(checked_at.year, checked_at.month, 1)
    if checked_at.month == 12:
        return start, date(checked_at.year + 1, 1, 1)
    return start, date(checked_at.year, checked_at.month + 1, 1)
