"""A company's customers hear in their own language, German too (TL17c):
every customer mail has a German version, the link to the booking carries
the customer's language prefix, and the date reads as German writes it."""

from __future__ import annotations

from datetime import UTC, datetime

from django.conf import settings
from django.test import override_settings

from saas_core.modules.shared.booking.notify import manage_url
from saas_core.modules.shared.booking.services import local_time
from saas_core.modules.shared.notifications.api import AUDIENCE_CUSTOMER, TEMPLATES
from saas_core.modules.shared.notifications.templates import render_template


def _latest_customer_templates() -> dict[str, int]:
    latest: dict[str, int] = {}
    for (key, version), template in TEMPLATES.items():
        if template.audience == AUDIENCE_CUSTOMER:
            latest[key] = max(latest.get(key, 0), version)
    return latest


def test_every_customer_mail_speaks_german_in_its_latest_version() -> None:
    latest = _latest_customer_templates()
    assert {"booking.confirmation", "booking.reminder", "booking.person_changed"} <= set(latest)
    missing = [
        f"{key} v{version}"
        for key, version in latest.items()
        if "de" not in TEMPLATES[(key, version)].subjects
    ]
    assert missing == []


@override_settings(FRONTEND_BASE_URL="https://business.example.test")
def test_the_booking_link_carries_the_customers_language() -> None:
    assert manage_url("t0k3n", "pl") == "https://business.example.test/booking/t0k3n"
    assert manage_url("t0k3n", "en") == "https://business.example.test/en/booking/t0k3n"
    assert manage_url("t0k3n", "de") == "https://business.example.test/de/booking/t0k3n"


def test_a_german_confirmation_reads_german_with_a_german_date() -> None:
    when = local_time(datetime(2026, 10, 14, 8, 30, tzinfo=UTC), "Europe/Berlin", "de")
    subject, body = render_template(
        key="booking.confirmation",
        version=3,
        locale="de",
        context={
            "organization_name": "Salon Anna",
            "starts_at": when,
            "manage_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/de/booking/t0k3n",
        },
    )

    assert subject == "Buchungsbestätigung"
    assert "Ihre Buchung bei Salon Anna ist bestätigt." in body
    assert "Oktober 2026" in when and "10:30" in when
    assert "/de/booking/t0k3n" in body
