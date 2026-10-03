"""Whose visits a person sees (UX-023): one rule, one place.

By default whoever reads the calendar reads everyone's visits — a small
company's team plans together. A product where that is not so declares the
permission that opens other people's visits in its descriptor
(`appointmentsOfOthersPermission`, settings.BOOKING_OTHERS_PERMISSION):
MedPlano, where a doctor with the staff role must not see another doctor's
patients (GDPR recital 35, health data). Whoever lacks it — and does not plan
visits — sees only the visits they are on.

„On the visit” is one test too: its lead, somebody with its time blocked, or,
once it is called off and nobody's time is, somebody who had it. A lead taken
off a visit that now waits for somebody else is not on it. A visit that takes
nobody (a stay, ADR-072 §2) is nobody's own.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import Q

from .models import AppointmentStatus

#: The permission of whoever plans visits; it always sees everyone's.
PLANS = "booking.appointment.manage"


def others_permission() -> str | None:
    return getattr(settings, "BOOKING_OTHERS_PERMISSION", None)


def sees_others(context: Any) -> bool:
    permission = others_permission()
    return permission is None or context.has_permission(PLANS) or context.has_permission(permission)


def on_visit_q(
    *, staff_id: UUID | None = None, membership_id: UUID | None = None, prefix: str = ""
) -> Q:
    """The visits one person is on, by calendar entry or by membership;
    `prefix` reaches them from a related model (e.g. "appointment__")."""

    def field(name: str) -> str:
        return f"{prefix}{name}"

    if not staff_id and not membership_id:
        # Nobody named: a service context, or a person without a membership —
        # never "every visit whose people have no account".
        return Q(pk__in=[])
    if staff_id:
        lead = Q(**{field("staff_id"): staff_id})
        allocated = Q(**{field("staff_allocations__staff_id"): staff_id})
    else:
        lead = Q(**{field("staff__membership_id"): membership_id})
        allocated = Q(**{field("staff_allocations__staff__membership_id"): membership_id})
    return (
        (lead & Q(**{field("needs_assignment"): False}))
        | (allocated & Q(**{field("staff_allocations__active"): True}))
        | (allocated & Q(**{field("status"): AppointmentStatus.CANCELED}))
    )


def own_visits_q(context: Any, prefix: str = "") -> Q:
    """The caller's own visits."""
    return on_visit_q(membership_id=context.membership_id, prefix=prefix)
