"""The self-service link outlives the booking it opens (ADR-072, Konsekwencje):
a reminder the day before a visit two months ahead must not carry a dead link."""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from saas_core.modules.shared.booking.models import SelfServiceRoute
from saas_core.modules.shared.booking.services import create_appointment, reschedule_appointment
from test_booking import company_today, membership, tenant
from test_booking_slots import at, team

pytestmark = pytest.mark.django_db


@override_settings(BOOKING_SELF_SERVICE_TTL_DAYS=30)
def test_the_link_lives_until_the_booking_ends_and_moves_with_it() -> None:
    owner = membership("link-do-konca")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    far = company_today() + timedelta(days=60)
    with tenant(owner):
        visit = create_appointment(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            starts_at=at(far, 9),
            customer_data={"display_name": "Klient", "email": "klient@example.test"},
            idempotency_key="daleko",
            principal_ref=str(owner.user_id),
        ).appointment
        route = SelfServiceRoute.objects.get(appointment_id=visit.id)
        assert visit.self_service_expires_at == visit.ends_at == route.expires_at

        later = reschedule_appointment(
            appointment_id=visit.id,
            starts_at=at(far + timedelta(days=30), 10),
            idempotency_key="pozniej",
            principal_ref=str(owner.user_id),
        )
        route.refresh_from_db()
        assert later.self_service_expires_at == later.ends_at == route.expires_at

        # Moved back, the link keeps the longer life it already had.
        sooner = reschedule_appointment(
            appointment_id=visit.id,
            starts_at=at(far, 9),
            idempotency_key="wczesniej",
            principal_ref=str(owner.user_id),
        )
        route.refresh_from_db()
        assert sooner.self_service_expires_at == route.expires_at > sooner.ends_at


@override_settings(BOOKING_SELF_SERVICE_TTL_DAYS=30)
def test_a_booking_soon_keeps_the_thirty_days() -> None:
    owner = membership("link-blisko")
    configured = team(owner, people=1, hours=(time(8), time(16)), duration=60)
    soon = company_today() + timedelta(days=2)
    before = timezone.now()
    with tenant(owner):
        visit = create_appointment(
            service_id=configured["service"].id,
            location_id=configured["location"].id,
            starts_at=at(soon, 9),
            customer_data={"display_name": "Klient", "email": "klient@example.test"},
            idempotency_key="blisko",
            principal_ref=str(owner.user_id),
        ).appointment
    assert visit.self_service_expires_at >= before + timedelta(days=30)
