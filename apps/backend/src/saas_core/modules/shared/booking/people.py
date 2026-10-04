"""Which customers the caller sees in the calendar, and how much of each
(ADR-076, uzupełnienie 2026-10-04 „karty osób”) — the calendar's own rule
(ADR-067, UX-023), said to `shared.customers` for the cards the assistant's
conversation shows: the name on every visit the caller sees, the e-mail and
the phone where they plan visits or are on that one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.shared.billing.api import FeatureOperation
from saas_core.modules.shared.billing.authorization import authorize_entitled
from saas_core.modules.shared.customers.api import Sight

from .models import Appointment, AppointmentStatus
from .services import BOOKING_ENABLED, BOOKING_MANAGE, BOOKING_READ, visible_contacts
from .visibility import own_visits_q, sees_others

_REQUESTS = {
    "title": {"pl": "Prośby o rezerwację", "en": "Booking requests"},
    "href": "/panel/calendar/requests",
}
_VISIT = {"pl": "Wizyta w kalendarzu", "en": "The visit in the calendar"}


def customers_in_calendar(ids: Sequence[UUID]) -> dict[UUID, Sight]:
    try:
        context = authorize_entitled(BOOKING_READ, BOOKING_ENABLED, operation=FeatureOperation.READ)
    except APIException:
        return {}
    visits = Appointment.all_objects.filter(
        organization_id=context.organization_id, customer_id__in=list(ids)
    )
    if not sees_others(context):
        visits = visits.filter(own_visits_q(context))
    rows = list(
        visits.order_by("starts_at", "id")
        .values_list("id", "customer_id", "starts_at", "timezone", "status")
        .distinct()
    )
    contacts = visible_contacts([row[0] for row in rows])
    now = timezone.now()
    answers = context.has_permission(BOOKING_MANAGE)
    seen: dict[UUID, Sight] = {}
    linked: dict[UUID, Any] = {}
    for visit_id, customer_id, starts_at, zone, status in rows:
        before = seen.get(customer_id)
        contact = visit_id in contacts or bool(before and before.contact)
        # The link goes to the next visit ahead, else to the last one behind.
        chosen = linked.get(customer_id)
        if chosen is None or chosen[0] < now:
            chosen = linked[customer_id] = (starts_at, zone, status)
        waits = chosen[2] == AppointmentStatus.PENDING_REQUEST and answers
        day = chosen[0].astimezone(ZoneInfo(chosen[1])).date().isoformat()
        link = (
            _REQUESTS
            if waits
            else {"title": _VISIT, "href": f"/panel/calendar?view=day&date={day}"}
        )
        seen[customer_id] = Sight(contact=contact, links=(link,))
    return seen
