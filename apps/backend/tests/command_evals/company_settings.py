"""Evals of the settings groups' commands (ADR-078 pkt 12): booking reminders
and the online-booking pause, built from their declarations."""

from __future__ import annotations

from typing import Any

from django.db.models import F

from saas_core.modules.core.organizations.context import TenantContext
from saas_core.modules.core.organizations.models import OrganizationSetting
from saas_core.modules.shared.billing.models import (
    AccessMode,
    EntitlementSnapshot,
    SubscriptionState,
)

from . import CommandEval


def _booking_plan(context: TenantContext) -> None:
    EntitlementSnapshot.all_objects.create(
        organization_id=context.organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"booking.enabled": True},
        quotas={},
        sources={"booking.enabled": {"kind": "plan"}},
    )


def _values(context: TenantContext) -> list[Any]:
    return list(
        OrganizationSetting.objects.filter(organization_id=context.organization_id)
        .order_by("key")
        .values_list("key", "value", "version")
    )


def _stale(key: str) -> Any:
    """Somebody else changed one of the group's values since the preview."""

    def move(context: TenantContext) -> None:
        row, _ = OrganizationSetting.objects.get_or_create(
            organization_id=context.organization_id, key=key
        )
        OrganizationSetting.objects.filter(pk=row.pk).update(version=F("version") + 1)

    return move


EVALS = {
    "booking.settings_reminders.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"lead_hours": 48},
        wrong_field="lead_hours",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_booking_plan,
    ),
    "booking.settings_reminders.update@1": CommandEval(
        arguments=lambda _context: {
            "enabled": None,
            "lead_hours": 48,
            "min_notice_hours": None,
            "reset": None,
        },
        wrong_arguments={
            "enabled": None,
            "lead_hours": 500,
            "min_notice_hours": None,
            "reset": None,
        },
        wrong_field="lead_hours",
        stale=_stale("booking.reminders.lead_hours"),
        state=_values,
        prepare=_booking_plan,
    ),
    "booking.settings_online.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"paused": True},
        wrong_field="paused",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_booking_plan,
    ),
    "booking.settings_online.update@1": CommandEval(
        arguments=lambda _context: {"paused": True, "resume_on": None, "reset": None},
        wrong_arguments={"paused": "tak", "resume_on": None, "reset": None},
        wrong_field="paused",
        stale=_stale("booking.online.paused"),
        state=_values,
        prepare=_booking_plan,
    ),
}
