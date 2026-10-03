"""Evals of the settings groups' commands (ADR-078 pkt 12): booking reminders,
the online-booking pause, the company's 2FA requirement and its note to
customers, built from their declarations."""

from __future__ import annotations

from typing import Any

from django.db.models import F
from django.utils import timezone

from saas_core.modules.core.identity.models import UserMfaMethod
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


def _inventory_plan(context: TenantContext) -> None:
    EntitlementSnapshot.all_objects.create(
        organization_id=context.organization_id,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={"inventory.enabled": True},
        quotas={},
        sources={"inventory.enabled": {"kind": "plan"}},
    )


def _with_2fa(context: TenantContext) -> None:
    """The person acting has 2FA — requiring it of them would otherwise shut
    them out, which the change refuses."""
    UserMfaMethod.objects.create(
        user_id=context.actor_id, secret_ciphertext="x", confirmed_at=timezone.now()
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
        arguments=lambda _context: {
            "paused": True,
            "resume_on": None,
            "horizon_days": None,
            "contact": None,
            "reset": None,
        },
        wrong_arguments={
            "paused": "tak",
            "resume_on": None,
            "horizon_days": None,
            "contact": None,
            "reset": None,
        },
        wrong_field="paused",
        stale=_stale("booking.online.paused"),
        state=_values,
        prepare=_booking_plan,
    ),
}

EVALS.update({
    "organization.settings_security.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"mfa_required": "all"},
        wrong_field="mfa_required",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
    ),
    "organization.settings_security.update@1": CommandEval(
        arguments=lambda _context: {"mfa_required": "managers", "reset": None},
        wrong_arguments={"mfa_required": "sometimes", "reset": None},
        wrong_field="mfa_required",
        stale=_stale("organization.security.mfa_required"),
        state=_values,
        prepare=_with_2fa,
    ),
})


def _note(polish: str) -> dict[str, str | None]:
    """The note's change as the command takes it: Polish set, the rest kept."""
    from django.conf import settings

    return {code: (polish if code == "pl" else None) for code in settings.LOCALE_REGISTRY}


EVALS.update({
    "notifications.settings_customer_mail.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"note": {"pl": "Do zobaczenia"}},
        wrong_field="note",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
    ),
    # @2: a text per language. Every registry language is named; null keeps it.
    "notifications.settings_customer_mail.update@2": CommandEval(
        arguments=lambda _context: {
            "note": _note("Prosimy o przybycie 10 minut wcześniej."),
            "reset": None,
        },
        wrong_arguments={"note": _note("Zapisy na www.studio.test"), "reset": None},
        wrong_field="note",
        stale=_stale("notifications.customer_mail.note"),
        state=_values,
    ),
})

EVALS.update({
    "booking.settings_notices.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"office": True},
        wrong_field="office",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_booking_plan,
    ),
    "booking.settings_notices.update@1": CommandEval(
        arguments=lambda _context: {"office": True, "reset": None},
        wrong_arguments={"office": "tak", "reset": None},
        wrong_field="office",
        stale=_stale("booking.notices.office"),
        state=_values,
        prepare=_booking_plan,
    ),
    "sites.settings_inquiries.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"recipients": "editors"},
        wrong_field="recipients",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
    ),
    "sites.settings_inquiries.update@1": CommandEval(
        arguments=lambda _context: {"recipients": "editors", "reset": None},
        wrong_arguments={"recipients": "everyone", "reset": None},
        wrong_field="recipients",
        stale=_stale("sites.inquiries.recipients"),
        state=_values,
    ),
})

EVALS.update({
    "booking.settings_self_service.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"mode": "none"},
        wrong_field="mode",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_booking_plan,
    ),
    "booking.settings_self_service.update@1": CommandEval(
        arguments=lambda _context: {"mode": "cancel_only", "cutoff_hours": None, "reset": None},
        wrong_arguments={"mode": "sometimes", "cutoff_hours": None, "reset": None},
        wrong_field="mode",
        stale=_stale("booking.self_service.mode"),
        state=_values,
        prepare=_booking_plan,
    ),
})

# The warehouse's groups (phase 10; settings plan M3–M6) — only where it is composed.
INVENTORY_EVALS = {
    "inventory.settings_alerts.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"low_stock": "daily"},
        wrong_field="low_stock",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_inventory_plan,
    ),
    "inventory.settings_alerts.update@1": CommandEval(
        arguments=lambda _context: {
            "low_stock": "daily",
            "places": None,
            "recipients": None,
            "holder": None,
            "hour": 8,
            "reset": None,
        },
        wrong_arguments={
            "low_stock": "daily",
            "places": None,
            "recipients": None,
            "holder": None,
            "hour": 24,
            "reset": None,
        },
        wrong_field="hour",
        stale=_stale("inventory.alerts.low_stock"),
        state=_values,
        prepare=_inventory_plan,
    ),
    "inventory.settings_lots.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"expiring_days": 60},
        wrong_field="expiring_days",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_inventory_plan,
    ),
    "inventory.settings_lots.update@1": CommandEval(
        arguments=lambda _context: {"expiring_days": 60, "expired_sale": None, "reset": None},
        wrong_arguments={"expiring_days": 0, "expired_sale": None, "reset": None},
        wrong_field="expiring_days",
        stale=_stale("inventory.lots.expiring_days"),
        state=_values,
        prepare=_inventory_plan,
    ),
    "inventory.settings_materials.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"source": "lead_person"},
        wrong_field="source",
        stale="nie dotyczy: odczyt nie sprawdza wersji",
        state=_values,
        prepare=_inventory_plan,
    ),
    "inventory.settings_materials.update@1": CommandEval(
        arguments=lambda _context: {"source": "lead_person", "reset": None},
        wrong_arguments={"source": "the_van", "reset": None},
        wrong_field="source",
        stale=_stale("inventory.materials.source"),
        state=_values,
        prepare=_inventory_plan,
    ),
}
